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
_SUFFIX_ALPHABET = string.ascii_lowercase + string.digits
_AGENT_GIT = {
    "name": "Review Agent",
    "email": "review-agent@users.noreply.github.com",
}
_TITLE_PREFIX = "[Review Agent]"


def _run_suffix() -> str:
    return "".join(secrets.choice(_SUFFIX_ALPHABET) for _ in range(6))


def _as_list(text: str) -> list[str] | str:
    """Turn a newline-joined list into paths or match lines. Leave errors as text."""
    if text.startswith(("not found:", "github error", "invalid pattern:")):
        return text
    if text in {"", "no files", "no matches"}:
        return []
    return text.splitlines()


def build_listing_tools(reader: Reader):
    @tool
    def list_files(ref: str) -> list[str] | str:
        """List file paths in the local copy of a git ref.

        A successful result is a JSON array of paths.
        """
        return _as_list(reader.list_files(ref))

    @tool
    def search(pattern: str, ref: str) -> list[str] | str:
        """Search the local copy for a regular expression. Skips examples/.

        A successful result is a JSON array of path:line: text matches.
        """
        return _as_list(reader.search(pattern, ref))

    @tool
    def list_release_tags() -> list[str] | str:
        """List published tags, newest first.

        A successful result is a JSON array of tags. A tag is MAJOR.MINOR.PATCH
        with an optional v and an optional prerelease suffix.
        """
        try:
            return list(reader.list_release_tags())
        except RuntimeError as exc:
            return str(exc)

    return [list_files, search, list_release_tags]


def build_recommend_tools(reader: Reader, allowed: dict | None = None):
    scope = allowed if allowed is not None else {"files": set()}

    @tool
    def read_pr_template(paths: list[str], ref: str) -> str:
        """Read the first existing pull request template from an ordered list of paths.

        Returns that path and its text. Returns empty when none of the paths exist.
        """
        names = paths if isinstance(paths, list) else [paths]
        for path in names:
            text = reader.read_file(str(path), ref)
            if text.startswith("not found:"):
                continue
            return f"{path}\n{text}"
        return ""

    @tool
    def read_file(path: str, ref: str) -> str:
        """Read one file named by a finding. Refuses any other path."""
        if path not in scope["files"]:
            return "not in this run"
        return reader.read_file(path, ref)

    return [read_pr_template, read_file]


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


def _pull_request_body(status: str, suggested_version: str, findings: list[dict]) -> str:
    lines = [
        status,
        f"Suggested version: {suggested_version}",
        "",
        "Findings:",
    ]
    if not findings:
        lines.append("- none")
    for item in findings:
        lines.append(f"- {item['filename']}: {item['finding']}")
    return "\n".join(lines)


def _committable(path: str) -> bool:
    path = (path or "").strip()
    if not path or path.startswith("/") or path.startswith("\\"):
        return False
    return all(part not in {"", ".", ".."} for part in path.split("/"))


def open_pull_request(
    repo: str,
    base: str,
    suggested_version: str,
    status: str,
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
    files = [item for item in proposed_files if _committable(item.get("filename") or "")]
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
            else _pull_request_body(status, suggested_version, findings),
        },
    )
    return pull["html_url"]
