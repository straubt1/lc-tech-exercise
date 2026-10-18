"""Diff agent. Reads public tags and compares them to the candidate ref."""

from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from release.config import split_repo
from release.model import StubChatModel, resolve_model
from release.prompts import load_prompt
from release.state import ReleaseState
from release.tools.github_read import make_diff_tools, version_key


class DiffReport(BaseModel):
    """Structured result copied from the compare tool."""

    base_ref: str = Field(description="Highest published vMAJOR.MINOR.PATCH tag.")
    candidate_sha: str = Field(description="Full commit sha of the candidate ref from the compare tool.")
    changed_paths: list[str] = Field(description="Files that differ from the last published tag.")
    diff_summary: str = Field(description="Summary of edits since the last published tag.")
    change_category: str = Field(
        description="One short label for the type of change since the last published tag. Not a version bump."
    )


def build_diff_agent(
    model: StubChatModel | None = None,
    *,
    owner: str = "octo",
    repo: str = "mod",
    candidate_ref: str = "latest",
):
    return create_agent(
        model=model or StubChatModel(),
        tools=make_diff_tools(owner, repo, candidate_ref),
        system_prompt=load_prompt("diff.md"),
        response_format=DiffReport,
        name="diff",
    )


def _report_from(result: DiffReport | dict[str, Any]) -> DiffReport:
    if isinstance(result, DiffReport):
        return result
    return DiffReport.model_validate(result)


def diff_node(state: ReleaseState) -> dict[str, Any]:
    owner, repo = split_repo(state["repo"])
    candidate_ref = state["candidate_ref"]
    agent = build_diff_agent(
        resolve_model(),
        owner=owner,
        repo=repo,
        candidate_ref=candidate_ref,
    )
    result = agent.invoke(
        {
            "messages": [
                HumanMessage(content=f"Repository {owner}/{repo}. Candidate ref {candidate_ref}.")
            ]
        }
    )
    report = result.get("structured_response")
    if report is None:
        raise RuntimeError("diff agent did not return a report")
    decision = _report_from(report)
    if version_key(decision.base_ref) is None:
        raise RuntimeError(f"diff agent returned unknown base ref {decision.base_ref}")
    if not decision.candidate_sha:
        raise RuntimeError("diff agent did not return a candidate sha")
    category = decision.change_category.strip()
    if not category:
        raise RuntimeError("diff agent did not return a change category")
    if category.lower() in {"major", "minor", "patch"}:
        raise RuntimeError("diff agent returned a version bump instead of a change category")
    return {
        "base_ref": decision.base_ref,
        "candidate_sha": decision.candidate_sha,
        "changed_paths": [path for path in decision.changed_paths if path],
        "diff_summary": decision.diff_summary.strip(),
        "change_category": category,
    }
