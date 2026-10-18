"""Chat models. The diff agent uses resolve_model; other agents still build with the stub."""

import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class StubChatModel(BaseChatModel):
    """Builds with create_agent. The graph does not invoke it yet."""

    @property
    def _llm_type(self) -> str:
        return "stub"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="stub"))])

    def bind_tools(self, tools, **kwargs):
        return self


def resolve_model():
    name = os.environ.get("MODEL", "").strip()
    if not name:
        raise RuntimeError("MODEL is not set. Add it to .env (see .env.example).")
    from langchain.chat_models import init_chat_model

    return init_chat_model(name)
