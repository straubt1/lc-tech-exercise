from io import StringIO

from review.display import ask_pull_request, make_console, show_pull_request, show_report, show_step


def _console():
    buffer = StringIO()
    return buffer, make_console(file=buffer, force_terminal=False, width=60)


def test_step_line_counts_findings():
    buffer, console = _console()
    show_step(
        console,
        "review",
        {"review_status": "fail", "review_findings": [{}, {}]},
    )
    show_step(
        console,
        "version",
        {"suggested_version": "v1.0.2", "bump": "patch"},
    )
    text = buffer.getvalue()
    assert "fail" in text
    assert "2 findings" in text
    assert "v1.0.2" in text
    assert "patch" in text


def test_report_keeps_literal_brackets_and_hides_file_bodies():
    buffer, console = _console()
    show_report(
        console,
        {
            "review_status": "fail",
            "suggested_version": "v1.0.2",
            "bump": "patch",
            "justification": "Kept at patch.",
            "versions": [
                {"version": "v1.0.1", "published": True, "source": "tag"},
                {"version": "v1.0.2", "published": False, "source": "CHANGELOG.md"},
            ],
            "review_findings": [
                {"filename": "CHANGELOG.md", "finding": "heading is [v1.0.1]"},
            ],
            "version_findings": [],
            "proposed_files": [
                {"filename": "CHANGELOG.md", "content": "FULL BODY SHOULD NOT SHOW"},
                {"filename": "main.tf", "content": "resource"},
            ],
        },
    )
    text = buffer.getvalue()
    assert "fail" in text
    assert "v1.0.2" in text
    assert "published" in text
    assert "unpublished" in text
    assert "[v1.0.1]" in text
    assert "FULL BODY" not in text
    assert "main.tf" not in text
    assert "Kept at patch." in text
    assert "CHANGELOG.md" in text


def _versions(count: int) -> list[dict]:
    return [
        {"version": f"v1.0.{index}", "published": True, "source": "tag"}
        for index in range(count - 1, -1, -1)
    ]


def test_more_than_five_versions_keep_five_and_count_the_rest():
    buffer, console = _console()
    show_report(
        console,
        {
            "review_status": "pass",
            "suggested_version": "v2.0.0",
            "versions": _versions(9),
            "review_findings": [],
            "version_findings": [],
        },
    )
    text = buffer.getvalue()
    for index in range(8, 3, -1):
        assert f"v1.0.{index}" in text
    for index in range(3, -1, -1):
        assert f"v1.0.{index}" not in text
    assert "4 other versions" in text


def test_six_versions_count_the_one_left_out():
    buffer, console = _console()
    show_report(
        console,
        {
            "review_status": "pass",
            "suggested_version": "v2.0.0",
            "versions": _versions(6),
            "review_findings": [],
            "version_findings": [],
        },
    )
    text = buffer.getvalue()
    assert "v1.0.5" in text
    assert "v1.0.1" in text
    assert "v1.0.0" not in text
    assert "1 other version" in text
    assert "other versions" not in text


def test_five_versions_are_listed_without_a_remainder():
    buffer, console = _console()
    show_report(
        console,
        {
            "review_status": "pass",
            "suggested_version": "v2.0.0",
            "versions": _versions(5),
            "review_findings": [],
            "version_findings": [],
        },
    )
    text = buffer.getvalue()
    assert "v1.0.4" in text
    assert "v1.0.0" in text
    assert "other version" not in text


def test_empty_readme_checks_are_left_off_the_report():
    buffer, console = _console()
    show_report(
        console,
        {
            "review_status": "fail",
            "suggested_version": "v1.0.2",
            "versions": [],
            "review_findings": [
                {
                    "filename": "README.md",
                    "finding": (
                        "Inputs, Missing: none. Inputs, Extra: bucket_name. "
                        "Inputs, Wrong: domain (code \"name\" vs README \"name\" matches). "
                        "Outputs, Missing: none. Outputs, Extra: none. "
                        "Outputs, Wrong: id description differs."
                    ),
                }
            ],
            "version_findings": [
                {"filename": "CHANGELOG.md", "finding": "heading is still v1.0.0"},
            ],
        },
    )
    text = buffer.getvalue()
    assert "Inputs, Extra: bucket_name" in text
    assert "Outputs, Wrong: id description differs" in text
    assert "CHANGELOG.md" in text
    assert "heading is still v1.0.0" in text
    assert "Missing" not in text
    assert "Inputs, Wrong" not in text
    assert "matches" not in text


def test_a_readme_with_only_empty_checks_is_skipped():
    buffer, console = _console()
    show_report(
        console,
        {
            "review_status": "fail",
            "suggested_version": "v1.0.2",
            "versions": [],
            "review_findings": [
                {
                    "filename": "README.md",
                    "finding": (
                        "Inputs\n"
                        "- Missing: none\n"
                        "- Extra: none\n"
                        "- Wrong: cloud_armor_tier is fine, but domain "
                        '(code "The domain" vs README "The domain" matches).\n'
                        "Outputs\n"
                        "- Missing: none\n"
                        "- Extra: none\n"
                        "- Wrong: group_email matches.\n"
                    ),
                }
            ],
            "version_findings": [],
        },
    )
    text = buffer.getvalue()
    assert "README.md" not in text
    assert "none" in text


def test_pull_request_preview_shows_the_title_and_line_changes():
    buffer, console = _console()
    show_pull_request(
        console,
        {
            "ref": "latest",
            "suggested_version": "v1.0.2",
            "pr_title": "Document the Bucket Rename for v1.0.2",
            "proposed_files": [
                {
                    "filename": "CHANGELOG.md",
                    "content": "# Changelog\n\n## v1.0.2\n\n- Renamed the bucket.\n\n## v1.0.1\n\n- Initial.\n",
                },
                {"filename": "main.tf", "content": "resource {}\n"},
            ],
        },
        lambda path, ref: "# Changelog\n\n## v1.0.1\n\n- Initial.\n",
    )
    text = buffer.getvalue()
    assert "[Review Agent]" in text
    assert "Document the Bucket Rename" in text
    assert "v1.0.2" in text
    assert "CHANGELOG.md" in text
    assert "+4" in text
    assert "-0" in text
    assert "Renamed the bucket" not in text
    assert "main.tf" not in text


def test_enter_with_no_text_means_no():
    _buffer, console = _console()
    assert ask_pull_request(console, stream=StringIO("\n")) == "no"
