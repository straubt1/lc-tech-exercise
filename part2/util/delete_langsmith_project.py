"""Delete a LangSmith cloud tracing project. Loads the repo .env file."""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langsmith import Client

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENDPOINT = "https://api.smith.langchain.com"


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Delete a LangSmith tracing project.")
    parser.add_argument(
        "--project",
        default=None,
        help="Project name. Defaults to LANGSMITH_PROJECT from .env.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Delete without a confirmation prompt.",
    )
    args = parser.parse_args(argv)

    project = (args.project or os.environ.get("LANGSMITH_PROJECT", "")).strip()
    api_key = os.environ.get("LANGSMITH_API_KEY", "").strip()
    endpoint = os.environ.get("LANGSMITH_ENDPOINT", "").strip() or DEFAULT_ENDPOINT
    if not project:
        print("error: pass --project or set LANGSMITH_PROJECT", file=sys.stderr)
        return 1
    if not api_key:
        print("error: LANGSMITH_API_KEY is not set", file=sys.stderr)
        return 1

    if not args.yes:
        answer = input(f"Delete LangSmith project {project!r} at {endpoint}? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Aborted.")
            return 1

    Client(api_url=endpoint, api_key=api_key).delete_project(project_name=project)
    print(f"Deleted LangSmith project {project}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
