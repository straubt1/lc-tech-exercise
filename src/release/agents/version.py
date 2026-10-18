"""Version agent. No tools. Chooses major, minor, or patch. Not invoked yet."""

from typing import Any

from langchain.agents import create_agent

from release.model import StubChatModel
from release.prompts import load_prompt
from release.state import ReleaseState

VERSION_TOOLS: list = []


def build_version_agent(model: StubChatModel | None = None):
    return create_agent(
        model=model or StubChatModel(),
        tools=VERSION_TOOLS,
        system_prompt=load_prompt("version.md"),
        name="version",
    )


def version_node(_state: ReleaseState) -> dict[str, Any]:
    build_version_agent()
    return {
        "bump": "",
        "proposed_version": "",
        "reasons": ["stub: version agent is not implemented"],
        "release_notes": "",
    }
