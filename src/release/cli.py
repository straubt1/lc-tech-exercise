"""Run the release graph until the human gate, then resume that same thread."""

import argparse
import os
import sys
import uuid
from collections.abc import Callable
from typing import Any

from dotenv import load_dotenv
from langgraph.types import Command

from release.graph import build_graph
from release.policy import DEFAULT_MODULE_PATH
from release.state import ReleaseState


def resolve_module_path(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    from_env = os.environ.get("MODULE_PATH", "").strip()
    if from_env:
        return from_env
    return DEFAULT_MODULE_PATH


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


def format_review(state: ReleaseState, packet: dict[str, Any]) -> str:
    blockers = packet.get("blockers") or []
    reasons = packet.get("reasons") or []
    blocker_lines = "\n".join(f"- {item}" for item in blockers) or "- (none)"
    reason_lines = "\n".join(f"- {item}" for item in reasons) or "- (none)"
    finding_lines = []
    for name in ("contract_findings", "docs_findings", "regression_findings"):
        finding = packet.get(name) or {}
        status = finding.get("status", "")
        summary = finding.get("summary")
        line = f"- {name.removesuffix('_findings')}: {status}"
        if summary:
            line = f"{line} ({summary})"
        finding_lines.append(line)
    proposed = packet.get("proposed_version") or "(none)"
    return "\n".join(
        [
            f"Module {state.get('module_path', '')}",
            f"Base {state.get('base_ref', '')}",
            f"Candidate {state.get('candidate_ref', '')} {state.get('candidate_sha', '')}",
            "",
            f"Bump: {packet.get('bump', '')}",
            f"Proposed branch: {proposed}",
            f"Ready for release: {packet.get('ready_for_release', False)}",
            "Blockers:",
            blocker_lines,
            "Reasons:",
            reason_lines,
            "Notes:",
            str(packet.get("release_notes") or "(none)"),
            "Findings:",
            *finding_lines,
        ]
    )


def read_decision_from_stdin(packet: dict[str, Any], state: ReleaseState) -> dict[str, str]:
    print(format_review(state, packet), flush=True)
    while True:
        choice = input("Decision [approve/edit/reject]: ").strip().lower()
        if choice in {"approve", "approved"}:
            return {"decision": "approved", "version": "", "notes": ""}
        if choice in {"reject", "rejected"}:
            return {"decision": "rejected", "version": "", "notes": ""}
        if choice in {"edit", "edited"}:
            version = input("Branch name (vX.Y.Z): ").strip()
            notes = input("Release notes: ").strip()
            return {"decision": "edited", "version": version, "notes": notes}
        print("Enter approve, edit, or reject.")


def run(
    module_path: str,
    thread_id: str,
    read_decision: Callable[[dict[str, Any], ReleaseState], dict[str, str]],
) -> ReleaseState:
    graph = build_graph()
    config = {"configurable": {"thread_id": thread_id}}
    first = graph.invoke({"module_path": module_path}, config)
    packet = pending_interrupt(graph, config, first)
    if packet is None:
        raise RuntimeError("graph finished without the human gate")
    decision = read_decision(packet, graph.get_state(config).values)
    resumed = graph.invoke(Command(resume=decision), config)
    if pending_interrupt(graph, config, resumed) is not None:
        raise RuntimeError("graph interrupted again after the human gate")
    return graph.get_state(config).values


def format_result(result: dict[str, str]) -> str:
    status = result.get("status", "")
    branch = result.get("branch", "")
    url = result.get("url", "")
    lines = [f"Release status={status} branch={branch} url={url}"]
    if status == "dry_run":
        lines.append("Dry run only. No branch was created.")
    elif status == "rejected":
        lines.append("Rejected. No branch was created.")
    elif status == "invalid_version":
        lines.append("Edited branch name must match vX.Y.Z. No branch was created.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Review a Terraform module release and record a dry run.")
    parser.add_argument("--module-path", default=None, help="Module checkout. Defaults to MODULE_PATH.")
    parser.add_argument("--thread-id", default=None, help="Checkpoint thread. Defaults to a new id.")
    args = parser.parse_args(argv)

    thread_id = args.thread_id or str(uuid.uuid4())
    module_path = resolve_module_path(args.module_path)
    print(f"Thread {thread_id}", flush=True)
    try:
        values = run(module_path, thread_id, read_decision_from_stdin)
    except EOFError:
        print("Decision input closed before a choice.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    result = values.get("release_result") or {}
    print(format_result(result), flush=True)
    print(f"Resumed thread {thread_id}", flush=True)
    if result.get("status") in {"dry_run", "rejected"}:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
