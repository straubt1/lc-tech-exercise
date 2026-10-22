"""Terminal layout for a review run.

A few colors only: cyan for versions, green for pass and published, red for
fail, yellow for unpublished and the pull-request question. Everything else
stays dim or plain.
"""

import difflib
import re

from rich.console import Console
from rich.padding import Padding
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from review.tools.github import pull_request_title

THEME = Theme(
    {
        "agent": "cyan",
        "version": "cyan",
        "link": "cyan",
        "pass": "green",
        "fail": "red",
        "published": "green",
        "unpublished": "yellow",
        "ask": "bold yellow",
        "muted": "dim",
    }
)

_DOCS = {"README.md", "CHANGELOG.md"}
_VERSIONS_SHOWN = 5

_EMPTY_PHRASE = re.compile(
    r"(?i)^(?:none|n/?a|no findings?|nothing|no mismatches?|\(none\)|—|-)$"
)
_DIFFERS = re.compile(r"(?i)\b(?:differs|differ|different|mismatch(?:ed)?|incorrect|absent)\b")
_NON_FINDING = re.compile(
    r"(?i)\b(?:(?:is|are) fine|omits nothing|no extra|has no extra|nothing missing|no missing)\b"
)
_AFFIRMED_MATCH = re.compile(
    r"(?i)(?<!\bnot )(?<!n't )(?<!does not )(?<!do not )\b(?:matches|matched|match)\b"
)
_SCOPED_CHECK = re.compile(r"(?i)(Inputs|Outputs),\s*(Missing|Extra|Wrong)\s*:")
_LINE_CHECK = re.compile(
    r"(?i)^(?:[-*]\s*)?(?:(Inputs|Outputs)[:,\s]+)?(Missing|Extra|Wrong)\s*:\s*(.*?)\s*$"
)
_SECTION = re.compile(r"(?i)^(Inputs|Outputs)\s*:?\s*$")


def make_console(**kwargs) -> Console:
    options = {"theme": THEME, "highlight": False}
    options.update(kwargs)
    return Console(**options)


def show_header(console: Console, repo: str, ref: str) -> None:
    console.print(Text.assemble((repo, "bold"), ("  ", ""), (ref, "muted")))
    console.print()


def waiting_label(done: set[str]) -> str:
    if "review" in done and "version" in done:
        return "[muted]recommend[/]"
    names = [name for name in ("review", "version") if name not in done]
    return "[muted]" + " and ".join(names) + "[/]"


def show_step(console: Console, name: str, data: dict) -> None:
    if name == "review":
        status = str(data.get("review_status") or "")
        count = len(data.get("review_findings") or [])
        if count == 0:
            extra = "no findings"
        elif count == 1:
            extra = "1 finding"
        else:
            extra = f"{count} findings"
        console.print(
            Text.assemble(
                (name.ljust(9), "agent"),
                (status, "pass" if status == "pass" else "fail"),
                ("   ", ""),
                (extra, "muted"),
            )
        )
        return
    if name == "version":
        console.print(
            Text.assemble(
                (name.ljust(9), "agent"),
                (str(data.get("suggested_version") or ""), "version"),
                ("   ", ""),
                (str(data.get("bump") or ""), "muted"),
            )
        )


