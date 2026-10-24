from langgraph.errors import GraphRecursionError
from langgraph.graph import END

from review.graph import (
    after_check,
    run_check,
    run_gate,
    run_interface,
    run_recommend,
    run_release,
    run_security,
)
from review.reader import FixtureReader


class FakeAgent:
    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.prompts = []

    def invoke(self, payload, _config):
        self.prompts.append(payload["messages"][0]["content"])
        body = self.bodies.pop(0)
        if body is None:
            raise GraphRecursionError("stopped")
        return {"structured_response": body}


def test_check_stops_on_an_error_and_continues_when_the_ref_is_present():
    class Missing(FixtureReader):
        def check(self, repo, ref):
            return f"not found: {repo}@{ref}"

    assert run_check({"repo": "acme/mod", "ref": "missing"}, Missing()) == {
        "error": "not found: acme/mod@missing"
    }
    assert run_check({"repo": "acme/mod", "ref": "latest"}, FixtureReader()) == {}
    assert after_check({"error": "repo is required"}) == END
    assert after_check({}) == ["interface", "security", "release"]


def test_interface_and_security_force_fail_and_stop_early():
    failed = FakeAgent(
        [{"status": "pass", "findings": [{"filename": "README.md", "finding": "missing variable"}]}]
    )
    assert run_interface({"repo": "acme/mod", "ref": "latest"}, failed) == {
        "interface_status": "fail",
        "interface_findings": [{"filename": "README.md", "finding": "missing variable"}],
    }

    stopped = FakeAgent([None])
    assert run_security({"repo": "acme/mod", "ref": "latest"}, stopped)["security_findings"] == [
        {
            "filename": "module",
            "finding": "Stopped early. The module is larger than this pass can read.",
        }
    ]
    assert "The minimum severity is HIGH" in stopped.prompts[0]


def test_release_short_circuits_and_normalizes_the_version():
    reader = FixtureReader(
        tags=["v1.2.3-rc1"],
        compares={("v1.2.3-rc1", "latest"): "status: identical\nahead_by: 0\nno changes"},
    )
    agent = FakeAgent([])
    held = {}
    result = run_release({"repo": "acme/mod", "ref": "latest"}, agent, reader, held)
    assert agent.prompts == []
    assert result["current_version"] == "v1.2.3-rc1"
    assert result["suggested_version"] == "none"
    assert result["bump"] == "none"
    assert held["release_tags"] == ["v1.2.3-rc1"]
    assert "changelog" not in held

    changed = FixtureReader(
        tags=["v1.0.0"],
        compares={("v1.0.0", "latest"): "status: ahead\nahead_by: 1\n"},
        files={("latest", "CHANGELOG.md"): "# Changelog\n\n## 1.0.0\n"},
    )
    agent = FakeAgent(
        [
            {
                "status": "ready",
                "suggested_version": "1.1.0",
                "bump": "minor",
                "findings": [{"filename": "CHANGELOG.md", "finding": "heading is still v1.0.0"}],
            }
        ]
    )
    loaded = {}
    result = run_release({"repo": "acme/mod", "ref": "latest"}, agent, changed, loaded)
    assert loaded["changelog"] == "# Changelog\n\n## 1.0.0\n"
    assert result["release_status"] == "not ready"
    assert result["suggested_version"] == "v1.1.0"
    assert result["current_version"] == "v1.0.0"


def test_a_matching_heading_drops_a_pass_and_keeps_a_notes_mismatch():
    reader = FixtureReader(
        tags=["v1.0.0"],
        compares={("v1.0.0", "latest"): "status: ahead\nahead_by: 1\n"},
        files={("latest", "CHANGELOG.md"): "# Changelog\n\n## 1.0.1\n\n- Allow public read.\n"},
    )
    agent = FakeAgent(
        [
            {
                "status": "not ready",
                "suggested_version": "v1.0.1",
                "bump": "patch",
                "findings": [{"filename": "CHANGELOG.md", "finding": "confirm the security intent"}],
            }
        ]
    )
    result = run_release({"repo": "acme/mod", "ref": "latest"}, agent, reader, {})
    assert result["release_status"] == "ready"
    assert result["release_findings"] == []
    assert result["suggested_version"] == "v1.0.1"

    missed = FakeAgent(
        [
            {
                "status": "ready",
                "suggested_version": "v1.0.1",
                "bump": "patch",
                "findings": [
                    {
                        "filename": "CHANGELOG.md",
                        "finding": "v1.0.1 leaves out the public-read ACL.",
                    }
                ],
            }
        ]
    )
    kept = run_release({"repo": "acme/mod", "ref": "latest"}, missed, reader, {})
    assert kept["release_status"] == "not ready"
    assert kept["release_findings"] == [
        {"filename": "CHANGELOG.md", "finding": "v1.0.1 leaves out the public-read ACL."}
    ]


