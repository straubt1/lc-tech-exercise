import io
import tarfile
import threading
import urllib.error
from pathlib import Path

from langchain_core.messages import ToolMessage

from review.reader import FixtureReader, GithubReader
from review.tools.github import (
    _run_suffix,
    build_listing_tools,
    build_recommend_tools,
    open_pull_request,
    pull_request_title,
)


def _http_error(code):
    return urllib.error.HTTPError("https://api.github.com", code, "error", None, io.BytesIO(b""))


def test_release_tags_are_one_request_and_keep_full_semver():
    calls = []
    pages = {
        "https://api.github.com/repos/acme/mod/tags?per_page=100": (
            [
                {"name": "v1.2"},
                {"name": "v1.2.3-rc1"},
                {"name": "v1.0.0"},
                {"name": "0.9.0-beta"},
                {"name": "v1.2.0"},
                {"name": "latest"},
                {"name": "1.1.0"},
                {"name": "1.2.0-beta"},
            ],
            "https://api.github.com/page-2",
        ),
    }

    def fetch(url):
        calls.append(url)
        return pages[url]

    reader = GithubReader("acme/mod", fetch=fetch)
    tags = reader.list_release_tags()
    assert calls == ["https://api.github.com/repos/acme/mod/tags?per_page=100"]
    assert tags == ["v1.2.3-rc1", "v1.2.0", "1.2.0-beta", "1.1.0", "v1.0.0", "0.9.0-beta"]
    assert reader.list_release_tags() == tags
    assert calls == ["https://api.github.com/repos/acme/mod/tags?per_page=100"]


