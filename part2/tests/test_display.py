from io import StringIO

from review.display import ask_pull_request, make_console, show_pull_request, show_report, show_step


def _console():
    buffer = StringIO()
    return buffer, make_console(file=buffer, force_terminal=False, width=80)


def test_step_line_counts_findings_and_shows_the_version():
    buffer, console = _console()
    show_step(
        console,
        "interface",
        {"interface_status": "fail", "interface_findings": [{}, {}]},
    )
    show_step(console, "security", {"security_status": "pass", "security_findings": []})
    show_step(
        console,
        "release",
        {
            "release_status": "not ready",
            "current_version": "v1.0.1",
            "suggested_version": "v1.0.2",
            "bump": "patch",
        },
    )
    text = buffer.getvalue()
    assert "fail" in text
    assert "2 findings" in text
    assert "pass" in text
    assert "not ready" in text
    assert "Latest Published Version" in text
    assert "v1.0.1" in text
    assert "Recommended Version" in text
    assert "v1.0.2" in text
    assert "patch" in text


def test_report_keeps_literal_brackets_and_hides_file_bodies():
    buffer, console = _console()
    show_report(
        console,
        {
            "interface_status": "fail",
            "security_status": "fail",
            "release_status": "not ready",
            "current_version": "v1.0.1",
            "suggested_version": "v1.0.2",
            "bump": "patch",
            "interface_findings": [
                {"filename": "README.md", "finding": "heading is [v1.0.1]"},
            ],
            "security_findings": [
                {"filename": "main.tf", "finding": "HIGH public bucket"},
            ],
            "release_findings": [],
            "proposed_files": [
                {"filename": "CHANGELOG.md", "content": "FULL BODY SHOULD NOT SHOW"},
                {"filename": "main.tf", "content": "resource"},
            ],
        },
    )
    text = buffer.getvalue()
    assert "fail" in text
    assert "not ready" in text
    assert "Latest Published Version" in text
    assert "v1.0.1" in text
    assert "Recommended Version" in text
    assert "v1.0.2" in text
    assert "patch" in text
    assert "[v1.0.1]" in text
    assert "HIGH public bucket" in text
    assert "FULL BODY" not in text
    assert "resource" not in text
    assert "main.tf" in text
    assert "CHANGELOG.md" in text


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
    assert "main.tf" in text


def test_enter_with_no_text_means_no():
    _buffer, console = _console()
    assert ask_pull_request(console, stream=StringIO("\n")) == "no"
