"""Public GitHub reads. No token. Not implemented yet."""

from langchain_core.tools import tool


@tool
def list_version_tags(owner: str, repo: str) -> str:
    """List published vMAJOR.MINOR.PATCH tags on a public GitHub repository."""
    return "not implemented"


@tool
def compare_refs(owner: str, repo: str, base: str, head: str) -> str:
    """Compare a published tag to the candidate ref on a public GitHub repository."""
    return "not implemented"


@tool
def read_repo_file(owner: str, repo: str, path: str, ref: str) -> str:
    """Read one file from a public GitHub repository at a ref."""
    return "not implemented"
