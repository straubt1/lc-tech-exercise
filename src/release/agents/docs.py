"""Docs agent. Reads the candidate ref and compares it with the diff summary."""

from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from release.config import split_repo
from release.model import StubChatModel, resolve_model
from release.prompts import load_prompt
from release.state import ReleaseState
from release.tools.github_read import make_docs_tools


class DocFinding(BaseModel):
    """One documentation issue and the file it belongs to."""

    filename: str = Field(description="Repository path of the file to change.")
    finding: str = Field(description="The docs issue and the edit that resolves it.")


class DocsReport(BaseModel):
    """Documentation verdict. This agent does not choose a version bump."""

    docs_ready: bool = Field(
        description="True only when the README, changelog, and every variable and output pass."
    )
    summary: str = Field(description="What is missing or inaccurate. Empty when docs_ready is true.")
    findings: list[DocFinding] = Field(
        description="One object per docs issue, with filename and finding. Empty when docs_ready is true."
    )


def build_docs_agent(
    model: StubChatModel | None = None,
    *,
    owner: str = "octo",
    repo: str = "mod",
    candidate_ref: str = "latest",
):
    return create_agent(
        model=model or StubChatModel(),
        tools=make_docs_tools(owner, repo, candidate_ref),
        system_prompt=load_prompt("docs.md"),
        response_format=DocsReport,
        name="docs",
    )


def _report_from(result: DocsReport | dict[str, Any]) -> DocsReport:
    if isinstance(result, DocsReport):
        return result
    return DocsReport.model_validate(result)


def _task(state: ReleaseState, owner: str, repo: str) -> str:
    paths = state.get("changed_paths") or []
    path_lines = "\n".join(f"- {path}" for path in paths) or "- (none)"
    return "\n".join(
        [
            f"Repository {owner}/{repo}.",
            f"Candidate ref {state.get('candidate_ref', '')}.",
            f"Base tag {state.get('base_ref') or '(none)'}.",
            "Changed paths:",
            path_lines,
            "Diff summary:",
            state.get("diff_summary") or "(none)",
            f"Change category: {state.get('change_category') or '(none)'}",
        ]
    )


def docs_node(state: ReleaseState) -> dict[str, Any]:
    owner, repo = split_repo(state["repo"])
    agent = build_docs_agent(
        resolve_model(),
        owner=owner,
        repo=repo,
        candidate_ref=state["candidate_ref"],
    )
    result = agent.invoke({"messages": [HumanMessage(content=_task(state, owner, repo))]})
    report = result.get("structured_response")
    if report is None:
        raise RuntimeError("docs agent did not return a report")
    decision = _report_from(report)
    findings = [
        {"filename": item.filename.strip(), "finding": item.finding.strip()}
        for item in decision.findings
        if item.filename.strip() and item.finding.strip()
    ]
    ready = decision.docs_ready and not findings
    summary = decision.summary.strip()
    if not ready and not summary:
        summary = "Documentation is not ready."
    return {
        "docs_ready": ready,
        "docs_findings": {
            "status": "ready" if ready else "not_ready",
            "summary": summary,
            "findings": findings,
        },
    }
