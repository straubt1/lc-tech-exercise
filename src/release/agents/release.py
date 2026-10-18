"""Release recommendation, then a draft release or a draft pull request."""

import json
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from release.agents.implement import implement_suggestions
from release.config import split_repo
from release.model import StubChatModel, resolve_model
from release.prompts import load_prompt
from release.state import ReleaseState
from release.tools.github_release import (
    create_draft_pull_request,
    create_draft_release,
    writes_enabled,
)

RELEASE_TOOLS: list = []


class ReleaseRecommendation(BaseModel):
    """Ready or not. Publishing happens only after a person says yes."""

    ready: bool = Field(description="True only when this module can be released at the proposed version.")
    recommendation: str = Field(description="Short reason for the ready or not-ready call.")
    suggestions: list[str] = Field(
        description="File edits that would make the next run ready. Empty when ready is true."
    )


def format_facts(source: dict[str, Any]) -> str:
    docs = "yes" if source.get("docs_ready") else "no"
    category = source.get("change_category") or "(none)"
    return "\n".join(
        [
            "Diff:",
            str(source.get("diff_summary") or "(none)"),
            f"Change: {category}",
            f"Suggested version: {source.get('proposed_version') or '(none)'}",
            f"Docs are ready: {docs}",
        ]
    )


def format_recommendation(source: dict[str, Any]) -> str:
    lines = [
        "Recommendation:",
        str(source.get("recommendation") or "(none)"),
    ]
    suggestions = [item for item in (source.get("suggestions") or []) if item]
    if suggestions:
        lines.append("Suggestions:")
        lines.extend(f"- {item}" for item in suggestions)
    return "\n".join(lines)


def build_release_agent(model: StubChatModel | None = None):
    return create_agent(
        model=model or StubChatModel(),
        tools=RELEASE_TOOLS,
        system_prompt=load_prompt("release.md"),
        response_format=ReleaseRecommendation,
        name="release",
    )


def _report_from(result: ReleaseRecommendation | dict[str, Any]) -> ReleaseRecommendation:
    if isinstance(result, ReleaseRecommendation):
        return result
    return ReleaseRecommendation.model_validate(result)


