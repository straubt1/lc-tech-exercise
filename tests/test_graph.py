import re
from io import StringIO

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.types import Command
from pydantic import Field

from review.agents.recommend import SCHEMA as RECOMMEND_SCHEMA
from review.agents.review import SCHEMA as REVIEW_SCHEMA
from review.agents.version import SCHEMA as VERSION_SCHEMA
from review.agents.version import apply_bump
from review.display import follow, make_console, show_report
from review.graph import build_graph
from review.reader import FixtureReader

_VERSION = re.compile(r"(?:^|[^0-9])v?(\d+\.\d+\.\d+)\b")


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
    pr_title: str = ""
    pr_body: str = ""

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
                "pr_title": self.pr_title,
                "pr_body": self.pr_body,
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
            return _version_turn(human)
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": RECOMMEND_SCHEMA["title"],
                    "args": {
                        "suggestions": "See findings.",
                        "proposed_files": [],
                        "pr_title": "",
                        "pr_body": "",
                    },
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
    text = ""
    for name, _args, content in outputs:
        if name == "read_interface":
            text = content
    if not text:
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=_tool_message("read_interface", {"ref": ref}, "interface")
                )
            ]
        )
    terraform = text.split("\nreadme inputs\n", 1)[0]
    inputs = _interface_section(text, "readme inputs")
    readme_outputs = _interface_section(text, "readme outputs")
    readme = inputs + "\n" + readme_outputs
    findings = []
    for name in re.findall(r'variable\s+"([^"]+)"', terraform):
        if name not in readme:
            findings.append({"filename": "README.md", "finding": f"missing variable {name}"})
    for name in re.findall(r'output\s+"([^"]+)"', terraform):
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


def _interface_section(text: str, title: str) -> str:
    marker = f"\n{title}\n"
    start = text.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    rest = text[start:]
    ends = [
        index
        for index in (
            rest.find("\nvariables\n"),
            rest.find("\noutputs\n"),
            rest.find("\nreadme inputs\n"),
            rest.find("\nreadme outputs\n"),
            rest.find("\nchangelog top\n"),
        )
        if index >= 0
    ]
    end = min(ends) if ends else len(rest)
    return rest[:end]


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


def _brief_parts(human: str) -> tuple[list[str], str]:
    tags = []
    diff = []
    mode = ""
    for line in human.splitlines():
        if line == "Published versions:":
            mode = "tags"
            continue
        if line.startswith("Latest published version:"):
            mode = ""
            continue
        if line == "Diff:":
            mode = "diff"
            continue
        if line == "Return bump, justification, versions, and findings.":
            break
        if mode == "tags" and line:
            tags.append(line)
        elif mode == "diff":
            diff.append(line)
    return tags, "\n".join(diff)


def _version_turn(human):
    tags, compared = _brief_parts(human)
    highest = tags[0] if tags else ""
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
        def __init__(self):
            super().__init__(tags=["v1.0.0"])
            self.tag_calls = 0

        def check(self, repo: str, ref: str) -> str:
            return f"not found: {repo}@{ref}"

        def list_release_tags(self):
            self.tag_calls += 1
            return super().list_release_tags()

    reader = Missing()
    result = _graph(reader=reader).invoke(
        {"repo": "acme/mod", "ref": "missing", "pr_url": ""},
        {"configurable": {"thread_id": "missing"}},
    )
    assert result["error"] == "not found: acme/mod@missing"
    assert reader.tag_calls == 0
    assert "release_tags" not in result
    assert "review_status" not in result
    assert "suggested_version" not in result
    assert "suggestions" not in result
    assert "__interrupt__" not in result


