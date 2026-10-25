from pathlib import Path

from review.reader import FixtureReader
from review.tools.checks import (
    build_interface_tools,
    build_release_tools,
    build_security_tools,
    without_called_diff,
)


def test_terraform_docs_shows_inputs_and_outputs_and_read_file_reads_the_readme():
    reader = FixtureReader(
        files={
            ("latest", "README.md"): "# Original\n",
            ("latest", "variables.tf"): 'variable "name" {}\n',
        }
    )
    seen = []

    def run(argv):
        seen.append(argv)
        readme = Path(argv[-1]) / "README.md"
        readme.write_text("# Modified by the command\n")
        return "generated table"

    (docs, read), answered = build_interface_tools(reader, run=run)
    text = docs.invoke({"ref": "latest"})
    assert seen[0][:5] == ["terraform-docs", "markdown", "table", "--output-file", ""]
    assert seen[0][5:9] == ["--show", "inputs", "--show", "outputs"]
    assert "generated table" in text
    assert "# Original" not in text
    assert "# Modified" not in text
    assert read.invoke({"path": "README.md", "ref": "latest"}) == "# Original\n"
    assert read.invoke({"path": "README.md", "ref": "latest"}) == (
        "Already returned. Use the first result and answer. Do not call this tool again."
    )
    assert read.invoke({"path": "variables.tf", "ref": "latest"}) == "not in this run"
    assert "README.md" in answered


def test_trivy_config_returns_the_full_report():
    reader = FixtureReader(files={("latest", "main.tf"): 'resource "aws_s3_bucket" "this" {}\n'})
    seen = []

    def run(argv):
        seen.append(argv)
        return '{"Results":[{"Misconfigurations":[{"Severity":"LOW"},{"Severity":"HIGH"}]}]}'

    text = build_security_tools(reader, run=run)[0].invoke({"ref": "latest"})
    assert seen[0][:4] == ["trivy", "config", "--format", "json"]
    assert "--quiet" in seen[0]
    assert "LOW" in text
    assert "HIGH" in text


def test_release_tools_read_the_holder():
    held = {
        "release_tags": ["v1.2.0", "v1.0.0"],
        "diff": "ahead assets-rename",
        "changelog": "# Changelog\n\n## 1.3.0\n",
    }
    tag, diff, _read = build_release_tools(held)
    assert tag.invoke({}) == "v1.2.0"
    text = diff.invoke({})
    assert text == "diff\nahead assets-rename"
    assert "CHANGELOG.md" not in text
    assert diff.invoke({}) == "Already returned. Use the first result and answer. Do not call this tool again."
    read = build_release_tools(held)[2]
    assert "## 1.3.0" in read.invoke({"path": "CHANGELOG.md", "ref": "latest"})
    assert read.invoke({"path": "CHANGELOG.md", "ref": "latest"}) == (
        "Already returned. Use the first result and answer. Do not call this tool again."
    )
    assert read.invoke({"path": "README.md", "ref": "latest"}) == "not in this run"
    held["release_tags"] = []
    assert tag.invoke({}) == ""
    again = {key: value for key, value in held.items() if key not in {"diff_read", "read_paths"}}
    fresh_diff, fresh_read = build_release_tools(again)[1:]
    text = fresh_diff.invoke({})
    assert text == "diff\nNo prior release."
    assert "## 1.3.0" in fresh_read.invoke({"path": "CHANGELOG.md", "ref": "latest"})


def test_a_missing_readme_is_final():
    (docs, read), seen = build_interface_tools(FixtureReader())
    assert docs
    text = read.invoke({"path": "README.md", "ref": "latest"})
    assert text == "README.md does not exist at this ref. Do not call read_file again."
    assert read.invoke({"path": "README.md", "ref": "latest"}) == (
        "Already returned. Use the first result and answer. Do not call this tool again."
    )
    assert "README.md" in seen


def test_the_diff_tool_drops_out_after_it_returns():
    diff = type("Tool", (), {"name": "get_diff_since_last_release"})()
    answer = type("Tool", (), {"name": "ReleaseResult"})()
    held = {}
    assert without_called_diff(held, [diff, answer]) == [diff, answer]
    held["diff_read"] = True
    assert without_called_diff(held, [diff, answer]) == [answer]
    read = type("Tool", (), {"name": "read_file"})()
    held["read_paths"] = {"CHANGELOG.md"}
    assert without_called_diff(held, [diff, read, answer]) == [answer]
