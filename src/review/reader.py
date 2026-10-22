import io
import json
import os
import re
import tarfile
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from langsmith import traceable

_RELEASE_TAG = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_API = "https://api.github.com"


def _semver(tag: str) -> tuple:
    match = _RELEASE_TAG.fullmatch(tag)
    major = int(match.group("major"))
    minor = int(match.group("minor"))
    patch = int(match.group("patch"))
    pre = match.group("pre")
    if not pre:
        return (major, minor, patch, 1)
    parts = []
    for item in pre.split("."):
        if item.isdigit():
            parts.append((0, int(item)))
        else:
            parts.append((1, item))
    return (major, minor, patch, 0, tuple(parts))


def _next_link(headers) -> str | None:
    link = headers.get("Link") if headers else None
    if not link:
        return None
    for part in link.split(","):
        if 'rel="next"' in part:
            return part[part.find("<") + 1 : part.find(">")]
    return None


def _github_error(exc: urllib.error.HTTPError) -> str:
    detail = exc.read().decode(errors="replace")[:300]
    return f"github error {exc.code}: {detail}"


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "module-review",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GH_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _compare_trace_inputs(inputs: dict) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "module-review",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if os.environ.get("GH_TOKEN", "").strip():
        headers["Authorization"] = "Bearer <redacted>"
    return {"method": "GET", "url": inputs["url"], "headers": headers}


def _compare_trace_outputs(outputs) -> dict:
    payload = outputs[0] if isinstance(outputs, (tuple, list)) and outputs else outputs
    if not isinstance(payload, dict):
        return {}
    return {
        "status": payload.get("status"),
        "ahead_by": payload.get("ahead_by"),
        "files": [item.get("filename") for item in payload.get("files") or []],
    }


@traceable(
    name="github_compare",
    run_type="tool",
    process_inputs=_compare_trace_inputs,
    process_outputs=_compare_trace_outputs,
)
def _github_compare(url: str, fetch):
    return fetch(url)


def _fetch(url: str):
    request = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode())
        return payload, _next_link(response.headers)


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _relative(path: str) -> str | None:
    path = path.strip().lstrip("./")
    if not path or path.startswith("/") or path.startswith("\\"):
        return None
    parts = path.split("/")
    if any(part in {"", ".."} for part in parts):
        return None
    return path


def _write_tree(files: dict[str, str]) -> str:
    root = Path(tempfile.mkdtemp(prefix="module-review-"))
    for name, text in files.items():
        safe = _relative(name)
        if safe is None:
            continue
        dest = root / safe
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
    return str(root)


def _listing(files: dict[str, str]) -> str:
    names = sorted(files)
    return "\n".join(names) if names else "no files"


def _search_files(files: dict[str, str], pattern: str) -> str:
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return f"invalid pattern: {exc}"
    lines = []
    for path in sorted(files):
        if path == "examples" or path.startswith("examples/"):
            continue
        for number, line in enumerate(files[path].splitlines(), 1):
            if compiled.search(line):
                lines.append(f"{path}:{number}: {line}")
    if not lines:
        return "no matches"
    text = "\n".join(lines)
    if len(text) > 48000:
        text = text[:48000] + "\n...truncated"
    return text


def _untar(blob: bytes) -> dict[str, str]:
    files: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
        chosen = []
        for member in archive.getmembers():
            if not member.isfile():
                continue
            name = member.name.lstrip("./")
            if not name or name.startswith("/") or ".." in name.split("/"):
                continue
            chosen.append((member, name))
        prefixes = {name.split("/", 1)[0] for _, name in chosen if "/" in name}
        strip = len(prefixes) == 1 and all("/" in name for _, name in chosen)
        for member, name in chosen:
            rel = name.split("/", 1)[1] if strip else name
            if _relative(rel) is None:
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            files[rel] = extracted.read().decode(errors="replace")
    return files


class _Copy:
    def __init__(self, files: dict[str, str], error: str = "", status: int = 0) -> None:
        self.files = files
        self.error = error
        self.status = status
        self.dir = ""


def _required(repo: str, ref: str) -> str:
    repo = (repo or "").strip()
    ref = (ref or "").strip()
    if not repo:
        return "repo is required"
    if repo.count("/") != 1 or repo.startswith("/") or repo.endswith("/"):
        return "repo must be owner/name"
    if not ref:
        return "ref is required"
    return ""


class Reader:
    """Reads a module. GithubReader copies one git ref, then reads that copy."""

    def check(self, repo: str, ref: str) -> str:
        return _required(repo, ref)

    def copy_repo(self, ref: str) -> str:
        return ""

    def list_files(self, ref: str) -> str:
        return ""

    def read_file(self, path: str, ref: str) -> str:
        return ""

    def search(self, pattern: str, ref: str) -> str:
        return ""

    def checkout(self, ref: str) -> str:
        return ""

    def list_release_tags(self) -> list[str]:
        return []

    def compare(self, base: str, head: str) -> str:
        return ""


