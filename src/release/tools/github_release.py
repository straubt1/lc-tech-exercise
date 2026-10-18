"""Draft GitHub Release. GH_TOKEN is read inside the tool later, never as an argument."""

from langchain_core.tools import tool


@tool
def create_draft_release(owner: str, repo: str, tag: str, notes: str) -> str:
    """Create a draft GitHub Release. The token stays in the environment."""
    return "not implemented"