def _archive(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name=f"mod-sha/{path}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_copy_repo_downloads_once_and_checkout_writes_that_copy():
    calls = []
    blob = _archive(
        {
            "locals.tf": 'variable "bucket_name" {}\n',
            "notes.md": 'output "bucket_arn" {}\n',
            "examples/demo.tf": 'variable "hidden" {}\n',
            "README.md": "hello\n",
        }
    )

    def download(url):
        calls.append(url)
        return blob

    reader = GithubReader("acme/mod", download=download)
    listing = reader.copy_repo("latest")
    assert calls == ["https://api.github.com/repos/acme/mod/tarball/latest"]
    assert "locals.tf" in listing
    assert reader.read_file("README.md", "latest") == "hello\n"
    assert reader.read_file("missing.tf", "latest") == "not found: missing.tf@latest"
    assert reader.copy_repo("latest") == listing
    assert calls == ["https://api.github.com/repos/acme/mod/tarball/latest"]
    path = reader.checkout("latest")
    assert Path(path, "locals.tf").read_text() == 'variable "bucket_name" {}\n'
    assert Path(path, "examples/demo.tf").is_file()
    assert reader.checkout("latest") == path
    assert calls == ["https://api.github.com/repos/acme/mod/tarball/latest"]


def test_copy_repo_downloads_once_when_two_callers_race():
    calls = []
    started = threading.Barrier(2)
    blob = _archive({"README.md": "hello\n"})

    def download(url):
        calls.append(url)
        return blob

    reader = GithubReader("acme/mod", download=download)

    def copy():
        started.wait()
        reader.copy_repo("latest")

    threads = [threading.Thread(target=copy), threading.Thread(target=copy)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert calls == ["https://api.github.com/repos/acme/mod/tarball/latest"]
    assert reader.read_file("README.md", "latest") == "hello\n"


def test_fetch_sends_the_token_from_the_environment(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "secret-token")
    seen = {}

    class _Response:
        headers = {}

        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def urlopen(request, timeout=30):
        seen["authorization"] = request.get_header("Authorization")
        return _Response()

    monkeypatch.setattr("review.reader.urllib.request.urlopen", urlopen)
    from review.reader import _fetch

    _fetch("https://api.github.com/repos/acme/mod/tags")
    assert seen["authorization"] == "Bearer secret-token"


def test_fetch_omits_authorization_when_the_token_is_unset(monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    seen = {}

    class _Response:
        headers = {}

        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def urlopen(request, timeout=30):
        seen["authorization"] = request.get_header("Authorization")
        return _Response()

    monkeypatch.setattr("review.reader.urllib.request.urlopen", urlopen)
    from review.reader import _fetch

    _fetch("https://api.github.com/repos/acme/mod/tags")
    assert seen["authorization"] is None


def test_check_confirms_the_ref_without_downloading_the_repo():
    def fetch(url):
        assert url == "https://api.github.com/repos/acme/mod/commits/latest"
        return {"sha": "abc"}, None

    def download(url):
        raise AssertionError(url)

    reader = GithubReader("acme/mod", fetch=fetch, download=download)
    assert reader.check("acme/mod", "latest") == ""


def test_check_reports_a_missing_ref_without_downloading_the_repo():
    def fetch(url):
        raise _http_error(422 if url.endswith("/latest-renames") else 404)

    def download(url):
        raise AssertionError(url)

    reader = GithubReader("acme/mod", fetch=fetch, download=download)
    assert reader.check("acme/mod", "missing") == "not found: acme/mod@missing"
    assert reader.check("acme/mod", "latest-renames") == "not found: acme/mod@latest-renames"
    assert reader.check("", "latest") == "repo is required"
    assert reader.check("acme/mod", "") == "ref is required"


def test_a_missing_ref_is_reported_without_a_second_download():
    calls = []

    def download(url):
        calls.append(url)
        raise _http_error(404)

    reader = GithubReader("acme/mod", download=download)
    assert reader.read_file("README.md", "missing") == "not found: acme/mod@missing"
    assert reader.checkout("missing") == "not found: acme/mod@missing"
    assert len(calls) == 1


def test_read_file_reports_a_rate_limit():
    calls = []

    def download(url):
        calls.append(url)
        raise _http_error(403)

    reader = GithubReader("acme/mod", download=download)
    text = reader.read_file("README.md", "latest")
    assert text.startswith("github error 403")
    assert reader.list_files("latest") == text
    assert len(calls) == 1


def test_compare_trace_records_the_get_and_redacts_the_token(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "secret-token")
    from review.reader import _compare_trace_inputs

    traced = _compare_trace_inputs(
        {"url": "https://api.github.com/repos/acme/mod/compare/v1.0.0...latest"}
    )
    assert traced["method"] == "GET"
    assert traced["url"].endswith("/compare/v1.0.0...latest")
    assert traced["headers"]["Authorization"] == "Bearer <redacted>"
    assert "secret-token" not in str(traced)


def test_compare_lists_files_and_patches():
    calls = []

    def fetch(url):
        calls.append(url)
        assert url.endswith("/compare/v1.0.0...latest")
        return {
            "status": "ahead",
            "ahead_by": 1,
            "files": [
                {
                    "filename": "variables.tf",
                    "status": "modified",
                    "patch": "+variable \"force_destroy\" {}",
                }
            ],
        }, None

    reader = GithubReader("acme/mod", fetch=fetch)
    text = reader.compare("v1.0.0", "latest")
    assert "variables.tf (modified)" in text
    assert "+variable" in text
    assert reader.compare("v1.0.0", "latest") == text
    assert len(calls) == 1


def test_a_blank_title_becomes_a_title_and_a_blank_body_lists_findings(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "secret-token")
    assert pull_request_title("fail v1.2.0", "v1.2.0", ["CHANGELOG.md"]) == (
        "[Review Agent] Update the Changelog for v1.2.0"
    )
    assert pull_request_title(
        "Document the Bucket Rename for v1.0.2",
        "v1.0.2",
        ["CHANGELOG.md"],
    ) == "[Review Agent] Document the Bucket Rename for v1.0.2"

    def request(method, url, token, payload=None):
        if method == "GET" and "/git/commits/" in url:
            return {"tree": {"sha": "tree123"}}
        if method == "GET" and "/git/ref/" in url:
            return {"object": {"sha": "abc123"}}
        if method == "POST" and url.endswith("/git/blobs"):
            return {"sha": "blob"}
        if method == "POST" and url.endswith("/git/trees"):
            return {"sha": "tree-new"}
        if method == "POST" and url.endswith("/git/commits"):
            request.commit = payload
            return {"sha": "commit-new"}
        if method == "POST" and url.endswith("/pulls"):
            request.pull = payload
            return {"html_url": "https://github.com/acme/mod/pull/8"}
        return {}

    request.pull = None
    request.commit = None
    open_pull_request(
        repo="acme/mod",
        base="latest",
        suggested_version="v1.2.0",
        status="Interface: fail",
        findings=[{"filename": "README.md", "finding": "missing variable"}],
        proposed_files=[{"filename": "README.md", "content": "# Readme\n"}],
        request=request,
        suffix=lambda: "a1b2c3",
    )
    assert request.pull["title"] == "[Review Agent] Update the Readme for v1.2.0"
    assert request.commit["author"]["name"] == "Review Agent"
    assert request.commit["committer"] == request.commit["author"]
    assert "Interface: fail" in request.pull["body"]
    assert "Suggested version: v1.2.0" in request.pull["body"]
    assert "README.md: missing variable" in request.pull["body"]


def test_run_suffix_is_six_alphanumeric_characters():
    first = _run_suffix()
    second = _run_suffix()
    assert len(first) == 6
    assert first.isalnum()
    assert first != second


def test_open_pull_request_commits_docs_and_uses_the_token_from_the_environment(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "secret-token")
    calls = []

    def request(method, url, token, payload=None):
        calls.append((method, url, token, payload))
        if method == "GET" and "/git/commits/" in url:
            return {"tree": {"sha": "tree123"}}
        if method == "GET" and "/git/ref/" in url:
            return {"object": {"sha": "abc123"}}
        if method == "POST" and url.endswith("/git/blobs"):
            return {"sha": "blob-" + str(len(calls))}
        if method == "POST" and url.endswith("/git/trees"):
            return {"sha": "tree-new"}
        if method == "POST" and url.endswith("/git/commits"):
            return {"sha": "commit-new"}
        if method == "POST" and url.endswith("/pulls"):
            return {"html_url": "https://github.com/acme/mod/pull/7"}
        return {}

    url = open_pull_request(
        repo="acme/mod",
        base="latest",
        suggested_version="v1.2.0",
        status="Interface: fail",
        findings=[{"filename": "README.md", "finding": "missing variable"}],
        proposed_files=[
            {"filename": "README.md", "content": "# Readme\n"},
            {"filename": "CHANGELOG.md", "content": "# Changelog\n"},
            {"filename": "main.tf", "content": "nope\n"},
        ],
        title="Document the Missing Variable for v1.2.0",
        body="## Summary\nThe readme omits a variable.\n",
        request=request,
        suffix=lambda: "a1b2c3",
    )

    assert url == "https://github.com/acme/mod/pull/7"
    assert {token for _method, _url, token, _payload in calls} == {"secret-token"}
    methods = [(method, url) for method, url, _token, _payload in calls]
    assert methods[0][0] == "GET"
    assert methods[1] == ("POST", "https://api.github.com/repos/acme/mod/git/refs")
    assert calls[1][3] == {"ref": "refs/heads/review/v1.2.0-a1b2c3", "sha": "abc123"}
    assert not any("/contents/" in url for _method, url, _token, _payload in calls)
    blobs = [
        payload["content"]
        for method, url, _token, payload in calls
        if method == "POST" and url.endswith("/git/blobs")
    ]
    assert blobs == ["# Readme\n", "# Changelog\n", "nope\n"]
    tree = next(
        payload
        for method, url, _token, payload in calls
        if method == "POST" and url.endswith("/git/trees")
    )
    assert [item["path"] for item in tree["tree"]] == ["README.md", "CHANGELOG.md", "main.tf"]
    commit = next(
        payload
        for method, url, _token, payload in calls
        if method == "POST" and url.endswith("/git/commits")
    )
    assert commit["author"] == {
        "name": "Review Agent",
        "email": "review-agent@users.noreply.github.com",
    }
    assert commit["committer"] == commit["author"]
    assert commit["parents"] == ["abc123"]
    pull = calls[-1][3]
    assert pull["title"] == "[Review Agent] Document the Missing Variable for v1.2.0"
    assert pull["body"] == "## Summary\nThe readme omits a variable."
    assert pull["head"] == "review/v1.2.0-a1b2c3"
    assert pull["base"] == "latest"


def test_read_pr_template_returns_the_first_existing_file_and_read_file_stays_on_the_list():
    reader = FixtureReader(
        files={
            ("latest", "docs/PULL_REQUEST_TEMPLATE.md"): "# Template\n",
            ("latest", "main.tf"): "resource {}\n",
        }
    )
    allowed = {"files": {"main.tf"}}
    tools = {tool.name: tool for tool in build_recommend_tools(reader, allowed)}
    text = tools["read_pr_template"].invoke(
        {
            "paths": [".github/PULL_REQUEST_TEMPLATE.md", "docs/PULL_REQUEST_TEMPLATE.md"],
            "ref": "latest",
        }
    )
    assert text.startswith("docs/PULL_REQUEST_TEMPLATE.md")
    assert "# Template" in text
    assert tools["read_pr_template"].invoke({"paths": ["missing.md"], "ref": "latest"}) == ""
    assert tools["read_file"].invoke({"path": "main.tf", "ref": "latest"}) == "resource {}\n"
    assert tools["read_file"].invoke({"path": "README.md", "ref": "latest"}) == "not in this run"
    allowed["files"] = set()
    assert tools["read_file"].invoke({"path": "main.tf", "ref": "latest"}) == "not in this run"


def _tool_call(tool, args):
    return tool.invoke({"type": "tool_call", "id": "call-1", "name": tool.name, "args": args})


def test_list_tools_return_arrays_and_keep_errors():
    reader = FixtureReader(
        files={
            ("latest", "README.md"): "hello\n",
            ("latest", "main.tf"): 'variable "name" {}\n',
            ("latest", "examples/demo.tf"): 'variable "hidden" {}\n',
        },
        tags=["v1.2.0", "v1.0.0"],
    )
    tools = {tool.name: tool for tool in build_listing_tools(reader)}
    assert reader.list_files("latest") == "README.md\nexamples/demo.tf\nmain.tf"

    listed = _tool_call(tools["list_files"], {"ref": "latest"})
    assert isinstance(listed, ToolMessage)
    assert listed.content == ["README.md", "examples/demo.tf", "main.tf"]

    found = _tool_call(tools["search"], {"pattern": "variable", "ref": "latest"})
    assert found.content == ['main.tf:1: variable "name" {}']
    assert _tool_call(tools["search"], {"pattern": "missing", "ref": "latest"}).content == []
    invalid = _tool_call(tools["search"], {"pattern": "(", "ref": "latest"})
    assert isinstance(invalid.content, str)
    assert invalid.content.startswith("invalid pattern:")

    tags = _tool_call(tools["list_release_tags"], {})
    assert tags.content == ["v1.2.0", "v1.0.0"]

    empty = {tool.name: tool for tool in build_listing_tools(FixtureReader())}
    assert _tool_call(empty["list_files"], {"ref": "latest"}).content == []
    assert _tool_call(empty["search"], {"pattern": "variable", "ref": "latest"}).content == []
    assert _tool_call(empty["list_release_tags"], {}).content == []

    def fail(url):
        raise _http_error(404)

    broken_reader = GithubReader("acme/mod", download=fail, fetch=fail)
    broken = {tool.name: tool for tool in build_listing_tools(broken_reader)}
    missing = _tool_call(broken["list_files"], {"ref": "missing"})
    assert missing.content == "not found: acme/mod@missing"
    assert _tool_call(broken["search"], {"pattern": "variable", "ref": "missing"}).content == missing.content
    denied = _tool_call(broken["list_release_tags"], {})
    assert isinstance(denied.content, str)
    assert denied.content.startswith("github error 404")

    huge = FixtureReader(files={("latest", "main.tf"): "y" * 48001 + "\n"})
    clipped = _tool_call(
        {tool.name: tool for tool in build_listing_tools(huge)}["search"],
        {"pattern": "y", "ref": "latest"},
    )
    assert clipped.content[-1] == "...truncated"
