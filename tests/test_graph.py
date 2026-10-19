import re

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.types import Command
from pydantic import Field

from review.agents.recommend import SCHEMA as RECOMMEND_SCHEMA
from review.agents.review import SCHEMA as REVIEW_SCHEMA
from review.agents.version import SCHEMA as VERSION_SCHEMA
from review.agents.version import apply_bump
from review.graph import build_graph
from review.reader import FixtureReader

_VERSION = re.compile(r"(?:^|[^0-9])v?(\d+\.\d+\.\d+)\b")
_VARIABLE = re.compile(r'variable\s+"([^"]+)"', re.S)
_OUTPUT = re.compile(r'output\s+"([^"]+)"', re.S)


class ScriptedModel(BaseChatModel):
    review_status: str = "pass"
    review_findings: list = Field(default_factory=list)
    suggested_version: str = "v1.2.0"
    versions: list = Field(
        default_factory=lambda: [
            {"version": "v1.2.0", "published": True, "source": "tag"}
        ]
    )
    version_findings: list = Field(default_factory=list)
    suggestions: str = "No file changes."
    proposed_files: list = Field(default_factory=list)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        system = "\n".join(
            message.content
            for message in messages
            if message.type == "system" and isinstance(message.content, str)
        )
        if "review agent" in system:
            name = REVIEW_SCHEMA["title"]
            args = {"status": self.review_status, "findings": self.review_findings}
        elif "version agent" in system:
            name = VERSION_SCHEMA["title"]
            args = {
                "suggested_version": self.suggested_version,
                "versions": self.versions,
                "findings": self.version_findings,
            }
        else:
            name = RECOMMEND_SCHEMA["title"]
            args = {
                "suggestions": self.suggestions,
                "proposed_files": self.proposed_files,
            }
        message = AIMessage(
            content="",
            tool_calls=[{"name": name, "args": args, "id": name, "type": "tool_call"}],
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self) -> str:
        return "scripted"


