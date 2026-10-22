from pathlib import Path

from review.reader import FixtureReader
from review.tools.checks import build_interface_tools, build_release_tools, build_security_tools


def test_terraform_docs_prints_docs_and_keeps_the_readme_text():
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

    text = build_interface_tools(reader, run=run)[0].invoke({"ref": "latest"})
    assert seen[0][:5] == ["terraform-docs", "markdown", "table", "--output-file", ""]
    assert "generated table" in text
    assert "# Original" in text
    assert "# Modified" not in text


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
    held = {"release_tags": ["v1.2.0", "v1.0.0"], "diff": "ahead assets-rename"}
    tag, diff = build_release_tools(held)
    assert tag.invoke({}) == "v1.2.0"
    assert diff.invoke({}) == "ahead assets-rename"
    held["release_tags"] = []
    assert tag.invoke({}) == ""
    assert diff.invoke({}) == "No prior release."
