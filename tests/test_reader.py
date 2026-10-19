import base64
import io
import json
import tarfile
import threading
import urllib.error

from review.reader import GithubReader
from review.tools.github import _run_suffix, open_pull_request


def _http_error(code):
    return urllib.error.HTTPError("https://api.github.com", code, "error", None, io.BytesIO(b""))


def test_release_tags_keep_only_full_semver_and_follow_pages():
    pages = {
        "https://api.github.com/repos/acme/mod/tags?per_page=100": (
            [{"name": "v1.2"}, {"name": "v1.2.3-rc1"}, {"name": "v1.0.0"}],
            "https://api.github.com/page-2",
        ),
        "https://api.github.com/page-2": ([{"name": "v1.2.0"}, {"name": "latest"}], None),
    }

    def fetch(url):
        return pages[url]

    tags = GithubReader("acme/mod", fetch=fetch).list_release_tags()
    assert tags == ["v1.2.0", "v1.0.0"]


def _archive(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name=f"mod-sha/{path}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_copy_repo_downloads_once_and_search_finds_blocks_in_any_filename():
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
    found = reader.search(r'(variable|output)\s+"', "latest")
    assert 'locals.tf:1: variable "bucket_name" {}' in found
    assert 'notes.md:1: output "bucket_arn" {}' in found
    assert "hidden" not in found


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


def test_a_missing_ref_is_unavailable():
    def download(url):
        raise _http_error(404)

    reader = GithubReader("acme/mod", download=download)
    assert reader.unavailable("missing") == "not found: acme/mod@missing"
    assert reader.read_file("README.md", "missing") == "not found: acme/mod@missing"


def test_read_file_reports_a_rate_limit():
    calls = []

    def download(url):
        calls.append(url)
        raise _http_error(403)

    reader = GithubReader("acme/mod", download=download)
    text = reader.read_file("README.md", "latest")
    assert text.startswith("github error 403")
    assert reader.unavailable("latest") == ""
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
    def fetch(url):
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

    text = GithubReader("acme/mod", fetch=fetch).compare("v1.0.0", "latest")
    assert "variables.tf (modified)" in text
    assert "+variable" in text


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
        if method == "GET" and "/git/ref/" in url:
            return {"object": {"sha": "abc123"}}
        if method == "GET" and "/contents/" in url:
            return {"sha": "file-sha"}
        if method == "PUT":
            return {"content": {"path": url}}
        if method == "POST" and url.endswith("/pulls"):
            return {"html_url": "https://github.com/acme/mod/pull/7"}
        return {}

    url = open_pull_request(
        repo="acme/mod",
        base="latest",
        suggested_version="v1.2.0",
        review_status="fail",
        findings=[{"filename": "README.md", "finding": "missing variable"}],
        proposed_files=[
            {"filename": "README.md", "content": "# Readme\n"},
            {"filename": "CHANGELOG.md", "content": "# Changelog\n"},
            {"filename": "main.tf", "content": "nope\n"},
        ],
        request=request,
        suffix=lambda: "a1b2c3",
    )

    assert url == "https://github.com/acme/mod/pull/7"
    assert {token for _method, _url, token, _payload in calls} == {"secret-token"}
    methods = [(method, url) for method, url, _token, _payload in calls]
    assert methods[0][0] == "GET"
    assert methods[1] == ("POST", "https://api.github.com/repos/acme/mod/git/refs")
    assert calls[1][3] == {"ref": "refs/heads/review/v1.2.0-a1b2c3", "sha": "abc123"}
    put_paths = [url for method, url, _token, _payload in calls if method == "PUT"]
    assert put_paths == [
        "https://api.github.com/repos/acme/mod/contents/README.md",
        "https://api.github.com/repos/acme/mod/contents/CHANGELOG.md",
    ]
    pull = calls[-1][3]
    assert pull["title"] == "fail v1.2.0"
    assert pull["head"] == "review/v1.2.0-a1b2c3"
    assert pull["base"] == "latest"
    assert "Review status: fail" in pull["body"]
    assert "Suggested version: v1.2.0" in pull["body"]
    assert "README.md: missing variable" in pull["body"]
    encoded = base64.b64encode(b"# Readme\n").decode()
    assert calls[3][3]["content"] == encoded
    assert json.loads(json.dumps(calls[3][3]))["branch"] == "review/v1.2.0-a1b2c3"