class FixtureReader(Reader):
    def __init__(
        self,
        files: dict[tuple[str, str], str] | None = None,
        tags: list[str] | None = None,
        compares: dict[tuple[str, str], str] | None = None,
    ) -> None:
        self._files = files or {}
        self._tags = list(tags or [])
        self._compares = compares or {}
        self._dirs: dict[str, str] = {}
        self._lock = threading.Lock()

    def _at(self, ref: str) -> dict[str, str]:
        return {path: text for (file_ref, path), text in self._files.items() if file_ref == ref}

    def copy_repo(self, ref: str) -> str:
        return _listing(self._at(ref))

    def list_files(self, ref: str) -> str:
        return self.copy_repo(ref)

    def read_file(self, path: str, ref: str) -> str:
        return self._files.get((ref, path), f"not found: {path}@{ref}")

    def search(self, pattern: str, ref: str) -> str:
        return _search_files(self._at(ref), pattern)

    def checkout(self, ref: str) -> str:
        with self._lock:
            cached = self._dirs.get(ref)
            if cached:
                return cached
            path = _write_tree(self._at(ref))
            self._dirs[ref] = path
            return path

    def list_release_tags(self) -> list[str]:
        return list(self._tags)

    def compare(self, base: str, head: str) -> str:
        return self._compares.get((base, head), "no changes")


class GithubReader(Reader):
    def __init__(self, repo: str, fetch=_fetch, download=_download) -> None:
        self.repo = repo
        self._fetch = fetch
        self._download = download
        self._copies: dict[str, _Copy] = {}
        self._release_tags: list[str] | None = None
        self._compared: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def check(self, repo: str, ref: str) -> str:
        message = _required(repo, ref)
        if message:
            return message
        repo = repo.strip()
        ref = ref.strip()
        url = f"{_API}/repos/{repo}/commits/{urllib.parse.quote(ref, safe='')}"
        try:
            self._fetch(url)
        except urllib.error.HTTPError as exc:
            if exc.code in {404, 422}:
                return f"not found: {repo}@{ref}"
            return _github_error(exc)
        return ""

    def copy_repo(self, ref: str) -> str:
        with self._lock:
            cached = self._copies.get(ref)
            if cached is None:
                url = f"{_API}/repos/{self.repo}/tarball/{urllib.parse.quote(ref, safe='')}"
                try:
                    blob = self._download(url)
                    cached = _Copy(_untar(blob))
                except urllib.error.HTTPError as exc:
                    if exc.code == 404:
                        cached = _Copy({}, f"not found: {self.repo}@{ref}", exc.code)
                    else:
                        cached = _Copy({}, _github_error(exc), exc.code)
                except tarfile.TarError as exc:
                    cached = _Copy({}, f"github error: archive {exc}")
                self._copies[ref] = cached
        if cached.error:
            return cached.error
        return _listing(cached.files)

    def list_files(self, ref: str) -> str:
        return self.copy_repo(ref)

    def read_file(self, path: str, ref: str) -> str:
        message = self.copy_repo(ref)
        cached = self._copies[ref]
        if cached.error:
            return message
        safe = _relative(path)
        if safe is None or safe not in cached.files:
            return f"not found: {path}@{ref}"
        return cached.files[safe]

    def search(self, pattern: str, ref: str) -> str:
        message = self.copy_repo(ref)
        cached = self._copies[ref]
        if cached.error:
            return message
        return _search_files(cached.files, pattern)

    def checkout(self, ref: str) -> str:
        message = self.copy_repo(ref)
        with self._lock:
            cached = self._copies[ref]
            if cached.error:
                return message
            if not cached.dir:
                cached.dir = _write_tree(cached.files)
            return cached.dir

    def list_release_tags(self) -> list[str]:
        """One tags request. Keeps vX.Y.Z, X.Y.Z, and vX.Y.Z-suffix, newest first."""
        with self._lock:
            if self._release_tags is not None:
                return list(self._release_tags)
            url = f"{_API}/repos/{self.repo}/tags?per_page=100"
            try:
                payload, _next = self._fetch(url)
            except urllib.error.HTTPError as exc:
                raise RuntimeError(_github_error(exc)) from exc
            tags = [
                item.get("name", "")
                for item in payload
                if _RELEASE_TAG.fullmatch(item.get("name", ""))
            ]
            self._release_tags = sorted(tags, key=_semver, reverse=True)
            return list(self._release_tags)

    def compare(self, base: str, head: str) -> str:
        key = (base, head)
        with self._lock:
            cached = self._compared.get(key)
            if cached is not None:
                return cached
            text = self._compare(base, head)
            self._compared[key] = text
            return text

    def _compare(self, base: str, head: str) -> str:
        base_quoted = urllib.parse.quote(base, safe="")
        head_quoted = urllib.parse.quote(head, safe="")
        url = f"{_API}/repos/{self.repo}/compare/{base_quoted}...{head_quoted}"
        try:
            payload, _next = _github_compare(url, self._fetch)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return f"no changes\ncompare not found: {base}...{head}"
            return _github_error(exc)
        lines = [
            f"status: {payload.get('status', '')}",
            f"ahead_by: {payload.get('ahead_by', 0)}",
            "files:",
        ]
        patches = []
        for item in payload.get("files") or []:
            filename = item.get("filename", "")
            lines.append(f"- {filename} ({item.get('status', '')})")
            patch = item.get("patch")
            if patch:
                patches.append(f"--- {filename}\n{patch}")
        text = "\n".join(lines)
        if patches:
            text = text + "\n\n" + "\n\n".join(patches)
        if payload.get("ahead_by", 0) == 0 and not patches:
            text = text + "\nno changes"
        if len(text) > 48000:
            text = text[:48000] + "\n...truncated"
        return text
