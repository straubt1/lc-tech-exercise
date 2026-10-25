"""Delete every LangSmith dataset and the experiments attached to each one.

Tracing projects that are not tied to a dataset stay, including LANGSMITH_PROJECT.
Loads the repo .env file.
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langsmith import Client

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENDPOINT = "https://api.smith.langchain.com"


def _rows(client: Client) -> list[tuple]:
    rows = []
    for dataset in client.list_datasets():
        experiments = list(client.list_projects(reference_dataset_id=dataset.id))
        rows.append((dataset, experiments))
    return rows


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(
        description="Delete every LangSmith dataset and its experiments.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Delete without a confirmation prompt.",
    )
    args = parser.parse_args(argv)

    api_key = os.environ.get("LANGSMITH_API_KEY", "").strip()
    endpoint = os.environ.get("LANGSMITH_ENDPOINT", "").strip() or DEFAULT_ENDPOINT
    tracing = os.environ.get("LANGSMITH_PROJECT", "").strip()
    if not api_key:
        print("error: LANGSMITH_API_KEY is not set", file=sys.stderr)
        return 1

    client = Client(api_url=endpoint, api_key=api_key)
    rows = _rows(client)
    experiment_count = sum(len(experiments) for _, experiments in rows)
    if not rows:
        print(f"No datasets at {endpoint}.")
        return 0

    print(f"Datasets at {endpoint}:")
    for dataset, experiments in rows:
        print(f"  {dataset.name}")
        for project in experiments:
            print(f"    {project.name}")
        if not experiments:
            print("    (no experiments)")
    if tracing:
        print(f"Tracing project {tracing!r} is kept.")

    if not args.yes:
        answer = input(
            f"Delete {len(rows)} datasets and {experiment_count} experiments at {endpoint}? [y/N]: "
        ).strip().lower()
        if answer not in {"y", "yes"}:
            print("Aborted.")
            return 1

    for dataset, experiments in rows:
        for project in experiments:
            client.delete_project(project_id=str(project.id))
            print(f"Deleted experiment {project.name}")
        client.delete_dataset(dataset_id=dataset.id)
        print(f"Deleted dataset {dataset.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