def _clauses(body: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in body:
        if char == "(":
            depth += 1
            current.append(char)
            continue
        if char == ")":
            if depth:
                depth -= 1
            current.append(char)
            continue
        if char in ".;" and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return [part.strip(" .;") for part in parts if part.strip(" .;")]


def _clause_is_finding(clause: str) -> bool:
    text = clause.strip(" .;")
    if not text or _EMPTY_PHRASE.fullmatch(text):
        return False
    if _DIFFERS.search(text):
        return True
    if _NON_FINDING.search(text) or _AFFIRMED_MATCH.search(text):
        return False
    return True


def _check_is_empty(body: str) -> bool:
    """A check with no names, or one that only says the values match, stays off the report."""
    text = " ".join(body.split()).strip()
    if not text:
        return True
    clauses = _clauses(text)
    return not clauses or not any(_clause_is_finding(clause) for clause in clauses)


def _finding_lines(text: str) -> list[str]:
    scoped = list(_SCOPED_CHECK.finditer(text))
    if scoped:
        lines = []
        preamble = " ".join(text[: scoped[0].start()].split()).strip()
        if preamble and not _check_is_empty(preamble):
            lines.append(preamble)
        for index, match in enumerate(scoped):
            end = scoped[index + 1].start() if index + 1 < len(scoped) else len(text)
            body = " ".join(text[match.end() : end].split()).strip().rstrip(".").strip()
            if _check_is_empty(body):
                continue
            section = match.group(1).capitalize()
            kind = match.group(2).capitalize()
            lines.append(f"{section}, {kind}: {body}")
        return lines

    raw_lines = text.splitlines()
    if not any(_LINE_CHECK.match(line.strip()) for line in raw_lines):
        stripped = text.strip()
        if not stripped or _EMPTY_PHRASE.fullmatch(stripped.rstrip(".")):
            return []
        return [stripped]

    lines = []
    section = ""
    for raw in raw_lines:
        stripped = raw.strip()
        if not stripped:
            continue
        heading = _SECTION.match(stripped)
        if heading:
            section = heading.group(1).capitalize()
            continue
        check = _LINE_CHECK.match(stripped)
        if not check:
            lines.append(stripped)
            continue
        own_section, kind, body = check.groups()
        if _check_is_empty(body):
            continue
        label_section = own_section or section
        kind_label = kind.capitalize()
        prefix = f"{label_section.capitalize()}, {kind_label}" if label_section else kind_label
        lines.append(f"{prefix}: {body.strip().rstrip('.').strip()}")
    return lines


def _other_versions(count: int) -> str:
    if count == 1:
        return "1 other version"
    return f"{count} other versions"


def show_report(console: Console, state: dict) -> None:
    console.print()
    console.rule("suggestions", style="muted", align="left")
    status = str(state.get("review_status") or "")
    version = str(state.get("suggested_version") or "")
    bump = str(state.get("bump") or "")
    version_text = Text(version, style="version")
    if bump:
        version_text.append("  ")
        version_text.append(bump, style="muted")

    facts = Table(box=None, show_header=False, pad_edge=False, padding=(0, 2, 0, 0))
    facts.add_column(style="muted", min_width=8)
    facts.add_column()
    facts.add_row("status", Text(status, style="pass" if status == "pass" else "fail"))
    facts.add_row("version", version_text)
    console.print(facts)

    justification = str(state.get("justification") or "").strip()
    if justification:
        console.print()
        console.print(Text(justification, style="muted"))

    console.print()
    console.print("versions", style="bold")
    versions = list(state.get("versions") or [])
    if not versions:
        console.print("  none", style="muted")
    else:
        shown = versions[:_VERSIONS_SHOWN]
        table = Table(box=None, show_header=False, pad_edge=False, padding=(0, 2, 0, 0))
        table.add_column(style="version")
        table.add_column()
        table.add_column(style="muted")
        for item in shown:
            published = bool(item.get("published"))
            mark = "published" if published else "unpublished"
            table.add_row(
                "  " + str(item.get("version") or ""),
                Text(mark, style="published" if published else "unpublished"),
                str(item.get("source") or ""),
            )
        console.print(table)
        hidden = len(versions) - len(shown)
        if hidden:
            console.print(Text(f"  {_other_versions(hidden)}", style="muted"))

    console.print()
    console.print("findings", style="bold")
    findings = [
        *(state.get("review_findings") or []),
        *(state.get("version_findings") or []),
    ]
    visible = []
    for item in findings:
        lines = _finding_lines(str(item.get("finding") or ""))
        if lines:
            visible.append((str(item.get("filename") or ""), lines))
    if not visible:
        console.print("  none", style="muted")
    for index, (filename, lines) in enumerate(visible):
        if index:
            console.print()
        console.print(Text("  " + filename, style="bold"))
        for line in lines:
            console.print(Padding(Text(line), (0, 0, 0, 4)))

    console.print()
    console.print("proposed", style="bold")
    names: list[str] = []
    for item in state.get("proposed_files") or []:
        filename = str(item.get("filename") or "")
        if filename in _DOCS and filename not in names:
            names.append(filename)
    if names:
        for filename in names:
            console.print(Text("  " + filename))
    else:
        console.print("  none", style="muted")
    console.print()


def _current_text(read_file, filename: str, ref: str) -> str:
    try:
        text = read_file(filename, ref)
    except Exception:
        return ""
    if not isinstance(text, str) or text.startswith("not found:"):
        return ""
    return text


def _line_counts(before: str, after: str) -> tuple[int, int]:
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        n=0,
        lineterm="",
    )
    added = 0
    removed = 0
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def show_pull_request(console: Console, state: dict, read_file) -> None:
    """Print the pull request title and each file's added and removed counts."""
    files = [
        item
        for item in state.get("proposed_files") or []
        if str(item.get("filename") or "") in _DOCS
    ]
    title = pull_request_title(
        str(state.get("pr_title") or ""),
        str(state.get("suggested_version") or ""),
        [str(item.get("filename") or "") for item in files],
    )
    console.print(Text.assemble(("pull request", "muted"), ("  ", ""), (title, "bold")))
    if not files:
        console.print("  no file changes", style="muted")
        console.print()
        return
    ref = str(state.get("ref") or "")
    for item in files:
        filename = str(item.get("filename") or "")
        added, removed = _line_counts(
            _current_text(read_file, filename, ref),
            str(item.get("content") or ""),
        )
        console.print(
            Text.assemble(
                (f"  {filename}", "bold"),
                ("  ", ""),
                (f"+{added}", "pass" if added else "muted"),
                ("  ", ""),
                (f"-{removed}", "fail" if removed else "muted"),
            )
        )
    console.print()


