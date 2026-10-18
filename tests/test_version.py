import pytest

from release.agents.version import VersionDecision, next_version, version_node


def test_next_version_bumps_one_level():
    assert next_version("v1.9.9", "patch") == "v1.9.10"
    assert next_version("v1.9.9", "minor") == "v1.10.0"
    assert next_version("v1.9.9", "major") == "v2.0.0"


def test_next_version_rejects_a_non_release_tag():
    with pytest.raises(RuntimeError, match="vMAJOR.MINOR.PATCH"):
        next_version("v1.2", "patch")


def test_version_node_computes_the_next_tag(monkeypatch):
    class Agent:
        def invoke(self, payload):
            text = payload["messages"][0].content
            assert "Renamed the bucket suffix." in text
            assert "not_run" in text
            return {
                "structured_response": VersionDecision(
                    bump="patch",
                    reasons=["  Tag and name change only.  ", ""],
                    release_notes="  Rename the assets bucket suffix.  ",
                )
            }

    monkeypatch.setattr("release.agents.version.resolve_model", lambda: object())
    monkeypatch.setattr("release.agents.version.build_version_agent", lambda *args, **kwargs: Agent())
    result = version_node(
        {
            "base_ref": "v1.0.1",
            "candidate_ref": "latest",
            "changed_paths": ["main.tf"],
            "diff_summary": "Renamed the bucket suffix.",
            "docs_findings": {"status": "ready", "summary": ""},
        }
    )
    assert result == {
        "bump": "patch",
        "proposed_version": "v1.0.2",
        "reasons": ["Tag and name change only."],
        "release_notes": "Rename the assets bucket suffix.",
    }
