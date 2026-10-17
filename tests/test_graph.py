import json
import subprocess
from pathlib import Path

import pytest
from langgraph.types import Command

from release.agents import VERSION_SYSTEM_PROMPT, VersionDecision, version_agent
from release.cli import format_result, pending_interrupt, run
from release.graph import build_graph
from release.nodes import load_node
from release.policy import NOT_RUN
from release.state import ReleaseState

REAL_MODULE = Path("/Users/tstraub/Projects/straubt1.github.com/terraform-aws-storage")


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=release-test@example.com",
            "-c",
            "user.name=release-test",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def make_repo(path: Path, *, local_versions: bool) -> Path:
    path.mkdir()
    git(path, "init", "-b", "main")
    (path / "variables.tf").write_text('variable "name_prefix" {\n  default = "networking"\n}\n')
    (path / "README.md").write_text("# module\n")
    git(path, "add", "variables.tf", "README.md")
    git(path, "commit", "-m", "v1.0.0")
    sha_100 = git(path, "rev-parse", "HEAD")
    git(path, "branch", "v1.0.0")
    (path / "variables.tf").write_text('variable "name_prefix" {\n  default = "demo"\n}\n')
    git(path, "commit", "-am", "v1.0.1")
    sha_101 = git(path, "rev-parse", "HEAD")
    git(path, "branch", "v1.0.1")
    (path / "variables.tf").write_text('variable "name_prefix" {\n  default = "storage"\n}\n')
    (path / "outputs.tf").write_text('output "bucket_domain_name" {\n  value = "example"\n}\n')
    git(path, "add", "variables.tf", "outputs.tf")
    git(path, "commit", "-m", "candidate")
    git(path, "update-ref", "refs/remotes/origin/v1.0.0", sha_100)
    git(path, "update-ref", "refs/remotes/origin/v1.0.1", sha_101)
    git(path, "update-ref", "refs/remotes/origin/release/verify-v1.0.2", "HEAD")
    git(path, "update-ref", "refs/remotes/origin/feature/update-tags", "HEAD")
    git(path, "update-ref", "refs/remotes/origin/v1.2", "HEAD")
    git(path, "update-ref", "refs/remotes/origin/v1.2.3-rc1", "HEAD")
    if not local_versions:
        git(path, "branch", "-D", "v1.0.0")
        git(path, "branch", "-D", "v1.0.1")
    return path


def test_prompt_tells_the_model_not_run_was_not_run():
    assert "was not run" in VERSION_SYSTEM_PROMPT
    assert "Do not invent a pass" in VERSION_SYSTEM_PROMPT
    assert "bind_tools" not in VERSION_SYSTEM_PROMPT


def test_version_agent_computes_branch_and_hides_token(monkeypatch):
    seen: list[str] = []

    class FakeStructured:
        def invoke(self, messages):
            seen.append("\n".join(message.content for message in messages))
            return VersionDecision(
                bump="minor",
                reasons=["Added output bucket_domain_name."],
                blockers=["  "],
                ready_for_release=False,
                release_notes="  Add the bucket domain output.  ",
            )

    class FakeModel:
        def with_structured_output(self, schema, **kwargs):
            assert schema is VersionDecision
            assert kwargs.get("method") == "json_schema"
            return FakeStructured()

        def bind_tools(self, tools):
            raise AssertionError("version agent must not bind tools")

    monkeypatch.setenv("MODEL", "openai:gpt-test")
    monkeypatch.setenv("GH_TOKEN", "ghp_sampletoken_should_not_leak")
    monkeypatch.setattr("release.agents.init_chat_model", lambda *args, **kwargs: FakeModel())

    state: ReleaseState = {
        "base_ref": "origin/v1.0.1",
        "candidate_ref": "main",
        "candidate_sha": "abc",
        "changed_paths": ["outputs.tf"],
        "diff_summary": "added an output",
        "interface": {},
        "contract_findings": {"status": NOT_RUN},
        "docs_findings": {"status": NOT_RUN},
        "regression_findings": {"status": NOT_RUN},
    }
    result = version_agent(state)
    assert result["bump"] == "minor"
    assert result["proposed_version"] == "v1.1.0"
    assert result["ready_for_release"] is True
    assert result["blockers"] == []
    assert result["release_notes"] == "Add the bucket domain output."
    blob = "\n".join(seen)
    assert "ghp_sampletoken_should_not_leak" not in blob
    assert NOT_RUN in blob
    assert "GH_TOKEN" not in blob


def test_version_agent_docs_only_has_no_branch(monkeypatch):
    class FakeStructured:
        def invoke(self, messages):
            return {
                "bump": "none",
                "reasons": ["README only."],
                "blockers": [],
                "ready_for_release": True,
                "release_notes": "Docs only.",
            }

    class FakeModel:
        def with_structured_output(self, schema, **kwargs):
            return FakeStructured()

    monkeypatch.setenv("MODEL", "openai:gpt-test")
    monkeypatch.setattr("release.agents.init_chat_model", lambda *args, **kwargs: FakeModel())
    result = version_agent(
        {
            "base_ref": "v1.0.1",
            "contract_findings": {"status": NOT_RUN},
            "docs_findings": {"status": NOT_RUN},
            "regression_findings": {"status": NOT_RUN},
        }
    )
    assert result["proposed_version"] == ""
    assert result["ready_for_release"] is False


