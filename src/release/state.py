"""Graph state for one module release review.

Gold labels and tokens stay off this state. Later stages fill fields in place.
"""

from typing import Any, Literal, TypedDict

Bump = Literal["major", "minor", "patch", "none"]


class ReleaseResult(TypedDict):
    status: str
    branch: str
    url: str


class ReleaseState(TypedDict, total=False):
    module_path: str
    base_ref: str
    candidate_ref: str
    candidate_sha: str
    diff_summary: str
    changed_paths: list[str]

    interface: dict[str, Any]
    contract_findings: dict[str, Any]
    docs_findings: dict[str, Any]
    regression_findings: dict[str, Any]

    bump: Bump
    proposed_version: str
    reasons: list[str]
    blockers: list[str]
    ready_for_release: bool
    release_notes: str

    human_decision: str
    human_edited_version: str
    human_edited_notes: str

    release_result: ReleaseResult
