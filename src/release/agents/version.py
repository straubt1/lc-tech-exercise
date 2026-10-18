"""Version agent. No tools. Chooses major, minor, or patch from the diff."""

from typing import Any, Literal

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from release.model import StubChatModel, resolve_model
from release.prompts import load_prompt
from release.state import ReleaseState
from release.tools.github_read import version_key

BumpChoice = Literal["major", "minor", "patch"]
VERSION_TOOLS: list = []


class VersionDecision(BaseModel):
    """Bump choice. The next tag is computed from the base ref, not from the model."""

    bump: BumpChoice = Field(description="One of major, minor, or patch.")
    reasons: list[str] = Field(description="Why this bump applies, citing the diff.")
    release_notes: str = Field(description="Short notes a person can accept.")


def next_version(base_ref: str, bump: BumpChoice) -> str:
    key = version_key(base_ref)
    if key is None:
        raise RuntimeError(f"base ref is not a vMAJOR.MINOR.PATCH tag: {base_ref}")
    major, minor, patch = key
    if bump == "major":
        return f"v{major + 1}.0.0"
    if bump == "minor":
        return f"v{major}.{minor + 1}.0"
    if bump == "patch":
        return f"v{major}.{minor}.{patch + 1}"
    raise RuntimeError(f"version agent returned unknown bump {bump}")


def build_version_agent(model: StubChatModel | None = None):
    return create_agent(
        model=model or StubChatModel(),
        tools=VERSION_TOOLS,
        system_prompt=load_prompt("version.md"),
        response_format=VersionDecision,
        name="version",
    )


def _decision_from(result: VersionDecision | dict[str, Any]) -> VersionDecision:
    if isinstance(result, VersionDecision):
        return result
    return VersionDecision.model_validate(result)


def _task(state: ReleaseState) -> str:
    paths = state.get("changed_paths") or []
    path_lines = "\n".join(f"- {path}" for path in paths) or "- (none)"
    docs = state.get("docs_findings") or {}
    return "\n".join(
        [
            f"Base tag: {state.get('base_ref') or '(none)'}",
            f"Candidate ref: {state.get('candidate_ref') or '(none)'}",
            "Changed paths:",
            path_lines,
            "Diff summary:",
            state.get("diff_summary") or "(none)",
            f"Change category: {state.get('change_category') or '(none)'}",
            "Documentation findings do not change the bump.",
            f"Docs status: {docs.get('status') or '(none)'}",
            f"Docs summary: {docs.get('summary') or '(none)'}",
            "Regression status: not_run. This is not a pass and not a failure.",
        ]
    )


def version_node(state: ReleaseState) -> dict[str, Any]:
    agent = build_version_agent(resolve_model())
    result = agent.invoke({"messages": [HumanMessage(content=_task(state))]})
    report = result.get("structured_response")
    if report is None:
        raise RuntimeError("version agent did not return a decision")
    decision = _decision_from(report)
    reasons = [item.strip() for item in decision.reasons if item.strip()]
    return {
        "bump": decision.bump,
        "proposed_version": next_version(state.get("base_ref", ""), decision.bump),
        "reasons": reasons,
        "release_notes": decision.release_notes.strip(),
    }
