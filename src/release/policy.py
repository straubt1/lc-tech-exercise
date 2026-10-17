"""Version tag and release-branch rules shared by load, the version agent, and release."""

import re
from dataclasses import dataclass

DEFAULT_MODULE_PATH = "/workspace/terraform-aws-object-storage"

# Module code under review lives on this branch; main is not the release candidate.
CANDIDATE_BRANCH = "latest"

NOT_RUN = "not_run"

BUMPS = ("major", "minor", "patch", "none")

# Exact v-prefixed release name. v1.2, v1.2.3-rc1, and release/verify-v1.0.2 do not match.
_VERSION_TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

RELEASE_POLICY = """
Bump rules. Use the highest one that applies:
- major: a variable or output was removed, renamed, or retyped; a required variable was added; a variable default changed.
- minor: an optional variable was added, or an output was added.
- patch: behavior changed and the variable and output contract stayed the same.
- none: the change is docs-only. Do not propose a version branch.

Blockers, listed apart from the bump:
- a variable or output is missing a description
- a sensitive value is not marked sensitive
- the README or changelog is stale for this change

A blocker does not change the bump.
""".strip()


@dataclass(frozen=True)
class VersionRef:
    version: tuple[int, int, int]
    short_name: str
    rev: str
    local: bool


def parse_version(name: str) -> tuple[int, int, int] | None:
    match = _VERSION_TAG.fullmatch(name.strip())
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def format_version(version: tuple[int, int, int]) -> str:
    major, minor, patch = version
    return f"v{major}.{minor}.{patch}"


def version_of_ref(ref: str) -> tuple[int, int, int]:
    short_name = ref.rsplit("/", 1)[-1]
    parsed = parse_version(short_name)
    if parsed is None:
        raise ValueError(f"{ref} is not a vX.Y.Z version tag")
    return parsed


def next_version(version: tuple[int, int, int], bump: str) -> str:
    major, minor, patch = version
    if bump == "major":
        return format_version((major + 1, 0, 0))
    if bump == "minor":
        return format_version((major, minor + 1, 0))
    if bump == "patch":
        return format_version((major, minor, patch + 1))
    if bump == "none":
        return ""
    raise ValueError(f"unknown bump {bump}")


def version_ref_from_refname(refname: str) -> VersionRef | None:
    """Map a refs/tags/vX.Y.Z refname to a version tag. Peeled tag refs are ignored."""
    if refname.endswith("^{}"):
        return None
    if not refname.startswith("refs/tags/"):
        return None
    short_name = refname.removeprefix("refs/tags/")
    parsed = parse_version(short_name)
    if parsed is None:
        return None
    return VersionRef(version=parsed, short_name=short_name, rev=short_name, local=True)


def select_base_ref(refnames: list[str]) -> VersionRef:
    """Highest vX.Y.Z tag in refs/tags."""
    chosen: list[VersionRef] = []
    for refname in refnames:
        item = version_ref_from_refname(refname)
        if item is not None:
            chosen.append(item)
    if not chosen:
        raise LookupError("no vX.Y.Z tag in refs/tags")
    return max(chosen, key=lambda item: item.version)


def chosen_release_branch(
    decision: str,
    proposed_version: str,
    edited_version: str,
) -> tuple[str, str]:
    """Return (outcome, branch).

    outcome is rejected, invalid_version, or release.
    An approved docs-only proposal has outcome release and an empty branch.
    """
    if decision == "edited":
        branch = edited_version.strip()
        if parse_version(branch) is None:
            return "invalid_version", branch
        return "release", branch
    if decision == "approved":
        branch = proposed_version.strip()
        if branch and parse_version(branch) is None:
            return "invalid_version", branch
        return "release", branch
    return "rejected", ""
