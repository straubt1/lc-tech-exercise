import base64
import json
import os
import secrets
import string
import urllib.error
import urllib.parse
import urllib.request

from langchain.tools import tool

from review.reader import Reader

_API = "https://api.github.com"
_DOC_FILES = {"README.md", "CHANGELOG.md"}
_SUFFIX_ALPHABET = string.ascii_lowercase + string.digits


def _run_suffix() -> str:
    return "".join(secrets.choice(_SUFFIX_ALPHABET) for _ in range(6))


def _tool_set(reader: Reader):
    @tool
    def list_files(ref: str) -> str:
        """List files in the local copy of a git ref, one path per line."""
        return reader.list_files(ref)

    @tool
    def read_file(path: str, ref: str) -> str:
        """Read one file from the local copy of a git ref."""
        return reader.read_file(path, ref)

    @tool
    def search(pattern: str, ref: str) -> str:
        """Search the local copy for a regular expression. Skips examples/."""
        return reader.search(pattern, ref)

    @tool
    def list_release_tags() -> str:
        """List published tags named vMAJOR.MINOR.PATCH, newest first."""
        try:
            return "\n".join(reader.list_release_tags())
        except RuntimeError as exc:
            return str(exc)

    @tool
    def compare(base: str, head: str) -> str:
        """Describe changes between a published tag and the candidate ref."""
        return reader.compare(base, head)

    return {
        "list_files": list_files,
        "read_file": read_file,
        "search": search,
        "list_release_tags": list_release_tags,
        "compare": compare,
    }


def build_tools(reader: Reader):
    tools = _tool_set(reader)
    return [
        tools["list_files"],
        tools["read_file"],
        tools["search"],
        tools["list_release_tags"],
        tools["compare"],
    ]


def build_version_tools(reader: Reader):
    tools = _tool_set(reader)
    return [tools["list_release_tags"], tools["compare"]]


def _request(method: str, url: str, token: str, payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "module-review",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise RuntimeError(f"GitHub {method} {url} failed: {exc.code} {detail}") from exc


def _pull_request_body(review_status: str, suggested_version: str, findings: list[dict]) -> str:
    lines = [
        f"Review status: {review_status}",
        f"Suggested version: {suggested_version}",
        "",
        "Findings:",
    ]
    if not findings:
        lines.append("- none")
    for item in findings:
        lines.append(f"- {item['filename']}: {item['finding']}")
    return "\n".join(lines)


def open_pull_request(
    repo: str,
    base: str,
    suggested_version: str,
    review_status: str,
    findings: list[dict],
    proposed_files: list[dict],
    request=_request,
    suffix=_run_suffix,
) -> str:
    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GH_TOKEN is not set")
    files = [item for item in proposed_files if item.get("filename") in _DOC_FILES]
    if not files:
        return ""

    branch = f"review/{suggested_version}-{suffix()}"
    ref_url = f"{_API}/repos/{repo}/git/ref/heads/{urllib.parse.quote(base, safe='')}"
    sha = request("GET", ref_url, token)["object"]["sha"]
    request(
        "POST",
        f"{_API}/repos/{repo}/git/refs",
        token,
        {"ref": f"refs/heads/{branch}", "sha": sha},
    )
    for item in files:
        path = item["filename"]
        contents_url = (
            f"{_API}/repos/{repo}/contents/{urllib.parse.quote(path, safe='/')}"
            f"?ref={urllib.parse.quote(branch, safe='')}"
        )
        try:
            current = request("GET", contents_url, token)
            current_sha = current.get("sha")
        except RuntimeError as exc:
            if "failed: 404" not in str(exc):
                raise
            current_sha = None
        body = {
            "message": f"Apply review suggestions for {suggested_version}",
            "content": base64.b64encode(item["content"].encode()).decode(),
            "branch": branch,
        }
        if current_sha:
            body["sha"] = current_sha
        request("PUT", f"{_API}/repos/{repo}/contents/{urllib.parse.quote(path, safe='/')}", token, body)

    pull = request(
        "POST",
        f"{_API}/repos/{repo}/pulls",
        token,
        {
            "title": f"{review_status} {suggested_version}",
            "head": branch,
            "base": base,
            "body": _pull_request_body(review_status, suggested_version, findings),
        },
    )
    return pull["html_url"]