def _finding_text(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        filename = str(item.get("filename") or "").strip()
        finding = str(item.get("finding") or "").strip()
        if filename and finding:
            return f"{filename}: {finding}"
        return finding or filename
    return ""


def _finding_lines(items: list[Any]) -> list[str]:
    return [text for text in (_finding_text(item) for item in items) if text]


def _task(state: ReleaseState) -> str:
    paths = state.get("changed_paths") or []
    path_lines = "\n".join(f"- {path}" for path in paths) or "- (none)"
    docs = state.get("docs_findings") or {}
    findings = _finding_lines(docs.get("findings") or [])
    finding_lines = "\n".join(f"- {item}" for item in findings) or "- (none)"
    reasons = [str(item) for item in (state.get("reasons") or []) if str(item).strip()]
    reason_lines = "\n".join(f"- {item}" for item in reasons) or "- (none)"
    return "\n".join(
        [
            f"Repository {state.get('repo', '')}.",
            f"Candidate ref {state.get('candidate_ref', '')}.",
            f"Base tag {state.get('base_ref') or '(none)'}.",
            "Changed paths:",
            path_lines,
            "Diff summary:",
            state.get("diff_summary") or "(none)",
            f"Change category: {state.get('change_category') or '(none)'}",
            f"Docs ready: {bool(state.get('docs_ready'))}",
            f"Docs status: {docs.get('status') or '(none)'}",
            f"Docs summary: {docs.get('summary') or '(none)'}",
            "Docs findings:",
            finding_lines,
            f"Bump: {state.get('bump') or '(none)'}",
            f"Proposed version: {state.get('proposed_version') or '(none)'}",
            "Version reasons:",
            reason_lines,
            "Release notes:",
            state.get("release_notes") or "(none)",
            "Regression has not run. Ignore it.",
        ]
    )


def _finalize(state: ReleaseState, decision: ReleaseRecommendation) -> ReleaseRecommendation:
    suggestions = [item.strip() for item in decision.suggestions if item.strip()]
    if not state.get("docs_ready"):
        if not suggestions:
            findings = state.get("docs_findings") or {}
            suggestions = _finding_lines(findings.get("findings") or [])
        if not suggestions:
            summary = str((state.get("docs_findings") or {}).get("summary") or "").strip()
            suggestions = [summary or "Documentation is not ready."]
        ready = False
    else:
        ready = decision.ready
        if ready:
            suggestions = []
    recommendation = decision.recommendation.strip() or (
        "Ready to release." if ready else "Not ready to release."
    )
    return ReleaseRecommendation(ready=ready, recommendation=recommendation, suggestions=suggestions)


def recommend(state: ReleaseState) -> ReleaseRecommendation:
    agent = build_release_agent(resolve_model())
    result = agent.invoke({"messages": [HumanMessage(content=_task(state))]})
    report = result.get("structured_response")
    if report is None:
        raise RuntimeError("release agent did not return a recommendation")
    return _finalize(state, _report_from(report))


def recommend_node(state: ReleaseState) -> dict[str, Any]:
    print(format_facts(state), flush=True)
    report = recommend(state)
    return {
        "ready_for_release": report.ready,
        "recommendation": report.recommendation,
        "suggestions": list(report.suggestions),
    }


def _packet(state: ReleaseState) -> dict[str, Any]:
    return {
        "repo": state.get("repo", ""),
        "candidate_ref": state.get("candidate_ref", ""),
        "base_ref": state.get("base_ref", ""),
        "bump": state.get("bump", ""),
        "proposed_version": state.get("proposed_version", ""),
        "release_notes": state.get("release_notes", ""),
        "diff_summary": state.get("diff_summary", ""),
        "change_category": state.get("change_category", ""),
        "docs_ready": bool(state.get("docs_ready")),
        "docs_findings": state.get("docs_findings") or {},
        "reasons": state.get("reasons") or [],
        "ready": bool(state.get("ready_for_release")),
        "recommendation": state.get("recommendation", ""),
        "suggestions": list(state.get("suggestions") or []),
    }


def _kept(state: ReleaseState) -> dict[str, Any]:
    return {
        "ready_for_release": bool(state.get("ready_for_release")),
        "recommendation": state.get("recommendation", ""),
        "suggestions": list(state.get("suggestions") or []),
    }


def _draft_release(state: ReleaseState) -> dict[str, str]:
    owner, repo = split_repo(state["repo"])
    tag = state.get("proposed_version", "")
    raw = create_draft_release.invoke(
        {
            "owner": owner,
            "repo": repo,
            "tag": tag,
            "notes": state.get("release_notes", ""),
            "target": state.get("candidate_sha", ""),
        }
    )
    if not isinstance(raw, str):
        raise RuntimeError("draft release tool returned an unexpected payload")
    parsed = json.loads(raw)
    return {
        "status": str(parsed.get("status", "")),
        "tag": str(parsed.get("tag", "")),
        "url": str(parsed.get("url", "")),
        "branch": "",
        "action": "release",
    }


def _draft_pull_request(state: ReleaseState) -> dict[str, str]:
    if not writes_enabled():
        return {"status": "dry_run", "tag": "", "url": "", "branch": "", "action": "pull_request"}
    suggestions = [str(item) for item in (state.get("suggestions") or []) if str(item).strip()]
    files = implement_suggestions(state, suggestions)
    if not files:
        return {"status": "no_changes", "tag": "", "url": "", "branch": "", "action": "pull_request"}
    owner, repo = split_repo(state["repo"])
    version = state.get("proposed_version") or "next"
    title = f"Apply release suggestions for {version}"
    body = "\n".join(
        [
            state.get("recommendation") or "Apply the release suggestions.",
            "",
            "Suggestions:",
            *[f"- {item}" for item in suggestions],
        ]
    )
    return create_draft_pull_request(
        owner,
        repo,
        state.get("candidate_ref", ""),
        state.get("candidate_sha", ""),
        version,
        title,
        body,
        files,
    )


def release_node(state: ReleaseState) -> dict[str, Any]:
    decision = interrupt(_packet(state))
    if not isinstance(decision, dict) or decision.get("decision") not in {"yes", "no"}:
        raise RuntimeError("human gate returned an unexpected payload")
    kept = _kept(state)
    if decision["decision"] == "no":
        return {
            **kept,
            "human_decision": "exit",
            "release_result": {"status": "exit", "tag": "", "url": "", "branch": "", "action": ""},
        }
    if state.get("ready_for_release"):
        return {
            **kept,
            "suggestions": [],
            "human_decision": "draft_release",
            "release_result": _draft_release(state),
        }
    return {
        **kept,
        "human_decision": "draft_pr",
        "release_result": _draft_pull_request(state),
    }
