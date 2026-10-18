"""Public GitHub reads. No token is sent."""

import base64
import difflib
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from urllib.parse import quote

from langchain_core.tools import tool

_VERSION = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_API = "https://api.github.com"
_MAX_PATCH = 4000
_MAX_FILES = 40
_MAX_BLOB = 200_000
_github_transport: ContextVar[Callable[[str], Any] | None] = ContextVar("github_transport", default=None)


def version_key(name: str) -> tuple[int, int, int] | None:
    match = _VERSION.fullmatch(name)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def published_tags(raw_tags: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Keep vMAJOR.MINOR.PATCH tags and sort the highest semver first."""
    chosen: list[dict[str, str]] = []
    for tag in raw_tags:
        name = str(tag.get("name", ""))
        if version_key(name) is None:
            continue
        commit = tag.get("commit") or {}
        sha = str(commit.get("sha", ""))
        if sha:
            chosen.append({"name": name, "sha": sha})
    chosen.sort(key=lambda item: version_key(item["name"]) or (0, 0, 0), reverse=True)
    return chosen


@contextmanager
def use_github_transport(transport: Callable[[str], Any]):
    """Serve GitHub reads for one example. Unset, reads stay on the public API."""
    token = _github_transport.set(transport)
    try:
        yield
    finally:
        _github_transport.reset(token)


def github_get(path: str) -> Any:
    transport = _github_transport.get()
    if transport is not None:
        return transport(path)
    request = urllib.request.Request(
        _API + path,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "lc-tech-exercise",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"GitHub {exc.code} for {path}: {detail}") from exc


def _repo_path(owner: str, repo: str, suffix: str) -> str:
    return f"/repos/{quote(owner)}/{quote(repo)}{suffix}"


def commit_sha(owner: str, repo: str, ref: str) -> str:
    payload = github_get(_repo_path(owner, repo, f"/commits/{quote(ref, safe='')}"))
    sha = str(payload.get("sha", ""))
    if not sha:
        raise RuntimeError(f"GitHub did not return a commit sha for {ref}")
    return sha


def fetch_version_tags(owner: str, repo: str) -> list[dict[str, str]]:
    found: list[dict[str, Any]] = []
    for page in range(1, 11):
        batch = github_get(_repo_path(owner, repo, f"/tags?per_page=100&page={page}"))
        if not isinstance(batch, list):
            raise RuntimeError("GitHub tags response was not a list")
        found.extend(batch)
        if len(batch) < 100:
            break
    return published_tags(found)


def _clip(text: str) -> str:
    if len(text) <= _MAX_PATCH:
        return text
    return text[:_MAX_PATCH] + "\n... truncated"


def _unified(path: str, old: str, new: str) -> str:
    lines = difflib.unified_diff(
        old.splitlines(),
        new.splitlines(),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    return _clip("\n".join(lines))


def _line_counts(patch: str) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for line in patch.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions


def _file_text(owner: str, repo: str, path: str, ref: str) -> str | None:
    """File body at a ref from the contents API. Comparison stays local."""
    suffix = f"/contents/{quote(path, safe='/')}?ref={quote(ref, safe='')}"
    payload = github_get(_repo_path(owner, repo, suffix))
    if not isinstance(payload, dict):
        return None
    if payload.get("encoding") != "base64" or int(payload.get("size") or 0) > _MAX_BLOB:
        return None
    raw = base64.b64decode(payload.get("content") or "")
    if b"\0" in raw:
        return None
    return raw.decode("utf-8", errors="replace")


def _tree_blobs(owner: str, repo: str, sha: str) -> dict[str, str]:
    payload = github_get(_repo_path(owner, repo, f"/git/trees/{sha}?recursive=1"))
    if payload.get("truncated"):
        raise RuntimeError(f"Git tree for {sha} is truncated")
    return {
        item["path"]: item["sha"]
        for item in payload.get("tree") or []
        if item.get("type") == "blob" and item.get("path") and item.get("sha")
    }


def files_from_snapshots(
    base: dict[str, str],
    head: dict[str, str],
    read_base: Callable[[str], str | None],
    read_head: Callable[[str], str | None],
) -> list[dict[str, Any]]:
    """Diff two path-to-blob maps. Callers download contents and compare here."""
    files: list[dict[str, Any]] = []
    for path in sorted(set(base) | set(head)):
        if path in base and path in head and base[path] == head[path]:
            continue
        if path not in base:
            status = "added"
            old, new = "", read_head(path) or ""
        elif path not in head:
            status = "removed"
            old, new = read_base(path) or "", ""
        else:
            status = "modified"
            old, new = read_base(path) or "", read_head(path) or ""
        patch = _unified(path, old, new)
        additions, deletions = _line_counts(patch)
        files.append(
            {
                "path": path,
                "status": status,
                "additions": additions,
                "deletions": deletions,
                "patch": patch,
            }
        )
        if len(files) >= _MAX_FILES:
            break
    return files


def diff_refs(owner: str, repo: str, base: str, head: str) -> dict[str, Any]:
    base_sha = commit_sha(owner, repo, base)
    head_sha = commit_sha(owner, repo, head)
    files = files_from_snapshots(
        _tree_blobs(owner, repo, base_sha),
        _tree_blobs(owner, repo, head_sha),
        lambda path: _file_text(owner, repo, path, base),
        lambda path: _file_text(owner, repo, path, head),
    )
    return {
        "base_ref": base,
        "base_sha": base_sha,
        "candidate_ref": head,
        "candidate_sha": head_sha,
        "files": files,
    }


def make_diff_tools(owner: str, repo: str, candidate_ref: str):
    """Tools bound to one public repository. The model cannot choose another repo."""

    @tool
    def list_version_tags() -> str:
        """List published vMAJOR.MINOR.PATCH tags, highest semver first."""
        return json.dumps({"tags": fetch_version_tags(owner, repo)})

    @tool
    def compare_refs(base: str) -> str:
        """Download a vMAJOR.MINOR.PATCH tag and the candidate ref, then diff them locally."""
        if version_key(base) is None:
            return json.dumps({"error": "base must be a vMAJOR.MINOR.PATCH tag"})
        return json.dumps(diff_refs(owner, repo, base, candidate_ref))

    return [list_version_tags, compare_refs]


_MAX_DOC = 20_000


def list_files(owner: str, repo: str, ref: str) -> list[str]:
    sha = commit_sha(owner, repo, ref)
    return sorted(_tree_blobs(owner, repo, sha))


def read_file(owner: str, repo: str, path: str, ref: str) -> str:
    if path.startswith("/") or ".." in path.split("/"):
        return json.dumps({"error": "path must stay inside the repository", "path": path})
    try:
        text = _file_text(owner, repo, path, ref)
    except RuntimeError as exc:
        if "GitHub 404" not in str(exc):
            raise
        return json.dumps({"error": "not found", "path": path})
    if text is None:
        return json.dumps({"error": "unreadable", "path": path})
    if len(text) > _MAX_DOC:
        return text[:_MAX_DOC] + "\n... truncated"
    return text


def make_docs_tools(owner: str, repo: str, candidate_ref: str):
    """Tools bound to the candidate ref. The model cannot choose another repo."""

    @tool
    def list_candidate_files() -> str:
        """List file paths at the configured candidate ref."""
        return json.dumps({"files": list_files(owner, repo, candidate_ref)})

    @tool
    def read_candidate_file(path: str) -> str:
        """Read one file at the configured candidate ref."""
        return read_file(owner, repo, path, candidate_ref)

    return [list_candidate_files, read_candidate_file]
