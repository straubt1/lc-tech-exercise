import json

import pytest
from langchain.agents import create_agent

from release.agents.diff import build_diff_agent
from release.agents.docs import build_docs_agent
from release.agents.implement import build_implement_agent
from release.agents.release import ReleaseRecommendation, build_release_agent
from release.agents.version import build_version_agent
from release.config import LANGSMITH_CLOUD_ENDPOINT, Settings, load_settings, split_repo
from release.evals import experiment_spec
from release.prompts import load_prompt
from release.terraform_module_releaser import run
from release.tools.github_release import create_draft_release


def test_prompts_come_from_files():
    for name in ("diff.md", "docs.md", "version.md", "release.md", "implement.md"):
        text = load_prompt(name)
        assert "You " in text
        assert "not implemented" not in text.lower()


def test_agents_use_create_agent():
    assert create_agent.__module__.startswith("langchain.agents")
    diff = build_diff_agent()
    docs = build_docs_agent()
    version = build_version_agent()
    release = build_release_agent()
    implement = build_implement_agent()
    assert diff.get_name() == "diff"
    assert docs.get_name() == "docs"
    assert version.get_name() == "version"
    assert release.get_name() == "release"
    assert implement.get_name() == "implement"


def test_draft_release_stays_dry_without_the_flag(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "super-secret-token")
    monkeypatch.delenv("RELEASE_ENABLED", raising=False)

    def fail_open(*_args, **_kwargs):
        raise AssertionError("dry run must not call GitHub")

    monkeypatch.setattr("urllib.request.urlopen", fail_open)
    result = create_draft_release.invoke(
        {
            "owner": "octo",
            "repo": "mod",
            "tag": "v1.2.0",
            "notes": "notes",
            "target": "abc123",
        }
    )
    assert json.loads(result) == {"status": "dry_run", "tag": "v1.2.0", "url": ""}
    assert "super-secret-token" not in result


