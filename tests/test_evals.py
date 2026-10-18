import json
import urllib.request
from types import SimpleNamespace

import pytest

from release.evals import (
    EVALUATORS,
    bump_match,
    docs_ready_match,
    draft_release_not_called,
    evaluator_functions,
    github_transport_for,
    load_cases,
    run_case,
)
from release.tools.github_read import diff_refs, github_get, read_file, use_github_transport

GRAPH_GOLD = {
    "removed-variable": ("major", True),
    "new-required-variable": ("major", True),
    "new-optional-variable": ("minor", True),
    "default-change": ("patch", True),
    "docs-only": ("patch", True),
    "missing-changelog": ("patch", False),
    "missing-readme-outputs": ("patch", False),
    "contract-stable-bugfix": ("patch", True),
    "stale-readme-minor": ("minor", False),
}
VERSION_GOLD = {"version-removed-variable": "major"}


def test_dataset_rows_carry_gold_labels():
    rows = {row["id"]: row for row in load_cases()}
    assert set(rows) == set(GRAPH_GOLD) | set(VERSION_GOLD)
    for row_id, (bump, docs_ready) in GRAPH_GOLD.items():
        row = rows[row_id]
        assert row["inputs"]["target"] == "graph"
        assert row["outputs"] == {"bump": bump, "docs_ready": docs_ready}
        assert set(row["inputs"]["files"]) == {"v1.0.0", "latest"}
    for row_id, bump in VERSION_GOLD.items():
        row = rows[row_id]
        assert row["inputs"]["target"] == "version"
        assert row["outputs"] == {"bump": bump}
        assert row["inputs"]["diff_summary"]
        assert "files" not in row["inputs"]


def test_evaluator_names_match_the_experiment_spec():
    assert [fn.__name__ for fn in evaluator_functions()] == list(EVALUATORS)


def test_bump_match_scores_the_gold_bump():
    assert bump_match({"bump": "major"}, {"bump": "major"}) == {"key": "bump_match", "score": 1}
    assert bump_match({"bump": "patch"}, {"bump": "major"}) == {"key": "bump_match", "score": 0}
    assert bump_match({"bump": "major"}, {}) == {"results": []}


def test_docs_ready_match_skips_version_rows():
    ready = {"docs_findings": {"status": "ready"}}
    missing = {"docs_findings": {"status": "not_ready"}}
    assert docs_ready_match(ready, {"docs_ready": True}) == {"key": "docs_ready_match", "score": 1}
    assert docs_ready_match(missing, {"docs_ready": True}) == {"key": "docs_ready_match", "score": 0}
    assert docs_ready_match({}, {"docs_ready": False}) == {"key": "docs_ready_match", "score": 1}
    assert docs_ready_match(ready, {}) == {"results": []}


def test_draft_release_not_called_walks_child_runs():
    quiet = SimpleNamespace(name="release", child_runs=[SimpleNamespace(name="interrupt", child_runs=[])])
    called = SimpleNamespace(
        name="graph",
        child_runs=[
            SimpleNamespace(
                name="release",
                child_runs=[SimpleNamespace(name="create_draft_release", child_runs=[])],
            )
        ],
    )
    assert draft_release_not_called(quiet) == {"key": "draft_release_not_called", "score": 1}
    assert draft_release_not_called(called) == {"key": "draft_release_not_called", "score": 0}


def test_github_get_uses_live_http_when_the_transport_is_unset(monkeypatch):
    calls = []

    class Response:
        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=30):
        calls.append(request.full_url)
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert github_get("/repos/octo/mod/tags?per_page=100&page=1") == {}
    assert calls == ["https://api.github.com/repos/octo/mod/tags?per_page=100&page=1"]
    assert "token" not in json.dumps(calls)


