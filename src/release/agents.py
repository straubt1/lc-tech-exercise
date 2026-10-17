"""Version agent. Contract and docs agents replace their pass-throughs later."""

import json
import os
from typing import Any

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from release.policy import BUMPS, NOT_RUN, RELEASE_POLICY, next_version, version_of_ref
from release.state import Bump, ReleaseState

VERSION_SYSTEM_PROMPT = f"""You decide the semantic version bump for a Terraform module that is about to be published.

You do not publish a branch. A person approves, edits, or rejects the proposal after you.

{RELEASE_POLICY}

How to read the evidence:
- changed_paths and diff_summary compare the highest published vX.Y.Z tag to the module latest branch. main is not the candidate.
- The published contract is the root module: variables.tf, outputs.tf, and resources in the root .tf files. Stacks under consumers/ or examples/ are callers.
- contract_findings, docs_findings, and regression_findings are the stage results.
- A stage with status {NOT_RUN} was not run. Do not invent a pass. Do not invent a failure. Do not invent findings that stage would have produced.
- regression status {NOT_RUN} is not a pass and not a failure. It does not block the release.
- Apply the bump and blocker rules to the diff you can see. A changelog that calls a change a patch does not override a major or minor rule.
- Blockers do not by themselves change the bump.
- ready_for_release is true only when the bump is major, minor, or patch and blockers is empty.
- reasons cite the diff or a real finding. release_notes are a short paragraph a person can accept or edit.
"""


class VersionDecision(BaseModel):
    """Structured bump. The branch name is computed from the base ref, not from this model."""

    bump: Bump = Field(description="One of major, minor, patch, none.")
    reasons: list[str] = Field(description="Why this bump applies.")
    blockers: list[str] = Field(
        description="Contract or doc blockers visible in the diff. Empty when none are visible."
    )
    ready_for_release: bool = Field(
        description="True only for major, minor, or patch when blockers is empty."
    )
    release_notes: str = Field(description="Short notes a person can accept or edit.")


def render_version_input(state: ReleaseState) -> str:
    payload = {
        "base_ref": state.get("base_ref", ""),
        "candidate_ref": state.get("candidate_ref", ""),
        "candidate_sha": state.get("candidate_sha", ""),
        "changed_paths": state.get("changed_paths", []),
        "diff_summary": state.get("diff_summary", ""),
        "interface": state.get("interface", {}),
        "contract_findings": state.get("contract_findings", {}),
        "docs_findings": state.get("docs_findings", {}),
        "regression_findings": state.get("regression_findings", {}),
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _decision_from(result: VersionDecision | dict[str, Any]) -> VersionDecision:
    if isinstance(result, VersionDecision):
        return result
    return VersionDecision.model_validate(result)


def version_agent(state: ReleaseState) -> dict[str, Any]:
    """Structured model call with no tools. Sees every finding and must not treat not_run as a pass."""
    load_dotenv()
    model_name = os.environ.get("MODEL", "").strip()
    if not model_name:
        raise RuntimeError("MODEL is not set. Add it to .env (see .env.example).")

    structured = init_chat_model(model_name).with_structured_output(
        VersionDecision,
        method="json_schema",
    )
    result = structured.invoke(
        [
            SystemMessage(VERSION_SYSTEM_PROMPT),
            HumanMessage(render_version_input(state)),
        ]
    )
    decision = _decision_from(result)
    if decision.bump not in BUMPS:
        raise RuntimeError(f"version agent returned unknown bump {decision.bump}")

    blockers = [item.strip() for item in decision.blockers if item.strip()]
    reasons = [item.strip() for item in decision.reasons if item.strip()]
    proposed = next_version(version_of_ref(state["base_ref"]), decision.bump)
    ready = decision.bump != "none" and not blockers
    return {
        "bump": decision.bump,
        "proposed_version": proposed,
        "reasons": reasons,
        "blockers": blockers,
        "ready_for_release": ready,
        "release_notes": decision.release_notes.strip(),
    }