def _settings(**overrides) -> Settings:
    values = {
        "github_repo": "octo/mod",
        "candidate_ref": "latest",
        "model": "",
        "langsmith_tracing": False,
        "langsmith_api_key": "",
        "langsmith_project": "",
        "langsmith_endpoint": LANGSMITH_CLOUD_ENDPOINT,
        "release_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)


def _offline_diff(_state):
    return {
        "base_ref": "v1.0.1",
        "candidate_sha": "abc123",
        "changed_paths": ["main.tf"],
        "diff_summary": "offline graph test",
        "change_category": "naming",
    }


def _offline_docs(_state):
    return {
        "docs_ready": False,
        "docs_findings": {
            "status": "not_ready",
            "summary": "offline docs test",
            "findings": [
                {"filename": "README.md", "finding": "Document the missing variable."}
            ],
        },
    }


def _offline_version(_state):
    return {
        "bump": "patch",
        "proposed_version": "v1.0.2",
        "reasons": ["offline version test"],
        "release_notes": "offline notes",
    }


def _offline_docs_ready(_state):
    return {
        "docs_ready": True,
        "docs_findings": {"status": "ready", "summary": "", "findings": []},
    }


def _offline_recommend(state):
    ready = bool(state.get("docs_ready"))
    return ReleaseRecommendation(
        ready=ready,
        recommendation="Ready to release." if ready else "Docs are not ready.",
        suggestions=[] if ready else ["Document the variable in README.md."],
    )


def _patch_offline_graph(monkeypatch):
    monkeypatch.setattr("release.graph.diff_node", _offline_diff)
    monkeypatch.setattr("release.graph.docs_node", _offline_docs)
    monkeypatch.setattr("release.graph.version_node", _offline_version)
    monkeypatch.setattr("release.agents.release.recommend", _offline_recommend)


def test_ready_yes_stays_dry_without_the_flag(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "super-secret-token")
    _patch_offline_graph(monkeypatch)
    monkeypatch.setattr("release.graph.docs_node", _offline_docs_ready)

    def fail_open(*_args, **_kwargs):
        raise AssertionError("dry run must not call GitHub")

    monkeypatch.setattr("urllib.request.urlopen", fail_open)
    seen = {}

    def choose(packet):
        seen["packet"] = packet
        return {"decision": "yes"}

    values = run(_settings(), "thread-yes", choose)
    encoded = json.dumps(values)
    assert "super-secret-token" not in encoded
    assert seen["packet"]["diff_summary"] == "offline graph test"
    assert seen["packet"]["proposed_version"] == "v1.0.2"
    assert seen["packet"]["docs_ready"] is True
    assert seen["packet"]["ready"] is True
    assert "regression" not in json.dumps(seen["packet"])
    assert values["base_ref"] == "v1.0.1"
    assert values["regression_findings"]["status"] == "not_run"
    assert values["human_decision"] == "draft_release"
    assert values["release_result"]["status"] == "dry_run"
    assert values["release_result"]["url"] == ""
    assert values["release_result"]["action"] == "release"


def test_not_ready_no_exits(monkeypatch):
    _patch_offline_graph(monkeypatch)
    values = run(_settings(), "thread-no", lambda packet: {"decision": "no"})
    assert values["ready_for_release"] is False
    assert values["human_decision"] == "exit"
    assert values["release_result"] == {
        "status": "exit",
        "tag": "",
        "url": "",
        "branch": "",
        "action": "",
    }


def test_not_ready_yes_stays_dry_without_implementing(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "super-secret-token")
    _patch_offline_graph(monkeypatch)

    def fail_implement(*_args, **_kwargs):
        raise AssertionError("dry run must not implement suggestions")

    monkeypatch.setattr("release.agents.release.implement_suggestions", fail_implement)
    values = run(_settings(), "thread-pr", lambda packet: {"decision": "yes"})
    assert "super-secret-token" not in json.dumps(values)
    assert values["human_decision"] == "draft_pr"
    assert values["release_result"]["status"] == "dry_run"
    assert values["release_result"]["action"] == "pull_request"
    assert values["release_result"]["url"] == ""


def test_ready_yes_opens_a_draft_release(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "super-secret-token")
    monkeypatch.setenv("RELEASE_ENABLED", "true")
    _patch_offline_graph(monkeypatch)
    monkeypatch.setattr("release.graph.docs_node", _offline_docs_ready)
    calls = []

    def fake_request(method, path, payload=None):
        calls.append((method, path, payload))
        assert "super-secret-token" not in json.dumps(payload)
        return {"html_url": "https://github.com/octo/mod/releases/1"}

    monkeypatch.setattr("release.tools.github_release._request", fake_request)
    values = run(_settings(release_enabled=True), "thread-draft", lambda _packet: {"decision": "yes"})
    assert calls[0][0] == "POST"
    assert calls[0][1] == "/repos/octo/mod/releases"
    assert calls[0][2]["draft"] is True
    assert calls[0][2]["tag_name"] == "v1.0.2"
    assert calls[0][2]["target_commitish"] == "abc123"
    assert values["human_decision"] == "draft_release"
    assert values["release_result"]["status"] == "draft"
    assert values["release_result"]["url"] == "https://github.com/octo/mod/releases/1"
    assert "super-secret-token" not in json.dumps(values)


def test_not_ready_yes_opens_a_draft_pull_request(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "super-secret-token")
    monkeypatch.setenv("RELEASE_ENABLED", "true")
    _patch_offline_graph(monkeypatch)
    monkeypatch.setattr(
        "release.agents.release.implement_suggestions",
        lambda _state, _suggestions: [("README.md", "# Fixed\n")],
    )
    calls = []

    def fake_request(method, path, payload=None):
        calls.append((method, path, payload))
        if payload is not None:
            assert "super-secret-token" not in json.dumps(payload)
        if path.endswith("/git/commits/abc123"):
            return {"sha": "abc123", "tree": {"sha": "tree123"}}
        if path.endswith("/git/blobs"):
            return {"sha": "blob123"}
        if path.endswith("/git/trees"):
            return {"sha": "tree456"}
        if path.endswith("/git/commits"):
            return {"sha": "commit456"}
        if path.endswith("/git/refs"):
            assert payload["sha"] == "commit456"
            assert payload["ref"] == "refs/heads/release-suggestions/v1.0.2"
            return {"ref": payload["ref"]}
        if path.endswith("/pulls"):
            return {"html_url": "https://github.com/octo/mod/pull/4"}
        raise AssertionError(path)

    monkeypatch.setattr("release.tools.github_release._request", fake_request)
    values = run(_settings(release_enabled=True), "thread-open-pr", lambda _packet: {"decision": "yes"})
    pull = calls[-1][2]
    assert pull["draft"] is True
    assert pull["base"] == "latest"
    assert pull["head"] == "release-suggestions/v1.0.2"
    assert values["release_result"] == {
        "status": "draft_pr",
        "tag": "",
        "url": "https://github.com/octo/mod/pull/4",
        "branch": "release-suggestions/v1.0.2",
        "action": "pull_request",
    }
    assert "super-secret-token" not in json.dumps(values)


def test_settings_do_not_carry_the_token(monkeypatch):
    monkeypatch.setenv("GITHUB_REPO", "octo/mod")
    monkeypatch.setenv("GH_TOKEN", "super-secret-token")
    settings = load_settings()
    assert split_repo(settings.github_repo) == ("octo", "mod")
    assert "super-secret-token" not in json.dumps(settings.__dict__)


def test_langsmith_experiment_targets_cloud():
    spec = experiment_spec()
    assert spec["endpoint"] == LANGSMITH_CLOUD_ENDPOINT
    assert spec["dataset"] == "tf-module-release"
    assert spec["evaluators"] == ["bump_match", "docs_ready_match", "draft_release_not_called"]
    assert spec["runner"] == "evaluate"


def test_tracing_requires_a_cloud_project(monkeypatch):
    monkeypatch.setattr("release.graph.diff_node", _offline_diff)
    settings = _settings(langsmith_tracing=True)
    with pytest.raises(RuntimeError, match="LANGSMITH_PROJECT"):
        run(settings, "thread-trace", lambda packet: {"decision": "no"})
