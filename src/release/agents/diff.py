"""Diff agent. Reads public tags and the compare API. Not invoked yet."""

from typing import Any

from langchain.agents import create_agent

from release.model import StubChatModel
from release.prompts import load_prompt
from release.state import ReleaseState
from release.tools.github_read import compare_refs, list_version_tags

DIFF_TOOLS = [list_version_tags, compare_refs]


def build_diff_agent(model: StubChatModel | None = None):
    return create_agent(
        model=model or StubChatModel(),
        tools=DIFF_TOOLS,
        system_prompt=load_prompt("diff.md"),
        name="diff",
    )


def diff_node(_state: ReleaseState) -> dict[str, Any]:
    """Construct the agent so the tool wiring stays real. Invocation is later."""
    build_diff_agent()
    return {
        "base_ref": "",
        "candidate_sha": "",
        "changed_paths": [],
        "diff_summary": "stub: diff agent is not implemented",
    }
