import json
import os
import uuid
from pathlib import Path
from statistics import median

from dotenv import load_dotenv
from langsmith import Client, evaluate

from review.agents import read_prompt
from review.graph import build_graph, load_model
from review.reader import FixtureReader

DATASET = "tf-module-review"
_AGENT_TAG = "Agent"
_EXAMPLES = Path(__file__).resolve().parents[2] / "evals" / "tf-module-review.json"
_AGENTS = ("interface", "security", "release", "recommend")
_FINDING_KEYS = ("interface_findings", "security_findings", "release_findings")
# Stable example ids. LangSmith lines experiments up by example id, so a resync
# must keep the same id for the same scenario.
_EXAMPLE_NAMESPACE = uuid.UUID("a7b1c2d3-e4f5-6789-abcd-ef0123456789")


def load_spec() -> dict:
    return json.loads(_EXAMPLES.read_text())


def load_examples() -> list[dict]:
    return load_spec()["examples"]


def example_id(scenario: str) -> uuid.UUID:
    return uuid.uuid5(_EXAMPLE_NAMESPACE, scenario)


def model_name() -> str:
    name = os.environ.get("MODEL", "").strip()
    if not name:
        raise RuntimeError("Set MODEL to provider:model")
    return name


def fixture_from_inputs(inputs: dict) -> FixtureReader:
    files = {}
    for ref, paths in (inputs.get("files") or {}).items():
        for path, text in paths.items():
            files[(ref, path)] = text
    compares = {}
    for key, text in (inputs.get("compares") or {}).items():
        base, head = key.split("...", 1)
        compares[(base, head)] = text
    return FixtureReader(files=files, tags=inputs.get("tags") or [], compares=compares)


def _filenames(outputs: dict) -> set[str]:
    names = set()
    for key in _FINDING_KEYS:
        for item in outputs.get(key) or []:
            names.add(item["filename"])
    return names


def _exact(key: str):
    def evaluator(run, example) -> dict:
        got = (run.outputs or {}).get(key)
        want = (example.outputs or {}).get(key)
        return {"key": key, "score": int(got == want)}

    evaluator.__name__ = key
    return evaluator


interface_status = _exact("interface_status")
security_status = _exact("security_status")
release_status = _exact("release_status")
suggested_version = _exact("suggested_version")


def finding_files(run, example) -> dict:
    got = _filenames(run.outputs or {})
    want = set((example.outputs or {}).get("finding_files") or [])
    return {"key": "finding_files", "score": int(got == want)}


EVALUATORS = [
    interface_status,
    security_status,
    release_status,
    suggested_version,
    finding_files,
]


_GRADE = {
    "title": "Groundedness",
    "type": "object",
    "properties": {
        "score": {"type": "integer", "enum": [0, 1]},
        "reason": {"type": "string"},
    },
    "required": ["score", "reason"],
}


def _finding_lines(outputs: dict) -> list[str]:
    lines = []
    for key in _FINDING_KEYS:
        for item in outputs.get(key) or []:
            lines.append(f"{item.get('filename', '')}: {item.get('finding', '')}")
    return lines


def _evidence(example) -> str:
    inputs = getattr(example, "inputs", None) or {}
    parts = ["Diff:"]
    compares = inputs.get("compares") or {}
    if compares:
        for key, text in compares.items():
            parts.append(f"{key}\n{text}")
    else:
        parts.append("(none)")
    ref = inputs.get("ref") or "latest"
    files = (inputs.get("files") or {}).get(ref) or {}
    parts.append("Files:")
    if not files:
        parts.append("(none)")
    for path, text in files.items():
        parts.append(f"--- {path}\n{text}")
    return "\n".join(parts)


def _grade_score(body) -> int:
    if not isinstance(body, dict):
        return 0
    try:
        score = int(body.get("score"))
    except (TypeError, ValueError):
        return 0
    if score not in (0, 1):
        return 0
    return score


def finding_groundedness(run, example, *, grade=None) -> dict:
    """LLM judge: does each finding sentence match the diff and the files?"""
    load_dotenv()
    lines = _finding_lines((run.outputs if run else None) or {})
    findings = "\n".join(lines) if lines else "(none)"
    if grade is None:
        grade = load_model(model_name()).with_structured_output(_GRADE)
    body = grade.invoke(
        [
            {"role": "system", "content": read_prompt("groundedness.md")},
            {"role": "user", "content": _evidence(example) + "\n\nFindings:\n" + findings},
        ]
    )
    reason = ""
    if isinstance(body, dict):
        reason = str(body.get("reason") or "")
    return {"key": "finding_groundedness", "score": _grade_score(body), "comment": reason}


def decisions_passed(runs, examples) -> dict:
    """Fraction of rows where every reference field matches."""
    total = min(len(runs), len(examples))
    if total == 0:
        return {"key": "decisions_passed", "score": 0, "comment": "0 of 0"}
    passed = 0
    for run, example in zip(runs, examples):
        if all(check(run, example)["score"] == 1 for check in EVALUATORS):
            passed += 1
    return {
        "key": "decisions_passed",
        "score": passed / total,
        "comment": f"{passed} of {total}",
    }


def target(inputs: dict) -> dict:
    load_dotenv()
    app = build_graph(load_model(model_name()), fixture_from_inputs(inputs))
    result = app.invoke(
        {"repo": inputs["repo"], "ref": inputs["ref"], "pr_url": ""},
        {"configurable": {"thread_id": inputs.get("id", "eval")}},
    )
    return {
        "interface_status": result.get("interface_status"),
        "security_status": result.get("security_status"),
        "release_status": result.get("release_status"),
        "suggested_version": result.get("suggested_version"),
        "interface_findings": result.get("interface_findings") or [],
        "security_findings": result.get("security_findings") or [],
        "release_findings": result.get("release_findings") or [],
    }


