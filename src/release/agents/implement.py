"""Implement agent. Applies suggestions so the next release run can say ready."""

from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from release.config import split_repo
from release.model import StubChatModel, resolve_model
from release.prompts import load_prompt
from release.state import ReleaseState
from release.tools.github_read import make_docs_tools

_MAX_FILE = 100_000
_MAX_FILES = 20


class FileEdit(BaseModel):
    """One full file at the candidate ref after the suggestion is applied."""

    path: str = Field(description="Repository path. Relative, with no .. segments.")
    content: str = Field(description="Full new text of that file.")


class ImplementReport(BaseModel):
    """Files to commit. This agent does not open a pull request."""

    summary: str = Field(description="What changed, in one short paragraph.")
    files: list[FileEdit] = Field(description="Only the files that had to change.")


def build_implement_agent(
    model: StubChatModel | None = None,
    *,
    owner: str = "octo",
    repo: str = "mod",
    candidate_ref: str = "latest",
):
    return create_agent(
        model=model or StubChatModel(),
        tools=make_docs_tools(owner, repo, candidate_ref),
        system_prompt=load_prompt("implement.md"),
        response_format=ImplementReport,
        name="implement",
    )


def _report_from(result: ImplementReport | dict[str, Any]) -> ImplementReport:
    if isinstance(result, ImplementReport):
        return result
    return ImplementReport.model_validate(result)


def _check_path(path: str) -> None:
    if not path or path.startswith("/") or ".." in path.split("/"):
        raise RuntimeError(f"implement agent returned an unsafe path: {path}")


def _edits(report: ImplementReport) -> list[tuple[str, str]]:
    chosen: dict[str, str] = {}
    order: list[str] = []
    for item in report.files:
        path = item.path.strip()
        _check_path(path)
        if not item.content.strip():
            raise RuntimeError(f"implement agent returned an empty file: {path}")
        if len(item.content) > _MAX_FILE:
            raise RuntimeError(f"implement agent returned a file that is too large: {path}")
        if path not in chosen:
            order.append(path)
        chosen[path] = item.content
    if len(order) > _MAX_FILES:
        raise RuntimeError("implement agent returned too many files")
    return [(path, chosen[path]) for path in order]


def _task(state: ReleaseState, suggestions: list[str]) -> str:
    lines = "\n".join(f"- {item}" for item in suggestions) or "- (none)"
    return "\n".join(
        [
            f"Repository {state.get('repo', '')}.",
            f"Candidate ref {state.get('candidate_ref', '')}.",
            f"Proposed version {state.get('proposed_version') or '(none)'}.",
            "Diff summary:",
            state.get("diff_summary") or "(none)",
            "Suggestions:",
            lines,
        ]
    )


def implement_suggestions(state: ReleaseState, suggestions: list[str]) -> list[tuple[str, str]]:
    owner, repo = split_repo(state["repo"])
    agent = build_implement_agent(
        resolve_model(),
        owner=owner,
        repo=repo,
        candidate_ref=state.get("candidate_ref") or "latest",
    )
    result = agent.invoke({"messages": [HumanMessage(content=_task(state, suggestions))]})
    report = result.get("structured_response")
    if report is None:
        raise RuntimeError("implement agent did not return a report")
    return _edits(_report_from(report))
