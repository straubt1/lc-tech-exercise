"""Draft GitHub Release and draft pull request. GH_TOKEN is read here, never as an argument."""

import json
import os
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote

from langchain_core.tools import tool

_API = "https://api.github.com"


def writes_enabled() -> bool:
    return os.environ.get("RELEASE_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def suggestion_branch(version: str) -> str:
    cleaned = version.strip().strip("/")
    if not cleaned or "/" in cleaned or cleaned in {".", ".."}:
        raise RuntimeError(f"proposed version cannot name a branch: {version!r}")
    return f"release-suggestions/{cleaned}"


def _token() -> str:
    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GH_TOKEN is not set")
    return token


def _redact(text: str) -> str:
    token = os.environ.get("GH_TOKEN", "").strip()
    if token:
        return text.replace(token, "[redacted]")
    return text


def _reject_secret(text: str) -> None:
    token = os.environ.get("GH_TOKEN", "").strip()
    if token and token in text:
        raise RuntimeError("refusing to send GH_TOKEN to GitHub")


def _repo(owner: str, repo: str, suffix: str) -> str:
    return f"/repos/{quote(owner)}/{quote(repo)}{suffix}"


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode()
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {_token()}",
        "User-Agent": "lc-tech-exercise",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(_API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = _redact(exc.read().decode("utf-8", errors="replace")[:300])
        raise RuntimeError(f"GitHub {exc.code} for {method} {path}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub request failed for {method} {path}") from exc
    if not body:
        return {}
    return json.loads(body)


def _check_files(files: list[tuple[str, str]]) -> None:
    if not files:
        raise RuntimeError("draft pull request needs at least one file")
    for path, content in files:
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise RuntimeError(f"refusing to write an unsafe path: {path}")
        _reject_secret(path)
        _reject_secret(content)


def _create_branch(owner: str, repo: str, branch: str, sha: str) -> str:
    path = _repo(owner, repo, "/git/refs")

    def create(name: str) -> None:
        _request("POST", path, {"ref": f"refs/heads/{name}", "sha": sha})

    try:
        create(branch)
        return branch
    except RuntimeError as exc:
        if "GitHub 422" not in str(exc):
            raise
    alt = f"{branch}-{sha[:7]}"
    create(alt)
    return alt


def _commit_files(
    owner: str,
    repo: str,
    parent_sha: str,
    message: str,
    files: list[tuple[str, str]],
) -> str:
    parent = _request("GET", _repo(owner, repo, f"/git/commits/{quote(parent_sha, safe='')}"))
    tree_sha = str((parent.get("tree") or {}).get("sha") or "")
    if not tree_sha:
        raise RuntimeError("GitHub did not return a tree for the candidate commit")
    items = []
    for path, content in files:
        blob = _request(
            "POST",
            _repo(owner, repo, "/git/blobs"),
            {"content": content, "encoding": "utf-8"},
        )
        blob_sha = str(blob.get("sha") or "")
        if not blob_sha:
            raise RuntimeError(f"GitHub did not return a blob sha for {path}")
        items.append({"path": path, "mode": "100644", "type": "blob", "sha": blob_sha})
    tree = _request(
        "POST",
        _repo(owner, repo, "/git/trees"),
        {"base_tree": tree_sha, "tree": items},
    )
    new_tree = str(tree.get("sha") or "")
    if not new_tree:
        raise RuntimeError("GitHub did not return a tree sha")
    commit = _request(
        "POST",
        _repo(owner, repo, "/git/commits"),
        {"message": message, "tree": new_tree, "parents": [parent_sha]},
    )
    commit_sha = str(commit.get("sha") or "")
    if not commit_sha:
        raise RuntimeError("GitHub did not return a commit sha")
    return commit_sha


def create_draft_pull_request(
    owner: str,
    repo: str,
    base: str,
    parent_sha: str,
    version: str,
    title: str,
    body: str,
    files: list[tuple[str, str]],
) -> dict[str, str]:
    """Commit files on a new branch and open a draft pull request into base."""
    if not writes_enabled():
        return {"status": "dry_run", "tag": "", "url": "", "branch": "", "action": "pull_request"}
    if not parent_sha:
        raise RuntimeError("draft pull request needs the candidate sha")
    if not base:
        raise RuntimeError("draft pull request needs a base ref")
    _check_files(files)
    _reject_secret(title)
    _reject_secret(body)
    branch = suggestion_branch(version)
    message = title.strip() or f"Apply release suggestions for {version}"
    commit_sha = _commit_files(owner, repo, parent_sha, message, files)
    opened = _create_branch(owner, repo, branch, commit_sha)
    payload = _request(
        "POST",
        _repo(owner, repo, "/pulls"),
        {
            "title": title,
            "body": body,
            "head": opened,
            "base": base,
            "draft": True,
        },
    )
    return {
        "status": "draft_pr",
        "tag": "",
        "url": str(payload.get("html_url") or ""),
        "branch": opened,
        "action": "pull_request",
    }


@tool
def create_draft_release(owner: str, repo: str, tag: str, notes: str, target: str) -> str:
    """Create a draft GitHub Release. The token stays in the environment."""
    if not writes_enabled():
        return json.dumps({"status": "dry_run", "tag": tag, "url": ""})
    if not target:
        raise RuntimeError("draft release needs the candidate sha")
    _reject_secret(notes)
    _reject_secret(tag)
    payload = _request(
        "POST",
        _repo(owner, repo, "/releases"),
        {
            "tag_name": tag,
            "target_commitish": target,
            "name": tag,
            "body": notes,
            "draft": True,
            "prerelease": False,
        },
    )
    return json.dumps(
        {
            "status": "draft",
            "tag": tag,
            "url": str(payload.get("html_url") or ""),
        }
    )
