"""LangSmith cloud experiment shape. The run itself is not implemented yet."""

from langsmith.evaluation import evaluate

from release.config import LANGSMITH_CLOUD_ENDPOINT

DATASET_NAME = "tf-module-release"
EVALUATORS = (
    "bump_match",
    "docs_ready_match",
    "draft_release_not_called",
)


def experiment_spec() -> dict[str, object]:
    return {
        "dataset": DATASET_NAME,
        "endpoint": LANGSMITH_CLOUD_ENDPOINT,
        "evaluators": list(EVALUATORS),
        "runner": evaluate.__name__,
    }


def run_experiment() -> None:
    raise NotImplementedError("LangSmith experiment is not implemented yet.")
