import base64
import json
import urllib.request

import pytest

from release.agents.diff import DiffReport, diff_node
from release.tools.github_read import (
    diff_refs,
    files_from_snapshots,
    github_get,
    published_tags,
)


def test_published_tags_keep_semver_and_sort_highest_first():
    tags = published_tags(
        [
            {"name": "v1.2", "commit": {"sha": "a"}},
            {"name": "v1.0.0-rc1", "commit": {"sha": "b"}},
            {"name": "v1.0.0", "commit": {"sha": "c" * 40}},
            {"name": "v1.0.1", "commit": {"sha": "d" * 40}},
            {"name": "latest", "commit": {"sha": "e"}},
        ]
    )
    assert [item["name"] for item in tags] == ["v1.0.1", "v1.0.0"]


def test_files_from_snapshots_diffs_locally_and_skips_identical_blobs():
    reads = []

    def read_base(path):
        reads.append(("base", path))
        return "old\n"

    def read_head(path):
        reads.append(("head", path))
        return "new\n" if path == "main.tf" else "added\n"

    files = files_from_snapshots(
        {"main.tf": "same", "variables.tf": "blob-a", "gone.tf": "blob-b"},
        {"main.tf": "same", "variables.tf": "blob-c", "added.tf": "blob-d"},
        read_base,
        read_head,
    )
    by_path = {item["path"]: item for item in files}
    assert "main.tf" not in by_path
    assert by_path["variables.tf"]["status"] == "modified"
    assert "-old" in by_path["variables.tf"]["patch"]
    assert "+added" in by_path["variables.tf"]["patch"]
    assert by_path["added.tf"]["status"] == "added"
    assert by_path["gone.tf"]["status"] == "removed"
    assert ("base", "main.tf") not in reads
    assert ("head", "main.tf") not in reads


def test_diff_refs_downloads_contents_and_does_not_call_compare(monkeypatch):
    paths = []

    def fake_github_get(path):
        paths.append(path)
        assert "/compare/" not in path
        if path.endswith("/commits/v1.0.1"):
            return {"sha": "b" * 40}
        if path.endswith("/commits/latest"):
            return {"sha": "a" * 40}
        if "/git/trees/" in path:
            sha = path.split("/git/trees/")[1].split("?")[0]
            blob = "old" if sha.startswith("b") else "new"
            return {"truncated": False, "tree": [{"path": "main.tf", "type": "blob", "sha": blob}]}
        if "/contents/main.tf" in path and "ref=v1.0.1" in path:
            return {"encoding": "base64", "size": 4, "content": base64.b64encode(b"old\n").decode()}
        if "/contents/main.tf" in path and "ref=latest" in path:
            return {"encoding": "base64", "size": 4, "content": base64.b64encode(b"new\n").decode()}
        raise AssertionError(path)

    monkeypatch.setattr("release.tools.github_read.github_get", fake_github_get)
    report = diff_refs("octo", "mod", "v1.0.1", "latest")
    assert report["candidate_sha"] == "a" * 40
    assert report["files"][0]["path"] == "main.tf"
    assert report["files"][0]["status"] == "modified"
    assert any("/contents/main.tf" in path for path in paths)


def test_github_get_does_not_send_a_token(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "super-secret-token")
    captured = {}

    class Response:
        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=30):
        captured["headers"] = {key.lower(): value for key, value in request.header_items()}
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert github_get("/repos/octo/mod/tags?per_page=100&page=1") == {}
    header_text = json.dumps(captured["headers"])
    assert "authorization" not in captured["headers"]
    assert "super-secret-token" not in header_text


def test_diff_node_rejects_a_version_bump_as_the_category(monkeypatch):
    class Agent:
        def invoke(self, _payload):
            return {
                "structured_response": DiffReport(
                    base_ref="v1.0.1",
                    candidate_sha="a" * 40,
                    changed_paths=["main.tf"],
                    diff_summary="Changed the bucket name.",
                    change_category="patch",
                )
            }

    monkeypatch.setattr("release.agents.diff.resolve_model", lambda: object())
    monkeypatch.setattr("release.agents.diff.build_diff_agent", lambda *args, **kwargs: Agent())
    with pytest.raises(RuntimeError, match="version bump"):
        diff_node({"repo": "octo/mod", "candidate_ref": "latest"})


def test_diff_node_records_the_local_report(monkeypatch):
    class Agent:
        def invoke(self, _payload):
            return {
                "structured_response": DiffReport(
                    base_ref="v1.0.1",
                    candidate_sha="a" * 40,
                    changed_paths=["main.tf"],
                    diff_summary="Changed the bucket name.",
                    change_category="naming",
                )
            }

    monkeypatch.setattr("release.agents.diff.resolve_model", lambda: object())
    monkeypatch.setattr("release.agents.diff.build_diff_agent", lambda *args, **kwargs: Agent())
    result = diff_node({"repo": "octo/mod", "candidate_ref": "latest"})
    assert result == {
        "base_ref": "v1.0.1",
        "candidate_sha": "a" * 40,
        "changed_paths": ["main.tf"],
        "diff_summary": "Changed the bucket name.",
        "change_category": "naming",
    }
