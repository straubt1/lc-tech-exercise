import json

import pytest

from release.agents.implement import FileEdit, ImplementReport, implement_suggestions
from release.agents.release import (
    ReleaseRecommendation,
    format_facts,
    format_recommendation,
    recommend,
)
from release.terraform_module_releaser import read_decision_from_stdin
from release.tools.github_release import create_draft_pull_request, create_draft_release


def test_facts_are_the_change_summary():
    text = format_facts(
        {
            "diff_summary": "Renamed the bucket.",
            "change_category": "naming",
            "proposed_version": "v1.0.2",
            "docs_ready": False,
        }
    )
    assert "Renamed the bucket." in text
    assert "Change: naming" in text
    assert "Suggested version: v1.0.2" in text
    assert "Docs are ready: no" in text
    assert "Regression" not in text


def test_recommendation_lists_suggestions():
    text = format_recommendation(
        {
            "recommendation": "Docs are not ready.",
            "suggestions": ["Document the variable in README.md."],
        }
    )
    assert "Docs are not ready." in text
    assert "- Document the variable in README.md." in text


def test_ready_question_asks_for_a_draft_release(monkeypatch):
    printed = []
    monkeypatch.setattr("builtins.print", lambda text, **kwargs: printed.append(text))
    monkeypatch.setattr("builtins.input", lambda prompt: printed.append(prompt) or "yes")
    decision = read_decision_from_stdin(
        {
            "ready": True,
            "candidate_ref": "latest",
            "recommendation": "Ready to release.",
            "suggestions": [],
        }
    )
    assert decision == {"decision": "yes"}
    text = "\n".join(printed)
    assert "Draft a release?" in text
    assert "pull request" not in text


def test_not_ready_question_asks_for_a_draft_pull_request(monkeypatch):
    printed = []
    monkeypatch.setattr("builtins.input", lambda prompt: printed.append(prompt) or "no")
    decision = read_decision_from_stdin(
        {
            "ready": False,
            "candidate_ref": "latest",
            "recommendation": "Docs are not ready.",
            "suggestions": ["Fix README.md."],
        }
    )
    assert decision == {"decision": "no"}
    assert any("draft pull request into latest" in line for line in printed)


def _patch_recommend(monkeypatch, report: ReleaseRecommendation, seen: dict):
    class Agent:
        def invoke(self, payload):
            seen["task"] = payload["messages"][0].content
            return {"structured_response": report}

    monkeypatch.setattr("release.agents.release.resolve_model", lambda: object())
    monkeypatch.setattr("release.agents.release.build_release_agent", lambda *args, **kwargs: Agent())


def test_recommend_blocks_release_when_docs_are_not_ready(monkeypatch):
    seen = {}
    _patch_recommend(
        monkeypatch,
        ReleaseRecommendation(ready=True, recommendation="Ship it.", suggestions=[]),
        seen,
    )
    report = recommend(
        {
            "repo": "octo/mod",
            "candidate_ref": "latest",
            "base_ref": "v1.0.1",
            "diff_summary": "Renamed the bucket.",
            "docs_ready": False,
            "docs_findings": {
                "status": "not_ready",
                "summary": "README is stale.",
                "findings": [
                    {"filename": "README.md", "finding": "Document the variable."}
                ],
            },
        }
    )
    assert "Ignore it." in seen["task"]
    assert "Renamed the bucket." in seen["task"]
    assert report.ready is False
    assert "README.md: Document the variable." in seen["task"]
    assert report.suggestions == ["README.md: Document the variable."]


def test_recommend_drops_suggestions_when_the_module_is_ready(monkeypatch):
    _patch_recommend(
        monkeypatch,
        ReleaseRecommendation(ready=True, recommendation="Ready.", suggestions=["Leave a note."]),
        {},
    )
    report = recommend(
        {
            "repo": "octo/mod",
            "docs_ready": True,
            "docs_findings": {"status": "ready", "summary": "", "findings": []},
        }
    )
    assert report.ready is True
    assert report.suggestions == []