def ask_pull_request(console: Console, stream=None) -> str:
    answer = Prompt.ask(
        "[ask]Create a pull request with these suggestions?[/]",
        choices=["yes", "no"],
        case_sensitive=False,
        default="no",
        console=console,
        stream=stream,
    )
    return str(answer).lower()


def show_done(console: Console, state: dict) -> None:
    url = str(state.get("pr_url") or "").strip()
    console.print()
    if url:
        console.print(Text.assemble(("pull request", "muted"), ("  ", ""), (url, "link")))
        return
    if state.get("decision") == "yes":
        console.print("No pull request. Nothing to commit.", style="muted")
        return
    console.print("No pull request.", style="muted")


class _Spinner:
    def __init__(self, console: Console, text: str):
        self._status = console.status(text) if text and console.is_terminal else None

    def __enter__(self):
        if self._status is not None:
            self._status.__enter__()
        return self

    def update(self, text: str) -> None:
        if self._status is not None:
            self._status.update(text)

    def __exit__(self, exc_type, exc, tb):
        if self._status is not None:
            return self._status.__exit__(exc_type, exc, tb)
        return False


def follow(
    app,
    payload,
    config,
    console: Console,
    *,
    status: str | None = None,
    steps: bool = False,
) -> None:
    """Stream the graph. With steps, print a line as review and version finish."""
    done: set[str] = set()
    with _Spinner(console, status or "") as spin:
        for chunk in app.stream(payload, config, stream_mode="updates"):
            if not isinstance(chunk, dict):
                continue
            for name, data in chunk.items():
                if not steps or name not in {"review", "version"} or not isinstance(data, dict):
                    continue
                show_step(console, name, data)
                done.add(name)
                spin.update(waiting_label(done))