class ReadingModel(BaseChatModel):
    """Calls the reader tools, then applies the fixture rules."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        system = "\n".join(
            message.content
            for message in messages
            if message.type == "system" and isinstance(message.content, str)
        )
        outputs = _tool_outputs(messages)
        if "review agent" in system or "version agent" in system:
            human = "\n".join(
                message.content
                for message in messages
                if message.type == "human" and isinstance(message.content, str)
            )
            ref = human.split("ref ", 1)[1].split(".", 1)[0].strip()
            if "review agent" in system:
                return _review_turn(ref, outputs)
            return _version_turn(ref, outputs)
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": RECOMMEND_SCHEMA["title"],
                    "args": {"suggestions": "See findings.", "proposed_files": []},
                    "id": "recommend",
                    "type": "tool_call",
                }
            ],
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self) -> str:
        return "reading"


def _tool_outputs(messages):
    calls = {}
    outputs = []
    for message in messages:
        if message.type == "ai":
            for call in message.tool_calls or []:
                calls[call["id"]] = call
        if message.type == "tool":
            call = calls[message.tool_call_id]
            outputs.append((call["name"], call["args"], message.content))
    return outputs


def _tool_message(name, args, call_id):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


def _review_turn(ref, outputs):
    files = {args["path"]: content for name, args, content in outputs if name == "read_file"}
    needed = ["variables.tf", "outputs.tf", "README.md", "CHANGELOG.md"]
    missing = [path for path in needed if path not in files]
    if missing:
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "read_file",
                    "args": {"path": path, "ref": ref},
                    "id": f"read-{path}",
                    "type": "tool_call",
                }
                for path in missing
            ],
        )
        return ChatResult(generations=[ChatGeneration(message=message)])
    readme = files["README.md"]
    findings = []
    for name in _VARIABLE.findall(files["variables.tf"]):
        if name not in readme:
            findings.append({"filename": "README.md", "finding": f"missing variable {name}"})
    for name in _OUTPUT.findall(files["outputs.tf"]):
        if name not in readme:
            findings.append({"filename": "README.md", "finding": f"missing output {name}"})
    message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": REVIEW_SCHEMA["title"],
                "args": {"status": "fail" if findings else "pass", "findings": findings},
                "id": "review-result",
                "type": "tool_call",
            }
        ],
    )
    return ChatResult(generations=[ChatGeneration(message=message)])


def _versions_in_diff(text):
    places = {}
    current = ""
    for line in text.splitlines():
        if line.startswith("--- "):
            current = line[4:].strip()
        if not current:
            continue
        for match in _VERSION.findall(line):
            places.setdefault(f"v{match}", []).append(current)
    return places


def _version_turn(ref, outputs):
    names = {name for name, _args, _content in outputs}
    if "list_release_tags" not in names:
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=_tool_message("list_release_tags", {}, "tags")
                )
            ]
        )

    tags = []
    compared = None
    for name, _args, content in outputs:
        if name == "list_release_tags":
            tags = _parse_tags(content)
        elif name == "compare":
            compared = content
    highest = tags[0] if tags else ""
    if highest and compared is None:
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=_tool_message(
                        "compare",
                        {"base": highest, "head": ref},
                        "compare",
                    )
                )
            ]
        )

    places = {}
    for version, sources in _versions_in_diff(compared or "").items():
        places.setdefault(version, []).extend(sources)
    for tag in tags:
        places.setdefault(tag, []).append("tag")
    versions = []
    for version in sorted(places):
        sources = places[version]
        published = "tag" in sources
        ordered = [item for item in ("tag", "CHANGELOG.md", "README.md") if item in sources]
        versions.append(
            {"version": version, "published": published, "source": ", ".join(ordered)}
        )
    suggested = _suggest(highest, compared or "")
    message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": VERSION_SCHEMA["title"],
                "args": {
                    "suggested_version": suggested,
                    "versions": versions,
                    "findings": [],
                },
                "id": "version-result",
                "type": "tool_call",
            }
        ],
    )
    return ChatResult(generations=[ChatGeneration(message=message)])


def _parse_tags(content):
    if isinstance(content, list):
        return content
    return re.findall(r"v\d+\.\d+\.\d+", content)


def _suggest(highest, compare):
    if not highest:
        return "v1.0.0"
    if "no changes" in compare:
        return highest
    major, minor, patch = (int(part) for part in highest[1:].split("."))
    if "required variable" in compare or "output renamed" in compare:
        return f"v{major + 1}.0.0"
    if "optional variable" in compare or "new output" in compare:
        return f"v{major}.{minor + 1}.0"
    if "behavior fix" in compare:
        return f"v{major}.{minor}.{patch + 1}"
    return highest


def _graph(model=None, reader=None, open_pr=None):
    kwargs = {}
    if open_pr is not None:
        kwargs["open_pr"] = open_pr
    return build_graph(model or ScriptedModel(), reader or FixtureReader(), **kwargs)


def _interrupt(result):
    return result["__interrupt__"][0].value


def test_trace_name():
    assert _graph().name == "module_review"


def test_a_missing_ref_stops_before_the_agents():
    class Missing(FixtureReader):
        def check(self, repo: str, ref: str) -> str:
            return f"not found: {repo}@{ref}"

    result = _graph(reader=Missing()).invoke(
        {"repo": "acme/mod", "ref": "missing", "pr_url": ""},
        {"configurable": {"thread_id": "missing"}},
    )
    assert result["error"] == "not found: acme/mod@missing"
    assert "review_status" not in result
    assert "suggested_version" not in result
    assert "suggestions" not in result
    assert "__interrupt__" not in result


def test_a_blank_repo_stops_before_the_agents():
    result = _graph().invoke(
        {"repo": " ", "ref": "latest", "pr_url": ""},
        {"configurable": {"thread_id": "blank-repo"}},
    )
    assert result["error"] == "repo is required"
    assert "suggested_version" not in result


def test_changes_after_a_published_tag_bump_patch():
    diff = """status: ahead
ahead_by: 1
files:
- main.tf (modified)