def agent_tag_id(tags: list, agent_name: str) -> str:
    for tag in tags:
        if tag.get("key") != _AGENT_TAG:
            continue
        for value in tag.get("values") or []:
            if value.get("value") == agent_name:
                return value["id"]
    raise RuntimeError(f"No {_AGENT_TAG} tag named {agent_name}")


def _tagged(resource_tags: list, tag_value_id: str) -> bool:
    for tag in resource_tags:
        for value in tag.get("values") or []:
            if value.get("id") == tag_value_id:
                return True
    return False


def tag_dataset(client: Client, dataset_id, agent_name: str) -> None:
    tags = client.request_with_retries("GET", "/workspaces/current/tags").json()
    tag_value_id = agent_tag_id(tags, agent_name)
    current = client.request_with_retries(
        "GET",
        "/workspaces/current/tags/resource",
        params={"resource_type": "dataset", "resource_id": str(dataset_id)},
    ).json()
    if _tagged(current, tag_value_id):
        return
    client.request_with_retries(
        "POST",
        "/workspaces/current/taggings",
        json={
            "tag_value_id": tag_value_id,
            "resource_type": "dataset",
            "resource_id": str(dataset_id),
        },
    )


def _example_rows(examples: list[dict]) -> list[dict]:
    rows = []
    for example in examples:
        scenario = example["inputs"]["id"]
        metadata = dict(example.get("metadata") or {})
        metadata["scenario"] = scenario
        rows.append(
            {
                "id": example_id(scenario),
                "inputs": example["inputs"],
                "outputs": example["outputs"],
                "metadata": metadata,
                "split": "base",
            }
        )
    return rows


def _set_description(client: Client, dataset_id, description: str) -> None:
    client.request_with_retries(
        "PATCH",
        f"/datasets/{dataset_id}",
        json={"description": description},
    )


def sync_dataset(client: Client, examples: list[dict], description: str = "") -> None:
    load_dotenv()
    agent_name = os.environ.get("LANGSMITH_PROJECT", "").strip()
    if not agent_name:
        raise RuntimeError("Set LANGSMITH_PROJECT to the agent name")
    tags = client.request_with_retries("GET", "/workspaces/current/tags").json()
    tag_value_id = agent_tag_id(tags, agent_name)
    if not client.has_dataset(dataset_name=DATASET):
        client.create_dataset(
            DATASET,
            description=description or None,
            tag_value_ids=[tag_value_id],
        )
    else:
        dataset = client.read_dataset(dataset_name=DATASET)
        tag_dataset(client, dataset.id, agent_name)
        if description:
            _set_description(client, dataset.id, description)
    rows = _example_rows(examples)
    wanted = {row["id"] for row in rows}
    existing = {example.id: example for example in client.list_examples(dataset_name=DATASET)}
    stale = [stored_id for stored_id in existing if stored_id not in wanted]
    if stale:
        client.delete_examples(stale)
    create = [row for row in rows if row["id"] not in existing]
    update = [row for row in rows if row["id"] in existing]
    if create:
        client.create_examples(dataset_name=DATASET, examples=create)
    if update:
        client.update_examples(dataset_name=DATASET, updates=update)


def _leaf_tokens(run_id, by_id, children) -> int:
    kids = children.get(run_id, [])
    if not kids:
        return by_id[run_id].total_tokens or 0
    return sum(_leaf_tokens(kid.id, by_id, children) for kid in kids)


def _leaf_cost(run_id, by_id, children) -> float:
    kids = children.get(run_id, [])
    if not kids:
        return float(by_id[run_id].total_cost or 0)
    return sum(_leaf_cost(kid.id, by_id, children) for kid in kids)


def print_performance(client: Client, experiment_name: str) -> None:
    runs = list(client.list_runs(project_name=experiment_name))
    by_id = {run.id: run for run in runs}
    children: dict = {}
    for run in runs:
        if run.parent_run_id:
            children.setdefault(run.parent_run_id, []).append(run)
    named = [run for run in runs if run.name in _AGENTS]
    named_ids = {run.id for run in named}
    chosen = [run for run in named if run.parent_run_id not in named_ids]
    for name in _AGENTS:
        group = [run for run in chosen if run.name == name]
        latencies = [
            (run.end_time - run.start_time).total_seconds()
            for run in group
            if run.end_time and run.start_time
        ]
        tokens = [_leaf_tokens(run.id, by_id, children) for run in group]
        costs = [_leaf_cost(run.id, by_id, children) for run in group]
        latency = median(latencies) if latencies else 0
        token_count = median(tokens) if tokens else 0
        cost = median(costs) if costs else 0
        print(
            f"{name} median_latency_s={latency:.2f} "
            f"median_tokens={token_count:.0f} median_cost={cost:.6f}"
        )


def run_evaluation():
    load_dotenv()
    client = Client()
    spec = load_spec()
    sync_dataset(client, spec["examples"], spec.get("description") or "")
    results = evaluate(
        target,
        data=DATASET,
        evaluators=[*EVALUATORS],
        # evaluators=[*EVALUATORS, finding_groundedness],
        summary_evaluators=[decisions_passed],
        experiment_prefix=DATASET,
        metadata={"models": model_name()},
        max_concurrency=1,
        client=client,
    )
    print_performance(client, results.experiment_name)
    return results
