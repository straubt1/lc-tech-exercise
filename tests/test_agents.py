import pytest
from langchain.tools import tool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from review.agents import read_prompt
from review.agents.interface import SCHEMA as INTERFACE_SCHEMA
from review.agents.interface import build as build_interface
from review.agents.recommend import SCHEMA as RECOMMEND_SCHEMA
from review.agents.recommend import build as build_recommend
from review.agents.release import SCHEMA as RELEASE_SCHEMA
from review.agents.release import build as build_release
from review.agents.security import SCHEMA as SECURITY_SCHEMA
from review.agents.security import build as build_security

calls: list[str] = []


class Once(BaseChatModel):
    schema_name: str
    payload: dict
    seen: dict = Field(default_factory=dict)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if "system" not in self.seen:
            self.seen["system"] = "\n".join(
                message.content
                for message in messages
                if message.type == "system" and isinstance(message.content, str)
            )
            message = AIMessage(
                content="",
                tool_calls=[
                    {"name": "probe", "args": {"ref": "latest"}, "id": "probe-1", "type": "tool_call"}
                ],
            )
            return ChatResult(generations=[ChatGeneration(message=message)])
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": self.schema_name,
                    "args": self.payload,
                    "id": self.schema_name,
                    "type": "tool_call",
                }
            ],
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, **kwargs):
        self.seen["tools"] = [item.name for item in tools]
        return self

    @property
    def _llm_type(self) -> str:
        return "once"


@tool
def probe(ref: str) -> str:
    """Return a fixed string so the agent can be exercised without a real tool."""
    calls.append(ref)
    return f"probe {ref}"


@pytest.mark.parametrize(
    ("build", "schema", "filename", "payload"),
    [
        (
            build_interface,
            INTERFACE_SCHEMA,
            "interface.md",
            {"status": "pass", "findings": []},
        ),
        (
            build_security,
            SECURITY_SCHEMA,
            "security.md",
            {"status": "fail", "findings": [{"filename": "main.tf", "finding": "HIGH public"}]},
        ),
        (
            build_release,
            RELEASE_SCHEMA,
            "release.md",
            {
                "status": "ready",
                "suggested_version": "v1.2.0",
                "bump": "minor",
                "findings": [],
            },
        ),
        (
            build_recommend,
            RECOMMEND_SCHEMA,
            "recommend.md",
            {
                "suggestions": "Update the readme.",
                "pr_title": "Document the Bucket for v1.2.0",
                "pr_body": "## Summary",
                "proposed_files": [{"filename": "README.md", "content": "# Readme\n"}],
            },
        ),
    ],
)
def test_each_agent_uses_its_prompt_tool_and_schema(build, schema, filename, payload):
    calls.clear()
    model = Once(schema_name=schema["title"], payload=payload, seen={})
    agent = build(model, [probe])
    result = agent.invoke({"messages": [{"role": "user", "content": "review latest"}]})
    assert agent.name == filename.removesuffix(".md")
    assert model.seen["system"] == read_prompt(filename)
    assert "probe" in model.seen["tools"]
    assert calls == ["latest"]
    assert result["structured_response"] == payload