def test_a_tag_lookup_failure_stops_before_the_agents():
    class Broken(FixtureReader):
        def list_release_tags(self):
            raise RuntimeError("github error 403: rate limit")

    result = _graph(reader=Broken()).invoke(
        {"repo": "acme/mod", "ref": "latest", "pr_url": ""},
        {"configurable": {"thread_id": "tag-error"}},
    )
    assert result["error"] == "github error 403: rate limit"
    assert "release_tags" not in result
    assert "review_status" not in result


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
    version, bump, _reason = apply_bump(
        "patch",
        "Patch: small fix after the beta.",
        "1.2.3-beta",
        "behavior fix",
    )
    assert (version, bump) == ("v1.2.4", "patch")
    assert apply_bump("patch", "", "0.9.0", "no changes")[0] == "0.9.0"


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


def test_a_version_response_without_versions_stays_empty():
    class OmitVersions(ScriptedModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            for call in result.generations[0].message.tool_calls:
                if call["name"] == VERSION_SCHEMA["title"]:
                    call["args"].pop("versions", None)
            return result

    paused = _graph(OmitVersions()).invoke(
        {"repo": "fixture/mod", "ref": "latest", "pr_url": ""},
        {"configurable": {"thread_id": "omit-versions"}},
    )
    assert paused["versions"] == []
    assert paused["suggested_version"] == "v1.2.0"


def test_version_fetches_tags_once_and_compares_the_latest():
    class Counting(FixtureReader):
        def __init__(self):
            super().__init__(
                tags=["v1.2.0", "v1.0.0"],
                compares={("v1.2.0", "latest"): "no changes"},
            )
            self.tag_calls = 0
            self.compare_calls = []

        def list_release_tags(self):
            self.tag_calls += 1
            return super().list_release_tags()

        def compare(self, base, head):
            self.compare_calls.append((base, head))
            return super().compare(base, head)

    seen = []

    class Recording(ScriptedModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            system = "\n".join(
                message.content
                for message in messages
                if message.type == "system" and isinstance(message.content, str)
            )
            if "version agent" in system:
                seen.append(
                    "\n".join(
                        message.content
                        for message in messages
                        if message.type == "human" and isinstance(message.content, str)
                    )
                )
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    reader = Counting()
    paused = _graph(Recording(), reader).invoke(
        {"repo": "fixture/mod", "ref": "latest", "pr_url": ""},
        {"configurable": {"thread_id": "one-tag-call"}},
    )
    assert reader.tag_calls == 1
    assert reader.compare_calls == [("v1.2.0", "latest")]
    assert paused["release_tags"] == ["v1.2.0", "v1.0.0"]
    published = seen[0].split("Published versions:\n", 1)[1].split("\nLatest", 1)[0]
    assert published == "v1.2.0\nv1.0.0"
    assert "Latest published version: v1.2.0" in seen[0]
    assert paused["versions"] == [
        {"version": "v1.2.0", "published": True, "source": "tag"},
        {"version": "v1.0.0", "published": True, "source": "tag"},
    ]


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


def test_follow_prints_each_agent_once_and_skips_the_prose_blob():
    app = _graph()
    config = {"configurable": {"thread_id": "display-once"}}
    buffer = StringIO()
    console = make_console(file=buffer, force_terminal=False, width=80)
    follow(
        app,
        {"repo": "fixture/mod", "ref": "latest", "pr_url": ""},
        config,
        console,
        status="review and version",
        steps=True,
    )
    assert app.get_state(config).interrupts
    show_report(console, app.get_state(config).values)
    report = buffer.getvalue()
    assert "pass" in report
    assert "v1.2.0" in report
    assert "No file changes." not in report
    follow(app, Command(resume="no"), config, console)
    assert buffer.getvalue().count("v1.2.0") == report.count("v1.2.0")


def test_no_exits_without_a_pull_request(capsys):
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
    assert "No file changes." not in capsys.readouterr().out


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
        pr_title="Document the Missing Variable for v1.2.0",
        pr_body="## Summary\nThe readme omits force_destroy.\n",
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
    assert call["title"] == "Document the Missing Variable for v1.2.0"
    assert "force_destroy" in call["body"]


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
