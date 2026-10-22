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
_AGENT_GIT = {
    "name": "Review Agent",
    "email": "review-agent@users.noreply.github.com",
}
_TITLE_PREFIX = "[Review Agent]"


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
    def read_interface(ref: str) -> str:
        """Return every root .tf file, the README Inputs and Outputs sections, and the changelog top section."""
        return reader.interface(ref)

    @tool
    def search(pattern: str, ref: str) -> str:
        """Search the local copy for a regular expression. Skips examples/."""
        return reader.search(pattern, ref)

    @tool
    def list_release_tags() -> str:
        """List published tags, newest first. A tag is MAJOR.MINOR.PATCH with an optional v and an optional prerelease suffix such as -beta."""
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
        "read_interface": read_interface,
        "search": search,
        "list_release_tags": list_release_tags,
        "compare": compare,
    }


def build_tools(reader: Reader):
    tools = _tool_set(reader)
    return [
        tools["read_interface"],
        tools["compare"],
    ]


def build_version_tools(_reader: Reader):
    """Tags are already on state, and the version step loads the diff, so the model does not call GitHub."""
    return []


def build_recommend_tools(reader: Reader):
    tools = _tool_set(reader)
    return [tools["list_files"], tools["read_file"]]


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


def pull_request_title(title: str, suggested_version: str, filenames: list[str]) -> str:
    """Use the agent's title, unless it is blank or only a status and version."""
    cleaned = " ".join((title or "").split())
    words = cleaned.split()
    if words and words[0].lower() in {"pass", "fail"} and len(words) <= 2:
        cleaned = ""
    if not cleaned:
        if filenames == ["README.md"]:
            document = "the Readme"
        elif filenames == ["CHANGELOG.md"]:
            document = "the Changelog"
        else:
            document = "the Module Docs"
        version = (suggested_version or "").strip() or "the Next Release"
        cleaned = f"Update {document} for {version}"
    if cleaned.startswith(_TITLE_PREFIX):
        return cleaned
    return f"{_TITLE_PREFIX} {cleaned}"


def _commit_as_agent(request, repo: str, token: str, branch: str, parent: str, files: list[dict], message: str) -> None:
    """Write one commit whose author and committer are the review agent."""
    current = request("GET", f"{_API}/repos/{repo}/git/commits/{parent}", token)
    entries = []
    for item in files:
        blob = request(
            "POST",
            f"{_API}/repos/{repo}/git/blobs",
            token,
            {"content": item["content"], "encoding": "utf-8"},
        )
        entries.append(
            {
                "path": item["filename"],
                "mode": "100644",
                "type": "blob",
                "sha": blob["sha"],
            }
        )
    tree = request(
        "POST",
        f"{_API}/repos/{repo}/git/trees",
        token,
        {"base_tree": current["tree"]["sha"], "tree": entries},
    )
    commit = request(
        "POST",
        f"{_API}/repos/{repo}/git/commits",
        token,
        {
            "message": message,
            "tree": tree["sha"],
            "parents": [parent],
            "author": _AGENT_GIT,
            "committer": _AGENT_GIT,
        },
    )
    ref = urllib.parse.quote(f"heads/{branch}", safe="/")
    request("PATCH", f"{_API}/repos/{repo}/git/refs/{ref}", token, {"sha": commit["sha"]})


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
    title: str = "",
    body: str = "",
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
    _commit_as_agent(
        request,
        repo,
        token,
        branch,
        sha,
        files,
        f"Apply review suggestions for {suggested_version}",
    )

    pull = request(
        "POST",
        f"{_API}/repos/{repo}/pulls",
        token,
        {
            "title": pull_request_title(
                title,
                suggested_version,
                [item["filename"] for item in files],
            ),
            "head": branch,
            "base": base,
            "body": body.strip()
            if body and body.strip()
            else _pull_request_body(review_status, suggested_version, findings),
        },
    )
    return pull["html_url"]