def test_github_transport_serves_one_example_then_live_reads_resume(monkeypatch):
    calls = []

    class Response:
        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=30):
        calls.append(request.full_url)
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with use_github_transport(lambda path: {"from": "snapshot", "path": path}):
        assert github_get("/repos/fixture/mod/tags") == {
            "from": "snapshot",
            "path": "/repos/fixture/mod/tags",
        }
        assert calls == []
    assert github_get("/repos/octo/mod/tags") == {}
    assert calls == ["https://api.github.com/repos/octo/mod/tags"]


@pytest.mark.parametrize(
    ("row_id", "changed", "unchanged"),
    [
        (
            "removed-variable",
            {"variables.tf", "main.tf", "README.md", "CHANGELOG.md"},
            {"outputs.tf"},
        ),
        (
            "docs-only",
            {"README.md", "CHANGELOG.md"},
            {"main.tf", "variables.tf", "outputs.tf"},
        ),
        (
            "missing-changelog",
            {"main.tf"},
            {"README.md", "CHANGELOG.md", "variables.tf", "outputs.tf"},
        ),
        (
            "contract-stable-bugfix",
            {"main.tf", "CHANGELOG.md"},
            {"README.md", "variables.tf", "outputs.tf"},
        ),
    ],
)
def test_snapshot_transport_diffs_graph_cases_locally(monkeypatch, row_id, changed, unchanged):
    def fail_urlopen(*args, **kwargs):
        raise AssertionError("live GitHub read")

    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)
    row = next(item for item in load_cases() if item["id"] == row_id)
    transport = github_transport_for(row["inputs"]["files"], row["inputs"]["base_ref"])
    with use_github_transport(transport):
        report = diff_refs("fixture", "mod", "v1.0.0", "latest")
        readme = read_file("fixture", "mod", "README.md", "latest")
    paths = {item["path"] for item in report["files"]}
    assert changed <= paths
    assert unchanged.isdisjoint(paths)
    assert report["candidate_sha"]
    assert readme == row["inputs"]["files"]["latest"]["README.md"]


def test_version_case_uses_the_frozen_summary(monkeypatch):
    def fail_urlopen(*args, **kwargs):
        raise AssertionError("live GitHub read")

    def fake_version(state):
        assert "Removed the force_destroy variable" in state["diff_summary"]
        assert state["base_ref"] == "v1.0.0"
        assert state["docs_findings"]["status"] == "ready"
        return {
            "bump": "major",
            "proposed_version": "v2.0.0",
            "reasons": ["removed a variable"],
            "release_notes": "Remove force_destroy.",
        }

    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)
    monkeypatch.setattr("release.evals.version_node", fake_version)
    row = next(item for item in load_cases() if item["id"] == "version-removed-variable")
    assert run_case(row["inputs"])["bump"] == "major"


def test_graph_case_stops_at_the_human_gate(monkeypatch):
    def diff_node(_state):
        return {
            "base_ref": "v1.0.0",
            "candidate_sha": "a" * 40,
            "changed_paths": ["variables.tf"],
            "diff_summary": "Removed force_destroy.",
            "change_category": "breaking",
        }

    def docs_node(_state):
        return {
            "docs_ready": True,
            "docs_findings": {"status": "ready", "summary": "", "findings": []},
        }

    def version_node(_state):
        return {
            "bump": "major",
            "proposed_version": "v2.0.0",
            "reasons": ["removed a variable"],
            "release_notes": "Remove force_destroy.",
        }

    monkeypatch.setattr("release.graph.diff_node", diff_node)
    monkeypatch.setattr("release.graph.docs_node", docs_node)
    monkeypatch.setattr("release.graph.version_node", version_node)
    monkeypatch.setattr(
        "release.agents.release.recommend",
        lambda _state: SimpleNamespace(
            ready=True,
            recommendation="Ready to release.",
            suggestions=[],
        ),
    )
    row = next(item for item in load_cases() if item["id"] == "removed-variable")
    packet = run_case(row["inputs"])
    assert packet["bump"] == "major"
    assert packet["docs_findings"]["status"] == "ready"
    assert packet["ready"] is True
    assert "release_result" not in packet
    assert "create_draft_release" not in json.dumps(packet)
