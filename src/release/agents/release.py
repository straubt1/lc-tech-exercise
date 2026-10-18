"""Release agent. Human gate, then a draft GitHub Release. The tool is not called yet."""

from typing import Any

from langchain.agents import create_agent
from langgraph.types import interrupt

from release.model import StubChatModel
from release.prompts import load_prompt
from release.state import ReleaseState
from release.tools.github_release import create_draft_release

RELEASE_TOOLS = [create_draft_release]


def build_release_agent(model: StubChatModel | None = None):
    return create_agent(
        model=model or StubChatModel(),
        tools=RELEASE_TOOLS,
        system_prompt=load_prompt("release.md"),
        name="release",
    )


def release_node(state: ReleaseState) -> dict[str, Any]:
    decision = interrupt(
        {
            "repo": state.get("repo", ""),
            "candidate_ref": state.get("candidate_ref", ""),
            "base_ref": state.get("base_ref", ""),
            "bump": state.get("bump", ""),
            "proposed_version": state.get("proposed_version", ""),
            "release_notes": state.get("release_notes", ""),
            "diff_summary": state.get("diff_summary", ""),
            "docs_findings": state.get("docs_findings", {}),
            "regression_findings": state.get("regression_findings", {}),
            "reasons": state.get("reasons", []),
        }
    )
    if not isinstance(decision, dict) or decision.get("decision") not in {"approved", "rejected"}:
        raise RuntimeError("human gate returned an unexpected payload")
    if decision["decision"] != "approved":
        return {
            "human_decision": "rejected",
            "release_result": {"status": "rejected", "tag": "", "url": ""},
        }
    build_release_agent()
    return {
        "human_decision": "approved",
        "release_result": {
            "status": "stub",
            "tag": state.get("proposed_version", ""),
            "url": "",
        },
    }