def test_a_none_bump_clears_the_suggested_version():
    reader = FixtureReader(tags=["v1.0.0"], compares={("v1.0.0", "latest"): "status: ahead\n"})
    agent = FakeAgent(
        [{"status": "not ready", "suggested_version": "v9.9.9", "bump": "none", "findings": []}]
    )
    result = run_release({"repo": "acme/mod", "ref": "latest"}, agent, reader, {})
    assert result["suggested_version"] == "none"
    assert result["bump"] == "none"


def test_a_tag_lookup_failure_stays_on_release():
    class Broken(FixtureReader):
        def list_release_tags(self):
            raise RuntimeError("github error 403: rate limit")

    result = run_release({"repo": "acme/mod", "ref": "latest"}, FakeAgent([]), Broken(), {})
    assert result["release_findings"] == [
        {"filename": "CHANGELOG.md", "finding": "github error 403: rate limit"}
    ]
    assert result["current_version"] == ""


def test_recommend_asks_once_more_for_a_missing_file():
    state = {
        "repo": "acme/mod",
        "ref": "latest",
        "interface_findings": [{"filename": "README.md", "finding": "missing variable"}],
        "security_findings": [{"filename": "main.tf", "finding": "HIGH public bucket"}],
    }
    agent = FakeAgent(
        [
            {
                "suggestions": "Block public access.",
                "pr_title": "Block public access for v1.2.0",
                "pr_body": "## Summary",
                "proposed_files": [{"filename": "README.md", "content": "# Readme\n"}],
            },
            {"proposed_files": [{"filename": "main.tf", "content": "resource {}\n"}]},
        ]
    )
    allowed = {"files": set()}
    result = run_recommend(state, agent, allowed)
    assert [item["filename"] for item in result["proposed_files"]] == ["README.md", "main.tf"]
    assert "left out of proposed_files" in agent.prompts[1]
    assert allowed["files"] == {"main.tf"}


def test_gate_filters_files_and_appends_a_missing_security_line():
    names = [f"file{index}.tf" for index in range(11)]
    state = {
        "repo": "acme/mod",
        "ref": "latest",
        "interface_status": "fail",
        "security_status": "fail",
        "release_status": "ready",
        "interface_findings": [{"filename": "README.md", "finding": "missing variable"}],
        "security_findings": [{"filename": name, "finding": f"HIGH {name}"} for name in names],
        "suggested_version": "v1.2.0",
        "pr_title": "Fix the module for v1.2.0",
        "pr_body": "## Summary\nFixes.\n",
        "proposed_files": [
            {"filename": "README.md", "content": "# Readme\n"},
            *[{"filename": name, "content": f"# {name}\n"} for name in names],
            {"filename": "notes.md", "content": "nope\n"},
        ],
    }
    calls = []

    def opener(**kwargs):
        calls.append(kwargs)
        return "https://github.com/example/pull/2"

    assert run_gate(state, "no", opener) == {"decision": "no"}
    assert calls == []

    opened = run_gate(state, "yes", opener)
    assert opened["pr_url"] == "https://github.com/example/pull/2"
    assert [item["filename"] for item in calls[0]["proposed_files"]] == ["README.md", *names[:9]]
    assert "notes.md" not in [item["filename"] for item in calls[0]["proposed_files"]]
    assert "More recommendations were not applied:" in calls[0]["body"]
    assert "file10.tf" in calls[0]["body"]
    assert "file0.tf: HIGH file0.tf" in calls[0]["body"]

    empty = run_gate({"repo": "acme/mod", "ref": "latest", "proposed_files": []}, "yes", opener)
    assert empty == {"decision": "yes"}
    assert len(calls) == 1
