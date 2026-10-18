"""Docs agent. Reads README and CHANGELOG from the public repo. Not invoked yet."""

from typing import Any

from langchain.agents import create_agent

from release.model import StubChatModel
from release.prompts import load_prompt
from release.state import ReleaseState
from release.tools.github_read import read_repo_file

DOCS_TOOLS = [read_repo_file]


def build_docs_agent(model: StubChatModel | None = None):
    return create_agent(
        model=model or StubChatModel(),
        tools=DOCS_TOOLS,
        system_prompt=load_prompt("docs.md"),
        name="docs",
    )


def docs_node(_state: ReleaseState) -> dict[str, Any]:
    build_docs_agent()
    return {
        "docs_ready": False,
        "docs_findings": {
            "status": "stub",
            "summary": "stub: docs agent is not implemented",
        },
    }
