import json
import os
from pathlib import Path
from statistics import median

from dotenv import load_dotenv
from langsmith import Client, evaluate

from review.graph import build_graph, load_model
from review.reader import FixtureReader

DATASET = "tf-module-review"
_EXAMPLES = Path(__file__).resolve().parents[2] / "evals" / "tf-module-review.json"
_AGENTS = ("review", "version", "recommend")


def load_examples() -> list[dict]:
    return json.loads(_EXAMPLES.read_text())["examples"]


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
    for key in ("review_findings", "version_findings"):
        for item in outputs.get(key) or []:
            names.add(item["filename"])
    return names


def _version_pairs(outputs: dict) -> set[tuple[str, bool]]:
    return {
        (item["version"], bool(item["published"]))
        for item in outputs.get("versions") or []
    }


def review_status(run, example) -> dict:
    got = (run.outputs or {}).get("review_status")
    want = (example.outputs or {}).get("review_status")
    return {"key": "review_status", "score": int(got == want)}


def suggested_version(run, example) -> dict:
    got = (run.outputs or {}).get("suggested_version")
    want = (example.outputs or {}).get("suggested_version")
    return {"key": "suggested_version", "score": int(got == want)}


def finding_files(run, example) -> dict:
    got = _filenames(run.outputs or {})
    want = set((example.outputs or {}).get("finding_files") or [])
    return {"key": "finding_files", "score": int(got == want)}


def versions(run, example) -> dict:
    got = _version_pairs(run.outputs or {})
    want = _version_pairs(example.outputs or {})
    return {"key": "versions", "score": int(got == want)}


def target(inputs: dict) -> dict:
    load_dotenv()
    model_name = os.environ.get("MODEL", "").strip()
    if not model_name:
        raise RuntimeError("Set MODEL to provider:model")
    app = build_graph(load_model(model_name), fixture_from_inputs(inputs))
    result = app.invoke(
        {"repo": inputs["repo"], "ref": inputs["ref"], "pr_url": ""},
        {"configurable": {"thread_id": inputs.get("id", "eval")}},
    )
    return {
        "review_status": result.get("review_status"),
        "suggested_version": result.get("suggested_version"),
        "review_findings": result.get("review_findings") or [],
        "version_findings": result.get("version_findings") or [],
        "versions": result.get("versions") or [],
    }


def sync_dataset(client: Client, examples: list[dict]) -> None:
    if not client.has_dataset(dataset_name=DATASET):
        client.create_dataset(DATASET)
    else:
        existing = list(client.list_examples(dataset_name=DATASET))
        if existing:
            client.delete_examples([example.id for example in existing])
    client.create_examples(
        dataset_name=DATASET,
        examples=[{"inputs": example["inputs"], "outputs": example["outputs"]} for example in examples],
    )


def _leaf_tokens(run_id, by_id, children) -> int:
    kids = children.get(run_id, [])
    if not kids:
        return by_id[run_id].total_tokens or 0
    return sum(_leaf_tokens(kid.id, by_id, children) for kid in kids)


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
        latency = median(latencies) if latencies else 0
        token_count = median(tokens) if tokens else 0
        print(f"{name} median_latency_s={latency:.2f} median_tokens={token_count:.0f}")


def run_evaluation():
    load_dotenv()
    client = Client()
    examples = load_examples()
    sync_dataset(client, examples)
    results = evaluate(
        target,
        data=DATASET,
        evaluators=[review_status, suggested_version, finding_files, versions],
        experiment_prefix=DATASET,
        max_concurrency=1,
        client=client,
    )
    print_performance(client, results.experiment_name)
    return results
