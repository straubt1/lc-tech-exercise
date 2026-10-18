import json

from release.agents.docs import DocFinding, DocsReport, docs_node
from release.tools.github_read import list_files, make_docs_tools, read_file


def test_read_file_rejects_paths_outside_the_repo():
    assert "path must stay inside the repository" in read_file("octo", "mod", "../README.md", "latest")


def test_read_file_reports_a_missing_file(monkeypatch):
    def fake_file_text(owner, repo, path, ref):
        raise RuntimeError("GitHub 404 for /contents/CHANGELOG.md: missing")

    monkeypatch.setattr("release.tools.github_read._file_text", fake_file_text)
    payload = json.loads(read_file("octo", "mod", "CHANGELOG.md", "latest"))
    assert payload == {"error": "not found", "path": "CHANGELOG.md"}


def test_docs_tools_read_the_bound_candidate(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "super-secret-token")
    calls = []

    def fake_list(owner, repo, ref):
        calls.append(("list", owner, repo, ref))
        return ["README.md", "variables.tf"]

    def fake_read(owner, repo, path, ref):
        calls.append(("read", owner, repo, path, ref))
        return "variable text"

    monkeypatch.setattr("release.tools.github_read.list_files", fake_list)
    monkeypatch.setattr("release.tools.github_read.read_file", fake_read)
    listed, reader = make_docs_tools("octo", "mod", "latest")
    assert json.loads(listed.invoke({})) == {"files": ["README.md", "variables.tf"]}
    assert reader.invoke({"path": "variables.tf"}) == "variable text"
    assert calls == [
        ("list", "octo", "mod", "latest"),
        ("read", "octo", "mod", "variables.tf", "latest"),
    ]
    assert "super-secret-token" not in json.dumps(calls)


def test_list_files_uses_the_candidate_tree(monkeypatch):
    def fake_github_get(path):
        if path.endswith("/commits/latest"):
            return {"sha": "a" * 40}
        if "/git/trees/" in path:
            return {
                "truncated": False,
                "tree": [
                    {"path": "outputs.tf", "type": "blob", "sha": "1"},
                    {"path": "README.md", "type": "blob", "sha": "2"},
                ],
            }
        raise AssertionError(path)

    monkeypatch.setattr("release.tools.github_read.github_get", fake_github_get)
    assert list_files("octo", "mod", "latest") == ["README.md", "outputs.tf"]


def test_docs_node_records_findings_as_not_ready(monkeypatch):
    class Agent:
        def invoke(self, payload):
            assert "Renamed the bucket." in payload["messages"][0].content
            return {
                "structured_response": DocsReport(
                    docs_ready=True,
                    summary="Changelog omits the bucket rename.",
                    findings=[
                        DocFinding(
                            filename=" CHANGELOG.md ",
                            finding=" Add an entry for the bucket rename. ",
                        )
                    ],
                )
            }

    monkeypatch.setattr("release.agents.docs.resolve_model", lambda: object())
    monkeypatch.setattr("release.agents.docs.build_docs_agent", lambda *args, **kwargs: Agent())
    result = docs_node(
        {
            "repo": "octo/mod",
            "candidate_ref": "latest",
            "base_ref": "v1.0.1",
            "changed_paths": ["main.tf"],
            "diff_summary": "Renamed the bucket.",
        }
    )
    assert result["docs_ready"] is False
    assert result["docs_findings"]["status"] == "not_ready"
    assert result["docs_findings"]["findings"] == [
        {"filename": "CHANGELOG.md", "finding": "Add an entry for the bucket rename."}
    ]


def test_docs_node_records_a_ready_report(monkeypatch):
    class Agent:
        def invoke(self, _payload):
            return {
                "structured_response": DocsReport(
                    docs_ready=True,
                    summary="",
                    findings=[],
                )
            }

    monkeypatch.setattr("release.agents.docs.resolve_model", lambda: object())
    monkeypatch.setattr("release.agents.docs.build_docs_agent", lambda *args, **kwargs: Agent())
    result = docs_node({"repo": "octo/mod", "candidate_ref": "latest"})
    assert result == {
        "docs_ready": True,
        "docs_findings": {"status": "ready", "summary": "", "findings": []},
    }
