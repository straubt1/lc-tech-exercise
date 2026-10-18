"""Load env, run the release graph to the recommendation, then resume that same thread."""

import argparse
import sys
import uuid
from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from release.agents.release import format_recommendation
from release.config import Settings, load_settings
from release.graph import build_graph
from release.observability import configure_langsmith
from release.state import ReleaseState


def interrupt_value(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    raw = result.get("__interrupt__")
    if not raw:
        return None
    first = raw[0]
    value = first.value if hasattr(first, "value") else first
    if not isinstance(value, dict):
        raise RuntimeError("human gate returned an unexpected payload")
    return value


def pending_interrupt(graph: Any, config: dict[str, Any], result: Any) -> dict[str, Any] | None:
    packet = interrupt_value(result)
    if packet is not None:
        return packet
    snapshot = graph.get_state(config)
    interrupts = getattr(snapshot, "interrupts", ()) or ()
    if not interrupts:
        for task in getattr(snapshot, "tasks", ()) or ():
            interrupts = getattr(task, "interrupts", ()) or ()
            if interrupts:
                break
    if not interrupts:
        return None
    value = interrupts[0].value
    if not isinstance(value, dict):
        raise RuntimeError("human gate returned an unexpected payload")
    return value


def _question(packet: dict[str, Any]) -> str:
    if packet.get("ready"):
        return "Draft a release? [yes/no]: "
    ref = packet.get("candidate_ref") or "the candidate ref"
    return (
        "Implement suggestions on a new branch and open a draft pull request "
        f"into {ref}? [yes/no]: "
    )


def read_decision_from_stdin(packet: dict[str, Any]) -> dict[str, str]:
    print(format_recommendation(packet), flush=True)
    while True:
        choice = input(_question(packet)).strip().lower()
        if choice in {"yes", "y"}:
            return {"decision": "yes"}
        if choice in {"no", "n"}:
            return {"decision": "no"}
        print("Enter yes or no.")


def run(
    settings: Settings,
    thread_id: str,
    read_decision: Callable[[dict[str, Any]], dict[str, str]],
) -> ReleaseState:
    configure_langsmith(settings)
    graph = build_graph(InMemorySaver())
    config = {"configurable": {"thread_id": thread_id}}
    first = graph.invoke(
        {"repo": settings.github_repo, "candidate_ref": settings.candidate_ref},
        config,
    )
    packet = pending_interrupt(graph, config, first)
    if packet is None:
        raise RuntimeError("graph finished without the human gate")
    decision = read_decision(packet)
    resumed = graph.invoke(Command(resume=decision), config)
    if pending_interrupt(graph, config, resumed) is not None:
        raise RuntimeError("graph interrupted again after the human gate")
    return graph.get_state(config).values


def format_result(result: dict[str, str]) -> str:
    status = result.get("status", "")
    if status == "exit":
        return "Exited. Nothing was created."
    if status == "dry_run":
        kind = "pull request" if result.get("action") == "pull_request" else "release"
        return f"RELEASE_ENABLED is off. No draft {kind} was created."
    if status == "draft":
        return f"Draft release {result.get('tag', '')} {result.get('url', '')}".strip()
    if status == "draft_pr":
        return f"Draft pull request {result.get('url', '')} branch {result.get('branch', '')}".strip()
    if status == "no_changes":
        return "No file changes were produced. No pull request was created."
    return f"Release status={status} tag={result.get('tag', '')} url={result.get('url', '')}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Review a public Terraform module, then draft a release or a pull request."
    )
    parser.add_argument("--thread-id", default=None, help="Checkpoint thread. Defaults to a new id.")
    args = parser.parse_args(argv)

    settings = load_settings()
    thread_id = args.thread_id or str(uuid.uuid4())
    tracing = "on" if settings.langsmith_tracing else "off"
    print(f"Repo {settings.github_repo}", flush=True)
    print(f"Candidate {settings.candidate_ref}", flush=True)
    print(f"Model {settings.model or '(unset)'}", flush=True)
    print(f"LangSmith tracing {tracing} endpoint {settings.langsmith_endpoint}", flush=True)
    print(f"Thread {thread_id}", flush=True)
    try:
        values = run(settings, thread_id, read_decision_from_stdin)
    except EOFError:
        print("Decision input closed before a choice.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    result = values.get("release_result") or {}
    print(format_result(result), flush=True)
    print(f"Resumed thread {thread_id}", flush=True)
    if result.get("status") in {"exit", "dry_run", "draft", "draft_pr"}:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
