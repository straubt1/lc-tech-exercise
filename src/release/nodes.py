"""Plain nodes: load, pass-through stages, the human gate, and the dry-run record."""

import os
import subprocess
from pathlib import Path
from typing import Any

from langgraph.types import interrupt

from release.policy import (
    DEFAULT_MODULE_PATH,
    NOT_RUN,
    chosen_release_branch,
    select_base_ref,
)
from release.state import ReleaseResult, ReleaseState

_MAX_DIFF_CHARS = 24_000
_DOC_NAMES = {"readme.md", "readme.markdown", "versions.md"}


def _git(repo: Path, *args: str) -> str:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "git failed"
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout


def _paths_from_name_status(name_status: str) -> list[str]:
    paths: list[str] = []
    for line in name_status.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            paths.extend(parts[1:])
    return paths


def _include_patch(path: str) -> bool:
    name = Path(path).name.lower()
    if name in _DOC_NAMES or name.startswith("changelog"):
        return True
    if path.endswith(".tf") or path.endswith(".tf.json"):
        return True
    normalized = path.replace("\\", "/")
    return normalized.startswith("examples/") or "/examples/" in f"/{normalized}"


def _dirty_note(repo: Path) -> str:
    porcelain = _git(repo, "status", "--porcelain", "--untracked-files=all")
    paths: list[str] = []
    for line in porcelain.splitlines():
        entry = line[3:] if len(line) > 3 else line
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        entry = entry.strip().strip('"')
        if entry:
            paths.append(entry)
    if not paths:
        return ""
    lines = ["Working tree has uncommitted changes. The candidate sha does not include:"]
    lines.extend(f"- {path}" for path in paths)
    return "\n".join(lines)


def short_diff(repo: Path, base_ref: str) -> tuple[list[str], str]:
    """Changed paths plus patches for the contract and the docs. Other patches are omitted."""
    name_status = _git(repo, "diff", "--name-status", base_ref, "HEAD")
    paths = _paths_from_name_status(name_status)
    full = [path for path in paths if _include_patch(path)]
    parts = ["Changed files:", name_status.strip() or "(none)", ""]
    if full:
        patch = _git(repo, "diff", "--unified=3", base_ref, "HEAD", "--", *full)
        parts.append(
            "Patches for root and nested Terraform, README, changelog, and examples. "
            "Other changed paths are listed above without a patch."
        )
        parts.append(patch.strip())
    else:
        parts.append("No Terraform, README, changelog, or example patches.")
    dirty = _dirty_note(repo)
    if dirty:
        parts.extend(["", dirty])
    summary = "\n".join(parts)
    if len(summary) > _MAX_DIFF_CHARS:
        summary = summary[:_MAX_DIFF_CHARS] + "\n\n[diff truncated]"
    return paths, summary


def load_node(state: ReleaseState) -> dict[str, Any]:
    """Read the module checkout and diff HEAD against the highest vX.Y.Z ref."""
    raw = state.get("module_path") or os.environ.get("MODULE_PATH") or DEFAULT_MODULE_PATH
    repo = Path(raw).expanduser().resolve()
    if not repo.is_dir():
        raise RuntimeError(f"MODULE_PATH does not exist: {repo}")
    _git(repo, "rev-parse", "--git-dir")

    listed = _git(repo, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes")
    refnames = [line for line in listed.splitlines() if line]
    try:
        base = select_base_ref(refnames)
    except LookupError as exc:
        raise RuntimeError(f"no vX.Y.Z branch in {repo}") from exc

    changed_paths, diff_summary = short_diff(repo, base.rev)
    return {
        "module_path": str(repo),
        "base_ref": base.rev,
        "candidate_ref": _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip(),
        "candidate_sha": _git(repo, "rev-parse", "HEAD").strip(),
        "changed_paths": changed_paths,
        "diff_summary": diff_summary,
        "interface": {},
    }


def contract_node(state: ReleaseState) -> dict[str, Any]:
    """Pass-through until the contract agent replaces this node."""
    return {"contract_findings": {"status": NOT_RUN}}


def docs_node(state: ReleaseState) -> dict[str, Any]:
    """Pass-through until the docs agent replaces this node."""
    return {"docs_findings": {"status": NOT_RUN}}


def regression_node(state: ReleaseState) -> dict[str, Any]:
    """Pass-through until regression runs against ministack."""
    return {"regression_findings": {"status": NOT_RUN}}


def review_node(state: ReleaseState) -> dict[str, Any]:
    """Always interrupt with the proposal. Resume value is the human decision."""
    answer = interrupt(
        {
            "bump": state.get("bump", ""),
            "proposed_version": state.get("proposed_version", ""),
            "release_notes": state.get("release_notes", ""),
            "blockers": state.get("blockers", []),
            "reasons": state.get("reasons", []),
            "ready_for_release": state.get("ready_for_release", False),
            "contract_findings": state.get("contract_findings", {}),
            "docs_findings": state.get("docs_findings", {}),
            "regression_findings": state.get("regression_findings", {}),
        }
    )
    if not isinstance(answer, dict):
        answer = {"decision": str(answer)}
    return {
        "human_decision": str(answer.get("decision", "")).strip().lower(),
        "human_edited_version": str(answer.get("version", "") or ""),
        "human_edited_notes": str(answer.get("notes", "") or ""),
    }


def _dry_run(branch: str) -> ReleaseResult:
    return {"status": "dry_run", "branch": branch, "url": ""}


def release_node(state: ReleaseState) -> dict[str, Any]:
    """Record the branch that would be created. This increment does not publish."""
    outcome, branch = chosen_release_branch(
        state.get("human_decision", ""),
        state.get("proposed_version", ""),
        state.get("human_edited_version", ""),
    )
    if outcome == "rejected":
        return {"release_result": {"status": "rejected", "branch": "", "url": ""}}
    if outcome == "invalid_version":
        return {"release_result": {"status": "invalid_version", "branch": branch, "url": ""}}
    return {"release_result": _dry_run(branch)}
