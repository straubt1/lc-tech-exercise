from io import StringIO

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.types import Command
from pydantic import Field

from review.agents.interface import SCHEMA as INTERFACE_SCHEMA
from review.agents.recommend import SCHEMA as RECOMMEND_SCHEMA
from review.agents.release import SCHEMA as RELEASE_SCHEMA
from review.agents.security import SCHEMA as SECURITY_SCHEMA
from review.display import follow, make_console, show_report
from review.graph import build_graph
from review.reader import FixtureReader


class ScriptedModel(BaseChatModel):
    interface_status: str = "pass"
    interface_findings: list = Field(default_factory=list)
    security_status: str = "pass"
    security_findings: list = Field(default_factory=list)
    release_status: str = "ready"
    release_findings: list = Field(default_factory=list)
    suggested_version: str = "v1.2.0"
    bump: str = "minor"
    suggestions: str = "No file changes."
    proposed_files: list = Field(default_factory=list)
    pr_title: str = ""
    pr_body: str = ""
    followup_files: list = Field(default_factory=list)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        system = "\n".join(
            message.content
            for message in messages
            if message.type == "system" and isinstance(message.content, str)
        )
        if "interface agent" in system:
            name = INTERFACE_SCHEMA["title"]
            args = {"status": self.interface_status, "findings": self.interface_findings}
        elif "security agent" in system:
            name = SECURITY_SCHEMA["title"]
            args = {"status": self.security_status, "findings": self.security_findings}
        elif "release specialist" in system:
            name = RELEASE_SCHEMA["title"]
            args = {
                "status": self.release_status,
                "suggested_version": self.suggested_version,
                "bump": self.bump,
                "findings": self.release_findings,
            }
        else:
            human = "\n".join(
                message.content
                for message in messages
                if message.type == "human" and isinstance(message.content, str)
            )
            proposed = self.proposed_files
            if self.followup_files and "left out of proposed_files" in human:
                proposed = self.followup_files
            name = RECOMMEND_SCHEMA["title"]
            args = {
                "suggestions": self.suggestions,
                "proposed_files": proposed,
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


def _tool_outputs(messages):
    calls = {}
    outputs = []
    for message in messages:
        if message.type == "ai":
            for call in message.tool_calls or []:
                calls[call["id"]] = call
        if message.type == "tool":
            call = calls[message.tool_call_id]
            outputs.append((call["name"], message.content))
    return outputs


def _tool_message(name, args, call_id):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


class ReleaseToolsModel(ScriptedModel):
    """Calls the release tools, then returns what they said."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        system = "\n".join(
            message.content
            for message in messages
            if message.type == "system" and isinstance(message.content, str)
        )
        if "release specialist" not in system:
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        outputs = dict(_tool_outputs(messages))
        if "get_last_release_tag" not in outputs:
            return ChatResult(
                generations=[
                    ChatGeneration(message=_tool_message("get_last_release_tag", {}, "tag"))
                ]
            )
        if "get_diff_since_last_release" not in outputs:
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=_tool_message("get_diff_since_last_release", {}, "diff")
                    )
                ]
            )
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": RELEASE_SCHEMA["title"],
                    "args": {
                        "status": "not ready",
                        "suggested_version": "v1.1.0",
                        "bump": "minor",
                        "findings": [
                            {
                                "filename": "CHANGELOG.md",
                                "finding": (
                                    f"tag {outputs['get_last_release_tag']} "
                                    f"diff {outputs['get_diff_since_last_release']}"
                                ),
                            }
                        ],
                    },
                    "id": "release-result",
                    "type": "tool_call",
                }
            ],
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


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
    assert "interface_status" not in result
    assert "suggested_version" not in result
    assert "suggestions" not in result
    assert "__interrupt__" not in result


def test_a_tag_lookup_failure_stays_inside_release():
    class Broken(FixtureReader):
        def list_release_tags(self):
            raise RuntimeError("github error 403: rate limit")

    result = _graph(reader=Broken()).invoke(
        {"repo": "acme/mod", "ref": "latest", "pr_url": ""},
        {"configurable": {"thread_id": "tag-error"}},
    )
    assert "error" not in result
    assert result["interface_status"] == "pass"
    assert result["security_status"] == "pass"
    assert result["release_status"] == "not ready"
    assert result["release_findings"] == [
        {"filename": "CHANGELOG.md", "finding": "github error 403: rate limit"}
    ]


def test_a_blank_repo_stops_before_the_agents():
    result = _graph().invoke(
        {"repo": " ", "ref": "latest", "pr_url": ""},
        {"configurable": {"thread_id": "blank-repo"}},
    )
    assert result["error"] == "repo is required"
    assert "suggested_version" not in result


def test_tags_are_loaded_once_and_the_diff_uses_the_latest():
    class Counting(FixtureReader):
        def __init__(self):
            super().__init__(
                tags=["v1.2.0", "v1.0.0"],
                compares={("v1.2.0", "latest"): "status: ahead\nahead_by: 1\n"},
            )
            self.tag_calls = 0
            self.compare_calls = []

        def list_release_tags(self):
            self.tag_calls += 1
            return super().list_release_tags()

        def compare(self, base, head):
            self.compare_calls.append((base, head))
            return super().compare(base, head)

    reader = Counting()
    paused = _graph(reader=reader).invoke(
        {"repo": "fixture/mod", "ref": "latest", "pr_url": ""},
        {"configurable": {"thread_id": "one-tag-call"}},
    )
    assert reader.tag_calls == 1
    assert reader.compare_calls == [("v1.2.0", "latest")]
    assert "release_tags" not in paused
    assert "diff" not in paused


def test_no_changes_is_not_ready_and_stays_on_the_tag():
    class Guard(ScriptedModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            system = "\n".join(
                message.content
                for message in messages
                if message.type == "system" and isinstance(message.content, str)
            )
            if "release specialist" in system:
                raise AssertionError("release model called")
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    reader = FixtureReader(
        tags=["v1.2.3-rc1", "v1.0.0"],
        compares={("v1.2.3-rc1", "latest"): "status: identical\nahead_by: 0\nno changes"},
    )
    paused = _graph(Guard(), reader).invoke(
        {"repo": "fixture/mod", "ref": "latest", "pr_url": ""},
        {"configurable": {"thread_id": "no-changes"}},
    )
    assert paused["release_status"] == "not ready"
    assert paused["current_version"] == "v1.2.3-rc1"
    assert paused["suggested_version"] == "none"
    assert paused["bump"] == "none"
    assert paused["release_findings"] == [
        {"filename": "CHANGELOG.md", "finding": "Nothing new to release since v1.2.3-rc1."}
    ]
    assert paused["interface_status"] == "pass"
    assert paused["security_status"] == "pass"


def test_release_tools_read_the_loaded_tag_and_diff():
    diff = "status: ahead\nahead_by: 1\nassets-rename\n"
    reader = FixtureReader(
        tags=["v1.2.0", "v1.0.0"],
        compares={("v1.2.0", "latest"): diff},
        files={("latest", "CHANGELOG.md"): "# Changelog\n\n## 1.3.0\n"},
    )
    paused = _graph(ReleaseToolsModel(), reader).invoke(
        {"repo": "fixture/mod", "ref": "latest", "pr_url": ""},
        {"configurable": {"thread_id": "release-tools"}},
    )
    assert paused["release_status"] == "not ready"
    assert paused["suggested_version"] == "v1.1.0"
    finding = paused["release_findings"][0]["finding"]
    assert "tag v1.2.0" in finding
    assert "assets-rename" in finding
    assert "## 1.3.0" in finding
    assert "changelog" not in paused


def test_follow_prints_each_check_once():
    app = _graph()
    config = {"configurable": {"thread_id": "display-once"}}
    buffer = StringIO()
    console = make_console(file=buffer, force_terminal=False, width=80)
    follow(
        app,
        {"repo": "fixture/mod", "ref": "latest", "pr_url": ""},
        config,
        console,
        status="interface, security, and release",
        steps=True,
    )
    assert app.get_state(config).interrupts
    show_report(console, app.get_state(config).values)
    report = buffer.getvalue()
    assert "interface" in report
    assert "security" in report
    assert "ready" in report
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

    assert paused["interface_status"] == "pass"
    assert paused["security_status"] == "pass"
    assert paused["release_status"] == "ready"
    assert paused["suggested_version"] == "v1.2.0"
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
        interface_status="fail",
        interface_findings=[{"filename": "README.md", "finding": "missing variable force_destroy"}],
        security_findings=[{"filename": "main.tf", "finding": "HIGH public bucket"}],
        suggested_version="v1.2.0",
        suggestions="Update the readme for v1.2.0.",
        pr_title="Document the Missing Variable for v1.2.0",
        pr_body="## Summary\nThe readme omits force_destroy.\n",
        proposed_files=[
            {"filename": "README.md", "content": "# Readme\n"},
            {"filename": "CHANGELOG.md", "content": "# Changelog\n"},
            {"filename": "main.tf", "content": "resource {}\n"},
            {"filename": "notes.md", "content": "nope\n"},
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
        "main.tf",
    ]
    assert "Interface: fail" in call["status"]
    assert "Release: ready" in call["status"]
    assert any(item["filename"] == "README.md" for item in call["findings"])
    assert any(item["filename"] == "main.tf" for item in call["findings"])
    assert call["title"] == "Document the Missing Variable for v1.2.0"
    assert "force_destroy" in call["body"]
    assert "main.tf: HIGH public bucket" in call["body"]


def test_only_the_first_ten_finding_files_are_committed():
    calls = []

    def opener(**kwargs):
        calls.append(kwargs)
        return "https://github.com/example/pull/2"

    names = [f"file{index}.tf" for index in range(11)]
    model = ScriptedModel(
        security_findings=[{"filename": name, "finding": f"HIGH {name}"} for name in names],
        proposed_files=[{"filename": name, "content": f"# {name}\n"} for name in names],
        pr_body="## Summary\nFixes.\n",
    )
    app = _graph(model, open_pr=opener)
    config = {"configurable": {"thread_id": "cap"}}
    app.invoke({"repo": "fixture/mod", "ref": "latest", "pr_url": ""}, config)
    app.invoke(Command(resume="yes"), config)

    call = calls[0]
    assert [item["filename"] for item in call["proposed_files"]] == names[:10]
    assert "More recommendations were not applied:" in call["body"]
    assert "file10.tf" in call["body"]


def test_a_file_left_out_of_the_first_reply_is_requested_again():
    calls = []

    def opener(**kwargs):
        calls.append(kwargs)
        return "https://github.com/example/pull/3"

    model = ScriptedModel(
        interface_findings=[{"filename": "README.md", "finding": "missing variable force_destroy"}],
        security_findings=[{"filename": "main.tf", "finding": "HIGH public bucket"}],
        proposed_files=[{"filename": "README.md", "content": "# Readme\n"}],
        followup_files=[{"filename": "main.tf", "content": "resource {}\n"}],
        pr_title="Block public access for v1.2.0",
        pr_body="## Summary\nBlock public access.\n",
    )
    app = _graph(model, open_pr=opener)
    config = {"configurable": {"thread_id": "retry-main"}}
    paused = app.invoke({"repo": "fixture/mod", "ref": "latest", "pr_url": ""}, config)
    app.invoke(Command(resume="yes"), config)

    assert [item["filename"] for item in paused["proposed_files"]] == ["README.md", "main.tf"]
    assert [item["filename"] for item in calls[0]["proposed_files"]] == ["README.md", "main.tf"]