--- main.tf
-  bucket = "${var.name_prefix}-${var.environment}-assets"
+  bucket = "${var.name_prefix}-${var.environment}-assets-rename"
"""
    reader = FixtureReader(tags=["v1.0.1", "v1.0.0"], compares={("v1.0.1", "latest"): diff})
    paused = _graph(
        ScriptedModel(
            suggested_version="v1.0.1",
            versions=[{"version": "v1.0.1", "published": True, "source": "tag"}],
        ),
        reader,
    ).invoke(
        {"repo": "fixture/mod", "ref": "latest", "pr_url": ""},
        {"configurable": {"thread_id": "bump-patch"}},
    )
    assert paused["suggested_version"] == "v1.0.2"
    assert paused["bump"] == "patch"
    assert paused["justification"].startswith("Patch bump from v1.0.1 to v1.0.2")
    assert "main.tf" in paused["justification"]
    assert "assets-rename" in paused["justification"]


def test_apply_bump_uses_the_model_choice_inside_the_hard_band():
    version, bump, reason = apply_bump(
        "minor",
        "Minor: new optional variable.",
        "v1.0.0",
        "optional variable",
    )
    assert (version, bump, reason) == ("v1.1.0", "minor", "Minor: new optional variable.")
    version, bump, reason = apply_bump(
        "patch",
        "treat it as a patch",
        "v1.0.0",
        '--- outputs.tf\n-output "bucket_id" {\n+output "bucket_arn" {\n',
    )
    assert version == "v1.1.0"
    assert bump == "minor"
    version, bump, reason = apply_bump(
        "major",
        "Major: callers must rebuild after the output rename.",
        "v1.0.0",
        '--- outputs.tf\n-output "bucket_id" {\n+output "bucket_arn" {\n',
    )
    assert (version, bump) == ("v2.0.0", "major")
    assert reason.startswith("Major:")


def test_review_copies_the_ref():
    class Counting(FixtureReader):
        def __init__(self):
            super().__init__()
            self.refs = []

        def copy_repo(self, ref):
            self.refs.append(ref)
            return super().copy_repo(ref)

    reader = Counting()
    _graph(reader=reader).invoke(
        {"repo": "fixture/mod", "ref": "latest", "pr_url": ""},
        {"configurable": {"thread_id": "copy"}},
    )
    assert reader.refs == ["latest"]


def test_findings_force_a_fail():
    app = _graph(
        ScriptedModel(
            review_status="pass",
            review_findings=[{"filename": "README.md", "finding": "missing variable"}],
        )
    )
    paused = app.invoke(
        {"repo": "fixture/mod", "ref": "latest", "pr_url": ""},
        {"configurable": {"thread_id": "fail"}},
    )
    assert paused["review_status"] == "fail"
    assert paused["review_findings"][0]["filename"] == "README.md"


def test_a_note_that_is_not_a_finding_is_dropped():
    app = _graph(
        ScriptedModel(
            review_findings=[
                {
                    "filename": "CHANGELOG.md",
                    "finding": "The 2.0.0 heading matches the bump, so this is not a finding.",
                }
            ],
            version_findings=[
                {
                    "filename": "CHANGELOG.md",
                    "finding": "Unreleased describes the diff, so this is not a mismatch.",
                },
                {
                    "filename": "README.md",
                    "finding": "README has no version string.",
                },
            ],
        )
    )
    paused = app.invoke(
        {"repo": "fixture/mod", "ref": "latest", "pr_url": ""},
        {"configurable": {"thread_id": "drop"}},
    )
    assert paused["review_findings"] == []
    assert paused["version_findings"] == []
    assert paused["review_status"] == "pass"


def test_a_version_finding_fails_the_review():
    app = _graph(
        ScriptedModel(
            review_status="pass",
            version_findings=[
                {"filename": "CHANGELOG.md", "finding": "heading is still v1.0.0"}
            ],
        )
    )
    paused = app.invoke(
        {"repo": "fixture/mod", "ref": "latest", "pr_url": ""},
        {"configurable": {"thread_id": "version-fail"}},
    )
    assert paused["review_status"] == "fail"
    assert paused["version_findings"][0]["filename"] == "CHANGELOG.md"


def test_no_exits_without_a_pull_request():
    def opener(**_kwargs):
        raise AssertionError("opener called")

    app = _graph(open_pr=opener)
    config = {"configurable": {"thread_id": "no"}}
    paused = app.invoke({"repo": "fixture/mod", "ref": "latest", "pr_url": ""}, config)

    assert paused["review_status"] == "pass"
    assert paused["review_findings"] == []
    assert paused["suggested_version"] == "v1.2.0"
    assert paused["versions"] == [
        {"version": "v1.2.0", "published": True, "source": "tag"}
    ]
    payload = _interrupt(paused)
    assert payload["question"] == "Create a pull request with these suggestions? (yes/no)"
    assert payload["suggestions"] == "No file changes."

    finished = app.invoke(Command(resume="no"), config)
    assert finished["decision"] == "no"
    assert finished["pr_url"] == ""
    assert "__interrupt__" not in finished


def test_yes_with_no_files_does_not_open_a_pull_request():
    def opener(**_kwargs):
        raise AssertionError("opener called")

    app = _graph(open_pr=opener)
    config = {"configurable": {"thread_id": "yes-empty"}}
    app.invoke({"repo": "fixture/mod", "ref": "latest", "pr_url": ""}, config)
    finished = app.invoke(Command(resume="yes"), config)

    assert finished["decision"] == "yes"
    assert finished["pr_url"] == ""
    assert finished["proposed_files"] == []


def test_yes_opens_a_pull_request_for_docs_only():
    calls = []

    def opener(**kwargs):
        calls.append(kwargs)
        return "https://github.com/example/pull/1"

    model = ScriptedModel(
        review_status="fail",
        review_findings=[{"filename": "README.md", "finding": "missing variable force_destroy"}],
        suggested_version="v1.2.0",
        suggestions="Update the readme for v1.2.0.",
        proposed_files=[
            {"filename": "README.md", "content": "# Readme\n"},
            {"filename": "CHANGELOG.md", "content": "# Changelog\n"},
            {"filename": "main.tf", "content": "resource {}\n"},
        ],
    )
    app = _graph(model, open_pr=opener)
    config = {"configurable": {"thread_id": "yes-pr"}}
    app.invoke({"repo": "fixture/mod", "ref": "latest", "pr_url": ""}, config)
    finished = app.invoke(Command(resume="yes"), config)

    assert finished["decision"] == "yes"
    assert finished["pr_url"] == "https://github.com/example/pull/1"
    assert len(calls) == 1
    call = calls[0]
    assert call["base"] == "latest"
    assert call["suggested_version"] == "v1.2.0"
    assert [item["filename"] for item in call["proposed_files"]] == [
        "README.md",
        "CHANGELOG.md",
    ]
    assert "fail" in call["review_status"]
    assert "v1.2.0" in call["suggested_version"]
    assert any(item["filename"] == "README.md" for item in call["findings"])


def _module_files(readme, changelog, variables):
    outputs = 'output "bucket_id" {\n  description = "ID of the bucket."\n  value = aws_s3_bucket.this.id\n}\n'
    return {
        ("latest", "README.md"): readme,
        ("latest", "CHANGELOG.md"): changelog,
        ("latest", "variables.tf"): variables,
        ("latest", "outputs.tf"): outputs,
    }


def test_passing_module_keeps_the_published_tag():
    readme = "# Object storage\n\nbucket_name\nbucket_id\nversion 1.0.0\n"
    changelog = "# Changelog\n\n## 1.0.0\n\n- Initial bucket module.\n"
    variables = 'variable "bucket_name" {\n  description = "Name of the bucket."\n  type = string\n}\n'
    reader = FixtureReader(
        files=_module_files(readme, changelog, variables),
        tags=["v1.0.0"],
        compares={("v1.0.0", "latest"): "status: identical\nahead_by: 0\nno changes"},
    )
    app = _graph(ReadingModel(), reader)
    paused = app.invoke(
        {"repo": "fixture/mod", "ref": "latest", "pr_url": ""},
        {"configurable": {"thread_id": "pass-module"}},
    )
    assert paused["review_status"] == "pass"
    assert paused["review_findings"] == []
    assert paused["suggested_version"] == "v1.0.0"
    published = [item for item in paused["versions"] if item["version"] == "v1.0.0"]
    assert published == [
        {"version": "v1.0.0", "published": True, "source": "tag"}
    ]


def test_missing_readme_variable_and_unpublished_changelog_version():
    readme = "# Object storage\n\nbucket_name\nbucket_id\n"
    changelog = "# Changelog\n\n## 1.3.0\n\n- Noted only here.\n\n## 1.0.0\n\n- Initial bucket module.\n"
    variables = (
        'variable "bucket_name" {\n  description = "Name of the bucket."\n  type = string\n}\n\n'
        'variable "force_destroy" {\n  description = "Destroy the bucket."\n  type = bool\n  default = false\n}\n'
    )
    reader = FixtureReader(
        files=_module_files(readme, changelog, variables),
        tags=["v1.0.0"],
        compares={
            ("v1.0.0", "latest"): "optional variable force_destroy added\n\n--- CHANGELOG.md\n## 1.3.0\n- Noted only here.\n"
        },
    )
    app = _graph(ReadingModel(), reader)
    paused = app.invoke(
        {"repo": "fixture/mod", "ref": "latest", "pr_url": ""},
        {"configurable": {"thread_id": "stale-readme"}},
    )
    assert paused["review_status"] == "fail"
    assert any(item["filename"] == "README.md" for item in paused["review_findings"])
    assert paused["suggested_version"] == "v1.1.0"
    unpublished = [item for item in paused["versions"] if item["version"] == "v1.3.0"]
    assert unpublished == [
        {"version": "v1.3.0", "published": False, "source": "CHANGELOG.md"}
    ]
