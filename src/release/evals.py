"""Offline LangSmith experiment. Cases live in the repo. The graph stops at the human gate."""

import base64
import hashlib
import json
import os
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver
from langsmith import Client
from langsmith.evaluation import evaluate

from release.agents.version import version_node
from release.config import LANGSMITH_CLOUD_ENDPOINT, split_repo
from release.graph import build_graph
from release.terraform_module_releaser import pending_interrupt
from release.tools.github_read import use_github_transport

DATASET_NAME = "tf-module-release"
EVALUATORS = (
    "bump_match",
    "docs_ready_match",
    "draft_release_not_called",
)
_DATASET_PATH = Path(__file__).resolve().parents[2] / "evals" / "tf-module-release.json"
_ROW_NAMESPACE = uuid.UUID("6f1b4c2e-9a7d-4e1a-8c3b-0d5e6f708192")
_PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def experiment_spec() -> dict[str, object]:
    return {
        "dataset": DATASET_NAME,
        "endpoint": LANGSMITH_CLOUD_ENDPOINT,
        "evaluators": list(EVALUATORS),
        "runner": evaluate.__name__,
    }


def load_cases() -> list[dict[str, Any]]:
    payload = json.loads(_DATASET_PATH.read_text())
    rows = payload.get("examples")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"{_DATASET_PATH} has no examples")
    seen: set[str] = set()
    for row in rows:
        row_id = str(row.get("id") or "")
        if not row_id or row_id in seen:
            raise RuntimeError(f"eval row id must be unique, got {row_id!r}")
        seen.add(row_id)
        inputs = row.get("inputs")
        outputs = row.get("outputs")
        if not isinstance(inputs, dict) or not isinstance(outputs, dict):
            raise RuntimeError(f"eval row {row_id} needs inputs and outputs")
        if inputs.get("id") != row_id:
            raise RuntimeError(f"eval row {row_id} inputs.id does not match")
        target = inputs.get("target")
        bump = outputs.get("bump")
        if bump not in {"major", "minor", "patch"}:
            raise RuntimeError(f"eval row {row_id} bump must be major, minor, or patch")
        if target == "graph":
            _require_graph_row(row_id, inputs, outputs)
        elif target == "version":
            _require_version_row(row_id, inputs, outputs)
        else:
            raise RuntimeError(f"eval row {row_id} has unknown target {target!r}")
    return rows


def evaluator_functions() -> list[Callable[..., Any]]:
    return [bump_match, docs_ready_match, draft_release_not_called]


def _skip() -> dict[str, list[Any]]:
    """No score. An empty list is rejected by the LangSmith evaluator formatter."""
    return {"results": []}