def test_draft_release_posts_a_draft_and_hides_the_token(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "super-secret-token")
    monkeypatch.setenv("RELEASE_ENABLED", "true")
    seen = {}

    class Response:
        def read(self):
            return json.dumps({"html_url": "https://github.com/octo/mod/releases/1"}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout=60):
        seen["header"] = request.get_header("Authorization")
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode())
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = json.loads(
        create_draft_release.invoke(
            {
                "owner": "octo",
                "repo": "mod",
                "tag": "v1.2.0",
                "notes": "Rename the bucket.",
                "target": "abc123",
            }
        )
    )
    assert seen["header"] == "Bearer super-secret-token"
    assert "super-secret-token" not in seen["url"]
    assert seen["body"]["draft"] is True
    assert seen["body"]["target_commitish"] == "abc123"
    assert result == {
        "status": "draft",
        "tag": "v1.2.0",
        "url": "https://github.com/octo/mod/releases/1",
    }
    assert "super-secret-token" not in json.dumps(result)


def test_draft_release_refuses_to_send_the_token(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "super-secret-token")
    monkeypatch.setenv("RELEASE_ENABLED", "true")

    def fail_open(*_args, **_kwargs):
        raise AssertionError("secret notes must not call GitHub")

    monkeypatch.setattr("urllib.request.urlopen", fail_open)
    with pytest.raises(RuntimeError, match="GH_TOKEN") as raised:
        create_draft_release.invoke(
            {
                "owner": "octo",
                "repo": "mod",
                "tag": "v1.2.0",
                "notes": "leak super-secret-token",
                "target": "abc123",
            }
        )
    assert "super-secret-token" not in str(raised.value)


def test_draft_pull_request_retries_an_existing_branch(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "super-secret-token")
    monkeypatch.setenv("RELEASE_ENABLED", "true")
    parent = "abc1234" + "d" * 33
    calls = []

    def fake_request(method, path, payload=None):
        calls.append((method, path, payload))
        if path.endswith(f"/git/commits/{parent}"):
            return {"sha": parent, "tree": {"sha": "tree123"}}
        if path.endswith("/git/blobs"):
            return {"sha": "blob123"}
        if path.endswith("/git/trees"):
            return {"sha": "tree456"}
        if path.endswith("/git/commits"):
            return {"sha": "c" * 40}
        if path.endswith("/git/refs") and payload["ref"].endswith("/v1.2.0"):
            raise RuntimeError("GitHub 422 for POST /git/refs: already exists")
        if path.endswith("/git/refs"):
            return {"ref": payload["ref"]}
        if path.endswith("/pulls"):
            return {"html_url": "https://github.com/octo/mod/pull/8"}
        raise AssertionError(path)

    monkeypatch.setattr("release.tools.github_release._request", fake_request)
    result = create_draft_pull_request(
        "octo",
        "mod",
        "latest",
        parent,
        "v1.2.0",
        "Apply release suggestions for v1.2.0",
        "Document the variable.",
        [("README.md", "# Module\n")],
    )
    assert result["branch"] == "release-suggestions/v1.2.0-ccccccc"
    assert result["url"] == "https://github.com/octo/mod/pull/8"
    assert calls[-1][2]["draft"] is True
    assert calls[-1][2]["base"] == "latest"
    assert "super-secret-token" not in json.dumps(result)


def test_draft_pull_request_refuses_a_file_that_contains_the_token(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "super-secret-token")
    monkeypatch.setenv("RELEASE_ENABLED", "true")

    def fail_request(*_args, **_kwargs):
        raise AssertionError("a secret file must not call GitHub")

    monkeypatch.setattr("release.tools.github_release._request", fail_request)
    with pytest.raises(RuntimeError, match="GH_TOKEN") as raised:
        create_draft_pull_request(
            "octo",
            "mod",
            "latest",
            "a" * 40,
            "v1.2.0",
            "Apply release suggestions",
            "Document the variable.",
            [("README.md", "token super-secret-token\n")],
        )
    assert "super-secret-token" not in str(raised.value)


def test_implement_rejects_an_unsafe_path(monkeypatch):
    class Agent:
        def invoke(self, _payload):
            return {
                "structured_response": ImplementReport(
                    summary="Fix the readme.",
                    files=[FileEdit(path="../README.md", content="# Nope\n")],
                )
            }

    monkeypatch.setattr("release.agents.implement.resolve_model", lambda: object())
    monkeypatch.setattr("release.agents.implement.build_implement_agent", lambda *args, **kwargs: Agent())
    with pytest.raises(RuntimeError, match="unsafe path"):
        implement_suggestions(
            {"repo": "octo/mod", "candidate_ref": "latest"},
            ["Fix README.md."],
        )
