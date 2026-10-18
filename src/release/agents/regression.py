"""Placeholder. This is not an agent and it does not call a model."""

from typing import Any

from release.state import ReleaseState


def regression_node(_state: ReleaseState) -> dict[str, Any]:
    return {
        "regression_findings": {
            "status": "not_run",
            "summary": "Regression agent is a placeholder and is not implemented.",
        }
    }
