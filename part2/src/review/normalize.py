import os
import re

_VERSION = re.compile(r"^v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$")
_BUMPS = {"major", "minor", "patch", "none"}
_SEVERITIES = ("UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL")
_FILE_CAP = 10
_TEMPLATES = [
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/pull_request_template.md",
    "PULL_REQUEST_TEMPLATE.md",
    "pull_request_template.md",
    "docs/PULL_REQUEST_TEMPLATE.md",
    "docs/pull_request_template.md",
]
_FINDING_KEYS = ("interface_findings", "security_findings", "release_findings")


def no_changes(diff: str) -> bool:
    if "compare not found" in diff:
        return False
    return any(line.strip() == "no changes" for line in diff.splitlines())


def version(text: str) -> str:
    text = " ".join((text or "").split())
    if not _VERSION.fullmatch(text):
        return text
    if text.startswith("v"):
        return text
    return "v" + text


def _parts(text: str) -> tuple[int, int, int] | None:
    match = _VERSION.fullmatch(version(text))
    if not match:
        return None
    nums = match.group(1).split("-", 1)[0].split(".")
    return int(nums[0]), int(nums[1]), int(nums[2])


def top_heading(changelog: str) -> str:
    for line in (changelog or "").splitlines():
        line = line.strip()
        if line.startswith("## "):
            return version(line[3:].strip())
    return ""


def heading_is_ready(changelog: str, suggested: str, current: str) -> bool:
    """The top heading is the suggested version, and that version is newer than the tag."""
    heading = top_heading(changelog)
    suggested = version(suggested)
    if not heading or heading != suggested or suggested in {"", "none"}:
        return False
    current_parts = _parts(current)
    suggested_parts = _parts(suggested)
    if suggested_parts is None:
        return False
    if current_parts is None:
        return True
    return suggested_parts > current_parts


def pull_version(state: dict) -> str:
    """Branch name uses the recommended version, or the current tag when there is no bump."""
    suggested = str(state.get("suggested_version") or "").strip()
    if suggested and suggested != "none":
        return suggested
    return str(state.get("current_version") or "").strip()


def released(label: str, findings: list, suggested: str, bump: str, current: str) -> dict:
    if bump == "none":
        suggested = "none"
    return {
        "release_status": label,
        "release_findings": findings,
        "current_version": current,
        "suggested_version": suggested,
        "bump": bump,
    }


def bump(text: str) -> str:
    text = (text or "").strip().lower()
    if text in _BUMPS:
        return text
    return ""


def severity() -> str:
    text = os.environ.get("TRIVY_SEVERITY", "HIGH").strip().upper()
    if text in _SEVERITIES:
        return text
    return "HIGH"


def findings(body: dict) -> list:
    rows = []
    for item in body.get("findings") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("finding") or "").strip()
        if not text:
            continue
        filename = str(item.get("filename") or "").strip() or "module"
        rows.append({"filename": filename, "finding": text})
    return rows


def status(body: dict, good: str, bad: str) -> tuple[str, list]:
    rows = findings(body)
    label = str(body.get("status") or bad)
    if label not in {good, bad}:
        label = bad
    if rows:
        label = bad
    return label, rows


def stopped(filename: str) -> tuple[str, list]:
    return "fail", [
        {
            "filename": filename,
            "finding": "Stopped early. The module is larger than this pass can read.",
        }
    ]


def apply_files(state: dict) -> tuple[list[str], list[str]]:
    """Files a finding names, interface then security then release. At most 10 are applied."""
    ordered = []
    for key in _FINDING_KEYS:
        for item in state.get(key) or []:
            name = str(item.get("filename") or "").strip()
            text = str(item.get("finding") or "").lower()
            if not name or name in ordered:
                continue
            if "nothing new to release" in text:
                continue
            ordered.append(name)
    return ordered[:_FILE_CAP], ordered[_FILE_CAP:]


def with_security(body: str, rows: list) -> str:
    """Keep security findings in the pull request body when the model leaves them out."""
    text = (body or "").strip()
    if not text:
        return ""
    missing = []
    for item in rows or []:
        finding = str(item.get("finding") or "").strip()
        if not finding or finding in text:
            continue
        filename = str(item.get("filename") or "").strip() or "module"
        missing.append(f"- {filename}: {finding}")
    if not missing:
        return text
    return text + "\n\nSecurity\n" + "\n".join(missing)


def with_skipped(body: str, skipped: list[str]) -> str:
    if not skipped:
        return body
    note = "More recommendations were not applied:\n" + "\n".join(f"- {name}" for name in skipped)
    if body.strip():
        return body.rstrip() + "\n\n" + note
    return note


def findings_for(state: dict, names: list[str]) -> dict[str, list[str]]:
    grouped = {name: [] for name in names}
    for key in _FINDING_KEYS:
        agent = key.removesuffix("_findings")
        for item in state.get(key) or []:
            name = str(item.get("filename") or "").strip()
            text = str(item.get("finding") or "").strip()
            if name in grouped and text:
                grouped[name].append(f"{agent}: {text}")
    return grouped


def kept_files(body: dict, names: list[str]) -> tuple[list, list[str]]:
    """Proposed files that are in this list and have text. The rest are still missing."""
    allowed = set(names)
    files = []
    seen = set()
    for item in body.get("proposed_files") or []:
        name = item.get("filename")
        if name not in allowed or name in seen:
            continue
        if not str(item.get("content") or "").strip():
            continue
        files.append({"filename": name, "content": item["content"]})
        seen.add(name)
    return files, [name for name in names if name not in seen]


def recommend_text(state: dict, chosen: list[str], skipped: list[str], missing: list[str] | None = None) -> str:
    files = missing or chosen
    grouped = findings_for(state, files)
    lines = [
        f"Repo: {state.get('repo', '')}",
        f"Ref: {state.get('ref') or ''}",
        f"Interface: {state.get('interface_status', '')}",
        f"Interface findings: {state.get('interface_findings', [])}",
        f"Security: {state.get('security_status', '')}",
        f"Security findings: {state.get('security_findings', [])}",
        f"Release: {state.get('release_status', '')}",
        f"Release findings: {state.get('release_findings', [])}",
        f"Latest Published Version: {state.get('current_version', '')}",
        f"Suggested version: {state.get('suggested_version', '')}",
        f"Bump: {state.get('bump', '')}",
    ]
    if missing:
        lines.append("These files were left out of proposed_files. Return each one now.")
    lines.append("Apply changes to these files only. Read each one once. Return every one in proposed_files:")
    for name in files:
        lines.append(name)
        lines.extend(f"- {text}" for text in grouped[name])
    if missing:
        return "\n".join(lines)
    lines.extend(
        [
            "Do not read any other file.",
            "Call read_pr_template once with these template paths, in this order:",
            *_TEMPLATES,
            "Skipped files:",
            *(skipped or ["none"]),
        ]
    )
    return "\n".join(lines)


def status_text(state: dict) -> str:
    return "\n".join(
        [
            f"Interface: {state.get('interface_status', '')}",
            f"Security: {state.get('security_status', '')}",
            f"Release: {state.get('release_status', '')}",
        ]
    )
