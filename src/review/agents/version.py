import re

from langchain.agents import create_agent

from review.agents import read_prompt

_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$")

SCHEMA = {
    "title": "VersionResult",
    "description": "Suggested version, every found version, and findings.",
    "type": "object",
    "properties": {
        "bump": {"type": "string", "enum": ["major", "minor", "patch", "none"]},
        "justification": {"type": "string"},
        "versions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "version": {"type": "string"},
                    "published": {"type": "boolean"},
                    "source": {"type": "string"},
                },
                "required": ["version", "published", "source"],
            },
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "finding": {"type": "string"},
                },
                "required": ["filename", "finding"],
            },
        },
    },
    "required": ["bump", "justification", "versions", "findings"],
}

_LEVELS = ("patch", "minor", "major")


def _parse(version: str) -> tuple[int, int, int] | None:
    match = _SEMVER.fullmatch((version or "").strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def _fmt(parts: tuple[int, int, int]) -> str:
    return "v%d.%d.%d" % parts


def _has_changes(diff: str) -> bool:
    return "no changes" not in diff


def _bump(highest: str, kind: str) -> str:
    major, minor, patch = _parse(highest)
    if kind == "major":
        return _fmt((major + 1, 0, 0))
    if kind == "minor":
        return _fmt((major, minor + 1, 0))
    return _fmt((major, minor, patch + 1))


def _kind(diff: str) -> str:
    lowered = diff.lower()
    if "required variable" in lowered or "output renamed" in lowered or "retyped" in lowered:
        return "major"
    if "optional variable" in lowered or "new output" in lowered:
        return "minor"
    if "behavior fix" in lowered:
        return "patch"
    removed_var = removed_out = False
    added_required = added_optional = added_out = False
    lines = diff.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("-") and not line.startswith("---") and not re.match(r"^- \S+ \(", line):
            if re.match(r'-variable\s+"', line):
                removed_var = True
            if re.match(r'-output\s+"', line):
                removed_out = True
        added = re.match(r'^\+variable\s+"([^"]+)"', line)
        if added:
            has_default = False
            index += 1
            while index < len(lines) and not lines[index].startswith("+}"):
                if lines[index].startswith("+") and re.search(r"\bdefault\b", lines[index]):
                    has_default = True
                index += 1
            if has_default:
                added_optional = True
            else:
                added_required = True
            continue
        if re.match(r'^\+output\s+"', line):
            added_out = True
        index += 1
    if removed_var or removed_out or added_required:
        return "major"
    if added_optional or added_out:
        return "minor"
    return "patch"


def _files(diff: str) -> str:
    names = re.findall(r"^- (\S+) \([^)]+\)$", diff, re.M)
    if not names:
        names = re.findall(r"^--- (\S+)", diff, re.M)
    return ", ".join(names) if names else "the module"


def _changed_lines(diff: str) -> tuple[list[str], list[str]]:
    removed, added = [], []
    current = ""
    for line in diff.splitlines():
        if line.startswith("--- "):
            current = line[4:].strip()
        if current == "CHANGELOG.md":
            continue
        if re.match(r"^- \S+ \(", line) or line.startswith("---") or line.startswith("+++"):
            continue
        text = line[1:].strip()
        if not text:
            continue
        if line.startswith("-"):
            removed.append(text)
        elif line.startswith("+"):
            added.append(text)
    return removed, added


def _because(kind: str, diff: str) -> str:
    where = _files(diff)
    if kind == "major":
        return (
            f"{where} removes, renames, or retypes a variable or output, "
            "or adds a variable with no default."
        )
    if kind == "minor":
        return f"{where} adds an optional variable or a new output."
    removed, added = _changed_lines(diff)
    if removed and added:
        return (
            f"{where} changes `{removed[0][:120]}` to `{added[0][:120]}`. "
            "Variables and outputs are unchanged."
        )
    if added:
        return f"{where} changes `{added[0][:120]}`. Variables and outputs are unchanged."
    return f"{where} changes behavior and the variable and output contract is unchanged."


def _band(diff: str) -> tuple[str, str]:
    kind = _kind(diff)
    if kind == "major":
        return ("minor", "major")
    if kind == "minor":
        return ("patch", "minor")
    return ("patch", "major")


def _clamp(bump: str, floor: str, ceiling: str) -> str:
    lowest = _LEVELS.index(floor)
    highest = _LEVELS.index(ceiling)
    chosen = _LEVELS.index(bump)
    return _LEVELS[min(max(chosen, lowest), highest)]


def apply_bump(
    bump: str,
    justification: str,
    highest: str,
    diff: str,
    suggested: str = "",
) -> tuple[str, str, str]:
    if not highest or _parse(highest) is None:
        return suggested or "v1.0.0", "none", justification
    if not _has_changes(diff):
        return highest, "none", justification.strip() or f"No changes since {highest}."
    floor, ceiling = _band(diff)
    chosen = (bump or "").strip().lower()
    if chosen not in _LEVELS:
        chosen = _kind(diff)
    else:
        chosen = _clamp(chosen, floor, ceiling)
    version = _bump(highest, chosen)
    if justification.strip() and (bump or "").strip().lower() == chosen:
        return version, chosen, justification.strip()
    label = chosen.capitalize()
    reason = f"{label} bump from {highest} to {version}: {_because(chosen, diff)}"
    return version, chosen, reason


def release_brief(repo: str, ref: str, tags: list[str], diff: str) -> str:
    """Published version strings, the latest, and the one compare diff."""
    latest = tags[0] if tags else ""
    lines = [
        f"Version repo {repo} at ref {ref}.",
        "Published versions:",
        *tags,
    ]
    if latest:
        lines.append(f"Latest published version: {latest}")
        lines.extend(["", "Diff:", diff])
    else:
        lines.append("Latest published version: none")
    lines.append("Return bump, justification, versions, and findings.")
    return "\n".join(lines)


def build(model, tools):
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=read_prompt("version.md"),
        response_format=SCHEMA,
        name="version",
    )
