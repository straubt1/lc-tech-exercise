"""Graph state for the Terraform module releaser. Gold labels and tokens never go here."""

from typing import Any, Literal, TypedDict

Bump = Literal["major", "minor", "patch", ""]
HumanDecision = Literal["approved", "rejected", ""]


class ReleaseState(TypedDict, total=False):
    repo: str
    candidate_ref: str
    base_ref: str
    candidate_sha: str
    diff_summary: str
    changed_paths: list[str]
    docs_ready: bool
    docs_findings: dict[str, Any]
    bump: Bump
    proposed_version: str
    reasons: list[str]
    release_notes: str
    regression_findings: dict[str, Any]
    human_decision: HumanDecision
    release_result: dict[str, str]
