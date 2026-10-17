"""Linear release graph. Later increments replace pass-through nodes and leave the edges."""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from release.agents import version_agent
from release.nodes import (
    contract_node,
    docs_node,
    load_node,
    regression_node,
    release_node,
    review_node,
)
from release.state import ReleaseState


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    builder = StateGraph(ReleaseState)
    builder.add_node("load", load_node)
    builder.add_node("contract", contract_node)
    builder.add_node("docs", docs_node)
    builder.add_node("regression", regression_node)
    builder.add_node("version", version_agent)
    builder.add_node("review", review_node)
    builder.add_node("release", release_node)

    builder.add_edge(START, "load")
    builder.add_edge("load", "contract")
    builder.add_edge("contract", "docs")
    builder.add_edge("docs", "regression")
    builder.add_edge("regression", "version")
    builder.add_edge("version", "review")
    builder.add_edge("review", "release")
    builder.add_edge("release", END)

    if checkpointer is None:
        checkpointer = InMemorySaver()
    return builder.compile(checkpointer=checkpointer)