def test_load_prefers_remote_when_main_has_no_local_version(tmp_path: Path):
    repo = make_repo(tmp_path / "module", local_versions=False)
    (repo / "notes.txt").write_text("super-secret-token-value")
    loaded = load_node({"module_path": str(repo)})
    assert loaded["base_ref"] == "origin/v1.0.1"
    assert loaded["candidate_ref"] == "main"
    assert loaded["interface"] == {}
    assert "variables.tf" in loaded["changed_paths"]
    assert "outputs.tf" in loaded["changed_paths"]
    assert 'default = "storage"' in loaded["diff_summary"]
    assert "notes.txt" in loaded["diff_summary"]
    assert "super-secret-token-value" not in loaded["diff_summary"]


def test_load_prefers_local_version_branch(tmp_path: Path):
    repo = make_repo(tmp_path / "module", local_versions=True)
    loaded = load_node({"module_path": str(repo)})
    assert loaded["base_ref"] == "v1.0.1"


def _fake_version(state: ReleaseState) -> dict:
    return {
        "bump": "patch",
        "proposed_version": "v1.0.2",
        "reasons": ["Behavior change only."],
        "blockers": [],
        "ready_for_release": True,
        "release_notes": "Patch the bucket tags.",
    }


def _run_decision(repo: Path, decision: dict[str, str], monkeypatch) -> ReleaseState:
    monkeypatch.setattr("release.graph.version_agent", _fake_version)
    monkeypatch.setenv("GH_TOKEN", "ghp_sampletoken_should_not_leak")
    captured: dict[str, dict] = {}

    def read_decision(packet, state):
        captured["packet"] = packet
        captured["state"] = state
        return decision

    values = run(str(repo), "thread-1", read_decision)
    captured_packet = captured["packet"]
    assert captured_packet["bump"] == "patch"
    assert captured_packet["proposed_version"] == "v1.0.2"
    for key in ("contract_findings", "docs_findings", "regression_findings"):
        assert captured_packet[key]["status"] == NOT_RUN
    assert captured["state"]["base_ref"] == "origin/v1.0.1"
    blob = json.dumps(values)
    assert "ghp_sampletoken_should_not_leak" not in blob
    branches = git(repo, "branch", "--list", "v1.0.2")
    assert branches == ""
    return values


def test_approve_is_a_dry_run_on_the_same_thread(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path / "module", local_versions=False)
    values = _run_decision(repo, {"decision": "approved", "version": "", "notes": ""}, monkeypatch)
    assert values["human_decision"] == "approved"
    assert values["release_result"] == {"status": "dry_run", "branch": "v1.0.2", "url": ""}
    assert "Dry run only" in format_result(values["release_result"])


def test_reject_creates_no_branch(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path / "module", local_versions=False)
    values = _run_decision(repo, {"decision": "rejected", "version": "", "notes": ""}, monkeypatch)
    assert values["release_result"] == {"status": "rejected", "branch": "", "url": ""}


def test_edit_uses_the_edited_branch_and_notes(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path / "module", local_versions=False)
    values = _run_decision(
        repo,
        {"decision": "edited", "version": "v1.4.0", "notes": "Ship the edited notes."},
        monkeypatch,
    )
    assert values["human_edited_version"] == "v1.4.0"
    assert values["human_edited_notes"] == "Ship the edited notes."
    assert values["release_result"] == {"status": "dry_run", "branch": "v1.4.0", "url": ""}
    assert git(repo, "branch", "--list", "v1.4.0") == ""


def test_edit_rejects_a_non_release_name(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path / "module", local_versions=False)
    values = _run_decision(
        repo,
        {"decision": "edited", "version": "v1.2", "notes": "nope"},
        monkeypatch,
    )
    assert values["release_result"]["status"] == "invalid_version"
    assert values["release_result"]["branch"] == "v1.2"
    assert git(repo, "branch", "--list", "v1.2") == ""


def test_graph_edges_stay_linear():
    graph = build_graph()
    edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
    assert ("__start__", "load") in edges
    assert ("load", "contract") in edges
    assert ("contract", "docs") in edges
    assert ("docs", "regression") in edges
    assert ("regression", "version") in edges
    assert ("version", "review") in edges
    assert ("review", "release") in edges
    assert ("release", "__end__") in edges


def test_resume_uses_checkpoint_interrupt(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path / "module", local_versions=False)
    monkeypatch.setattr("release.graph.version_agent", _fake_version)
    graph = build_graph()
    config = {"configurable": {"thread_id": "same-thread"}}
    first = graph.invoke({"module_path": str(repo)}, config)
    packet = pending_interrupt(graph, config, first)
    assert packet is not None
    assert packet["regression_findings"]["status"] == NOT_RUN
    resumed = graph.invoke(
        Command(resume={"decision": "approved", "version": "", "notes": ""}),
        config,
    )
    assert pending_interrupt(graph, config, resumed) is None
    assert graph.get_state(config).values["release_result"]["status"] == "dry_run"


@pytest.mark.skipif(not REAL_MODULE.is_dir(), reason="storage module checkout is not on this machine")
def test_real_module_on_main_baselines_origin_v1_0_1():
    loaded = load_node({"module_path": str(REAL_MODULE)})
    assert loaded["candidate_ref"] == "main"
    assert loaded["base_ref"] == "origin/v1.0.1"
    assert loaded["candidate_sha"]
    for path in ("variables.tf", "outputs.tf", "main.tf", "README.md"):
        assert path in loaded["changed_paths"]
    assert "bucket_domain_name" in loaded["diff_summary"]
    assert "lockfileVersion" not in loaded["diff_summary"]
