"""Release graph. Diff, docs, and version run. Regression stays a placeholder."""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from release.agents.diff import diff_node
from release.agents.docs import docs_node
from release.agents.regression import regression_node
from release.agents.release import recommend_node, release_node
from release.agents.version import version_node
from release.state import ReleaseState


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    builder = StateGraph(ReleaseState)
    builder.add_node("diff", diff_node)
    builder.add_node("docs", docs_node)
    builder.add_node("version", version_node)
    builder.add_node("regression", regression_node)
    builder.add_node("recommend", recommend_node)
    builder.add_node("release", release_node)

    builder.add_edge(START, "diff")
    builder.add_edge("diff", "docs")
    builder.add_edge("docs", "version")
    builder.add_edge("version", "regression")
    builder.add_edge("regression", "recommend")
    builder.add_edge("recommend", "release")
    builder.add_edge("release", END)

    return builder.compile(checkpointer=checkpointer, name="terraform_module_releaser")


graph = build_graph()
