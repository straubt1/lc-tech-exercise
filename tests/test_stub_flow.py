import json

import pytest
from langchain.agents import create_agent

from release.agents.diff import build_diff_agent
from release.agents.docs import build_docs_agent
from release.agents.release import build_release_agent
from release.agents.version import build_version_agent
from release.config import LANGSMITH_CLOUD_ENDPOINT, Settings, load_settings, split_repo
from release.evals import experiment_spec, run_experiment
from release.prompts import load_prompt
from release.terraform_module_releaser import run
from release.tools.github_read import read_repo_file
from release.tools.github_release import create_draft_release


def test_prompts_come_from_files():
    for name in ("diff.md", "docs.md", "version.md", "release.md"):
        text = load_prompt(name)
        assert "You " in text
        assert "not implemented" not in text.lower()


def test_agents_use_create_agent():
    assert create_agent.__module__.startswith("langchain.agents")
    diff = build_diff_agent()
    docs = build_docs_agent()
    version = build_version_agent()
    release = build_release_agent()
    assert diff.get_name() == "diff"
    assert docs.get_name() == "docs"
    assert version.get_name() == "version"
    assert release.get_name() == "release"


def test_unpublished_tools_are_stubs_and_ignore_token(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "super-secret-token")
    results = [
        read_repo_file.invoke({"owner": "octo", "repo": "mod", "path": "README.md", "ref": "latest"}),
        create_draft_release.invoke(
            {"owner": "octo", "repo": "mod", "tag": "v1.2.0", "notes": "notes"}
        ),
    ]
    assert results == ["not implemented", "not implemented"]
    assert all("super-secret-token" not in item for item in results)


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
    }


def test_graph_approve_stops_at_stub_release(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "super-secret-token")
    monkeypatch.setattr("release.graph.diff_node", _offline_diff)
    values = run(_settings(), "thread-approve", lambda packet: {"decision": "approved"})
    encoded = json.dumps(values)
    assert "super-secret-token" not in encoded
    assert values["base_ref"] == "v1.0.1"
    assert values["diff_summary"] == "offline graph test"
    assert values["docs_findings"]["status"] == "stub"
    assert values["regression_findings"]["status"] == "not_run"
    assert values["human_decision"] == "approved"
    assert values["release_result"] == {"status": "stub", "tag": "", "url": ""}


def test_graph_reject_creates_nothing(monkeypatch):
    monkeypatch.setattr("release.graph.diff_node", _offline_diff)
    values = run(_settings(), "thread-reject", lambda packet: {"decision": "rejected"})
    assert values["release_result"]["status"] == "rejected"
    assert values["release_result"]["url"] == ""


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
    assert "bump_match" in spec["evaluators"]
    with pytest.raises(NotImplementedError):
        run_experiment()


def test_tracing_requires_a_cloud_project(monkeypatch):
    monkeypatch.setattr("release.graph.diff_node", _offline_diff)
    settings = _settings(langsmith_tracing=True)
    with pytest.raises(RuntimeError, match="LANGSMITH_PROJECT"):
        run(settings, "thread-trace", lambda packet: {"decision": "rejected"})