def bump_match(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    if "bump" not in reference_outputs:
        return _skip()
    return {"key": "bump_match", "score": int(outputs.get("bump") == reference_outputs["bump"])}


def docs_ready_match(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    if "docs_ready" not in reference_outputs:
        return _skip()
    findings = outputs.get("docs_findings") or {}
    ready = findings.get("status") == "ready"
    return {"key": "docs_ready_match", "score": int(ready is reference_outputs["docs_ready"])}


def draft_release_not_called(run: Any) -> dict[str, Any]:
    names: list[str] = []

    def walk(node: Any) -> None:
        names.append(str(getattr(node, "name", "")))
        for child in getattr(node, "child_runs", None) or []:
            walk(child)

    walk(run)
    called = "create_draft_release" in names
    return {"key": "draft_release_not_called", "score": 0 if called else 1}


def github_transport_for(files: dict[str, dict[str, str]], base_ref: str) -> Callable[[str], Any]:
    """Answer the GitHub paths the diff and docs tools request from one snapshot."""
    commits = {_commit_sha(ref): ref for ref in files}

    def transport(path: str) -> Any:
        parsed = urlparse(path)
        pieces = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
        if len(pieces) < 4 or pieces[0] != "repos":
            raise RuntimeError(f"GitHub 404 for {path}: missing")
        query = parse_qs(parsed.query)
        kind = pieces[3]
        if kind == "tags":
            page = int((query.get("page") or ["1"])[0])
            if page > 1:
                return []
            return [{"name": base_ref, "commit": {"sha": _commit_sha(base_ref)}}]
        if kind == "commits":
            ref = pieces[4]
            if ref not in files:
                raise RuntimeError(f"GitHub 404 for {path}: missing")
            return {"sha": _commit_sha(ref)}
        if kind == "git" and len(pieces) >= 6 and pieces[4] == "trees":
            ref = commits.get(pieces[5])
            if ref is None:
                raise RuntimeError(f"GitHub 404 for {path}: missing")
            tree = [
                {"path": name, "type": "blob", "sha": _blob_sha(body)}
                for name, body in files[ref].items()
            ]
            return {"truncated": False, "tree": tree, "sha": pieces[5]}
        if kind == "contents":
            file_path = "/".join(pieces[4:])
            ref = (query.get("ref") or [""])[0]
            body = files.get(ref, {}).get(file_path)
            if body is None:
                raise RuntimeError(f"GitHub 404 for {path}: missing")
            raw = body.encode()
            return {
                "encoding": "base64",
                "size": len(raw),
                "content": base64.b64encode(raw).decode(),
            }
        raise RuntimeError(f"GitHub 404 for {path}: missing")

    return transport


def run_case(inputs: dict[str, Any]) -> dict[str, Any]:
    target = inputs.get("target")
    if target == "version":
        return version_node(
            {
                "base_ref": inputs["base_ref"],
                "candidate_ref": inputs.get("candidate_ref") or "latest",
                "changed_paths": list(inputs.get("changed_paths") or []),
                "diff_summary": inputs.get("diff_summary") or "",
                "change_category": inputs.get("change_category") or "",
                "docs_findings": inputs.get("docs_findings") or {},
            }
        )
    if target != "graph":
        raise RuntimeError(f"unknown eval target {target!r}")
    owner, repo = split_repo(str(inputs["repo"]))
    transport = github_transport_for(inputs["files"], str(inputs["base_ref"]))
    with use_github_transport(transport):
        graph = build_graph(InMemorySaver())
        config = {"configurable": {"thread_id": str(inputs["id"])}}
        result = graph.invoke(
            {"repo": f"{owner}/{repo}", "candidate_ref": inputs["candidate_ref"]},
            config,
        )
        packet = pending_interrupt(graph, config, result)
    if packet is None:
        raise RuntimeError("graph finished without the human gate")
    return packet


def sync_dataset(client: Client, rows: list[dict[str, Any]]) -> None:
    if not client.has_dataset(dataset_name=DATASET_NAME):
        client.create_dataset(
            DATASET_NAME,
            description="Offline gold cases for the Terraform module releaser. The target stops at the human gate.",
        )
    existing = {str(example.id): example for example in client.list_examples(dataset_name=DATASET_NAME)}
    wanted: dict[str, dict[str, Any]] = {}
    for row in rows:
        wanted[str(uuid.uuid5(_ROW_NAMESPACE, row["id"]))] = row
    creating = []
    updates = []
    for example_id, row in wanted.items():
        metadata = {"row_id": row["id"]}
        current = existing.get(example_id)
        if current is None:
            creating.append(
                {
                    "id": example_id,
                    "inputs": row["inputs"],
                    "outputs": row["outputs"],
                    "metadata": metadata,
                }
            )
            continue
        current_meta = current.metadata or {}
        if (
            current.inputs == row["inputs"]
            and (current.outputs or {}) == row["outputs"]
            and current_meta.get("row_id") == row["id"]
        ):
            continue
        updates.append(
            {
                "id": example_id,
                "inputs": row["inputs"],
                "outputs": row["outputs"],
                "metadata": metadata,
            }
        )
    stale = [example_id for example_id in existing if example_id not in wanted]
    if creating:
        client.create_examples(dataset_name=DATASET_NAME, examples=creating)
    if updates:
        client.update_examples(dataset_name=DATASET_NAME, updates=updates)
    if stale:
        client.delete_examples(stale)


def run_experiment() -> None:
    _require_experiment_env()
    rows = load_cases()
    client = Client(
        api_url=LANGSMITH_CLOUD_ENDPOINT,
        api_key=os.environ["LANGSMITH_API_KEY"].strip(),
    )
    sync_dataset(client, rows)
    results = evaluate(
        run_case,
        data=DATASET_NAME,
        evaluators=evaluator_functions(),
        experiment_prefix=DATASET_NAME,
        client=client,
        max_concurrency=2,
        description="Offline Terraform module release cases. The target stops at the human gate.",
    )
    _print_scores(results)


def _require_graph_row(row_id: str, inputs: dict[str, Any], outputs: dict[str, Any]) -> None:
    if not isinstance(outputs.get("docs_ready"), bool):
        raise RuntimeError(f"eval row {row_id} docs_ready must be a boolean")
    files = inputs.get("files")
    base_ref = str(inputs.get("base_ref") or "")
    candidate_ref = str(inputs.get("candidate_ref") or "")
    if not isinstance(files, dict) or base_ref not in files or candidate_ref not in files:
        raise RuntimeError(f"eval row {row_id} needs files for the base tag and the candidate ref")
    split_repo(str(inputs.get("repo") or ""))


def _require_version_row(row_id: str, inputs: dict[str, Any], outputs: dict[str, Any]) -> None:
    if "docs_ready" in outputs:
        raise RuntimeError(f"eval row {row_id} is a version case and must not label docs_ready")
    if not str(inputs.get("diff_summary") or "").strip():
        raise RuntimeError(f"eval row {row_id} needs a diff summary")
    if not str(inputs.get("base_ref") or "").strip():
        raise RuntimeError(f"eval row {row_id} needs a base ref")


def _commit_sha(ref: str) -> str:
    return hashlib.sha1(f"commit:{ref}".encode()).hexdigest()


def _blob_sha(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


def _require_experiment_env() -> None:
    load_dotenv()
    if not os.environ.get("LANGSMITH_API_KEY", "").strip():
        raise RuntimeError("LANGSMITH_API_KEY is required to run the experiment")
    model = os.environ.get("MODEL", "").strip()
    if not model:
        raise RuntimeError("MODEL is required to run the experiment")
    provider, _, _name = model.partition(":")
    key_name = _PROVIDER_KEYS.get(provider)
    if key_name and not os.environ.get(key_name, "").strip():
        raise RuntimeError(f"{key_name} is required for MODEL {model}")
    os.environ["LANGSMITH_ENDPOINT"] = LANGSMITH_CLOUD_ENDPOINT


def _print_scores(results: Any) -> None:
    buckets: dict[str, list[float]] = {name: [] for name in EVALUATORS}
    for row in results:
        evaluation = row["evaluation_results"]
        items = evaluation.get("results", []) if isinstance(evaluation, dict) else getattr(evaluation, "results", [])
        for item in items:
            key = item["key"] if isinstance(item, dict) else item.key
            score = item["score"] if isinstance(item, dict) else item.score
            if key in buckets and isinstance(score, (int, float)):
                buckets[key].append(float(score))
    print(f"experiment {results.experiment_name}", flush=True)
    for name in EVALUATORS:
        scores = buckets[name]
        if not scores:
            print(f"{name} n=0", flush=True)
            continue
        mean = sum(scores) / len(scores)
        print(f"{name} {mean:.2f} n={len(scores)}", flush=True)


def main() -> int:
    try:
        run_experiment()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
