from review.normalize import (
    apply_files,
    bump,
    findings,
    heading_is_ready,
    kept_files,
    no_changes,
    pull_version,
    recommend_text,
    released,
    severity,
    status,
    version,
    with_security,
    with_skipped,
)


def test_a_newer_heading_that_matches_the_suggestion_is_ready():
    changelog = "# Changelog\n\n## 1.0.1\n\n- Allow public read.\n"
    assert heading_is_ready(changelog, "v1.0.1", "v1.0.0")
    assert heading_is_ready("# Changelog\n\n## v2.0.0\n", "2.0.0", "v1.0.0")
    assert not heading_is_ready("# Changelog\n\n## 1.0.0\n", "v1.0.1", "v1.0.0")
    assert not heading_is_ready("# Changelog\n\n## 1.0.0\n", "v1.0.0", "v1.0.0")
    assert not heading_is_ready("# Changelog\n\n## Unreleased\n", "v1.0.0", "")


def test_version_adds_a_leading_v_and_leaves_other_text():
    assert version("1.1.0") == "v1.1.0"
    assert version("v1.1.0") == "v1.1.0"
    assert version("  v1.2.0  ") == "v1.2.0"
    assert version("none") == "none"
    assert version("latest") == "latest"


def test_bump_accepts_the_four_words():
    assert bump("MINOR") == "minor"
    assert bump("none") == "none"
    assert bump("nope") == ""


def test_a_finding_forces_the_bad_status():
    label, rows = status(
        {"status": "pass", "findings": [{"filename": "README.md", "finding": "missing"}]},
        "pass",
        "fail",
    )
    assert label == "fail"
    assert rows == [{"filename": "README.md", "finding": "missing"}]
    assert status({"status": "ready", "findings": ["nope", {"finding": "  "}]}, "ready", "not ready") == (
        "ready",
        [],
    )
    assert status({"status": "maybe"}, "pass", "fail") == ("fail", [])
    assert findings({"findings": [{"finding": "public"}]}) == [{"filename": "module", "finding": "public"}]


def test_none_bump_clears_the_suggested_version():
    assert released("not ready", [], "v9.9.9", "none", "v1.0.0")["suggested_version"] == "none"


def test_no_changes_ignores_a_missing_compare():
    assert no_changes("status: identical\nno changes") is True
    assert no_changes("no changes\ncompare not found: v1...latest") is False


def test_apply_files_keeps_order_skips_the_empty_release_and_caps_at_ten():
    names = [f"file{index}.tf" for index in range(11)]
    chosen, skipped = apply_files(
        {
            "interface_findings": [{"filename": "README.md", "finding": "missing variable"}],
            "security_findings": [{"filename": name, "finding": f"HIGH {name}"} for name in names],
            "release_findings": [
                {"filename": "CHANGELOG.md", "finding": "Nothing new to release since v1.0.0."}
            ],
        }
    )
    assert chosen[0] == "README.md"
    assert "CHANGELOG.md" not in chosen
    assert len(chosen) == 10
    assert skipped == ["file9.tf", "file10.tf"]


def test_kept_files_drops_unknown_and_blank_text():
    files, missing = kept_files(
        {
            "proposed_files": [
                {"filename": "README.md", "content": "# Readme\n"},
                {"filename": "notes.md", "content": "nope\n"},
                {"filename": "main.tf", "content": "  "},
            ]
        },
        ["README.md", "main.tf"],
    )
    assert files == [{"filename": "README.md", "content": "# Readme\n"}]
    assert missing == ["main.tf"]


def test_recommend_text_asks_again_only_for_the_files_left_out():
    state = {
        "repo": "acme/mod",
        "ref": "latest",
        "interface_findings": [{"filename": "README.md", "finding": "missing variable"}],
        "security_findings": [{"filename": "main.tf", "finding": "HIGH public bucket"}],
    }
    again = recommend_text(state, ["README.md", "main.tf"], [], ["main.tf"])
    assert "left out of proposed_files" in again
    assert "main.tf" in again
    assert "README.md" not in again.split("proposed_files:")[-1]
    assert "Do not read any other file." not in again

    first = recommend_text(state, ["README.md"], ["file10.tf"], None)
    assert "Call read_pr_template once" in first
    assert ".github/PULL_REQUEST_TEMPLATE.md" in first
    assert "file10.tf" in first


def test_security_lines_and_skipped_files_are_appended():
    body = with_security("## Summary\nDone.", [{"filename": "main.tf", "finding": "HIGH public bucket"}])
    assert "main.tf: HIGH public bucket" in body
    assert with_security(body, [{"filename": "main.tf", "finding": "HIGH public bucket"}]) == body
    assert with_security("", [{"filename": "main.tf", "finding": "HIGH public bucket"}]) == ""
    assert with_skipped("## Summary", ["file10.tf"]).endswith("- file10.tf")
    assert with_skipped("", ["file10.tf"]).startswith("More recommendations were not applied:")


def test_pull_version_uses_the_tag_when_there_is_no_bump():
    assert pull_version({"suggested_version": "v1.2.0", "current_version": "v1.0.0"}) == "v1.2.0"
    assert pull_version({"suggested_version": "none", "current_version": "v1.0.0"}) == "v1.0.0"


def test_severity_defaults_to_high(monkeypatch):
    monkeypatch.delenv("TRIVY_SEVERITY", raising=False)
    assert severity() == "HIGH"


def test_severity_reads_the_env(monkeypatch):
    monkeypatch.setenv("TRIVY_SEVERITY", "medium")
    assert severity() == "MEDIUM"


def test_severity_rejects_an_unknown_value(monkeypatch):
    monkeypatch.setenv("TRIVY_SEVERITY", "info")
    assert severity() == "HIGH"
