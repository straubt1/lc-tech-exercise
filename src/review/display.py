"""Terminal layout for a review run.

A few colors only: cyan for versions, green for pass and ready, red for fail
and not ready, yellow for the pull-request question. Everything else stays dim.
"""

import difflib

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
        "ask": "bold yellow",
        "muted": "dim",
    }
)

_STEPS = ("interface", "security", "release")


def _proposed(state: dict) -> list[dict]:
    files = []
    seen = set()
    for item in state.get("proposed_files") or []:
        filename = str(item.get("filename") or "")
        if not filename or filename in seen:
            continue
        seen.add(filename)
        files.append(item)
    return files


def make_console(**kwargs) -> Console:
    options = {"theme": THEME, "highlight": False}
    options.update(kwargs)
    return Console(**options)


def show_header(console: Console, repo: str, ref: str) -> None:
    console.print(Text.assemble((repo, "bold"), ("  ", ""), (ref, "muted")))
    console.print()


def _names(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{names[0]}, {names[1]}, and {names[2]}"


def waiting_label(done: set[str]) -> str:
    left = [name for name in _STEPS if name not in done]
    if not left:
        return "[muted]recommend[/]"
    return "[muted]" + _names(left) + "[/]"


def _style(status: str) -> str:
    return "pass" if status in {"pass", "ready"} else "fail"


def _count(count: int) -> str:
    if count == 0:
        return "no findings"
    if count == 1:
        return "1 finding"
    return f"{count} findings"


def _version_line(data: dict) -> Text:
    text = Text()
    current = str(data.get("current_version") or "").strip()
    suggested = str(data.get("suggested_version") or "").strip()
    bump = str(data.get("bump") or "").strip()
    if current:
        text.append("Current Version ", style="muted")
        text.append(current, style="version")
    if suggested:
        if text.plain:
            text.append("   ")
        text.append("Recommended Version ", style="muted")
        text.append(suggested, style="version")
        if bump and bump != "none":
            text.append("   ")
            text.append(bump, style="muted")
    return text


def show_step(console: Console, name: str, data: dict) -> None:
    if name in {"interface", "security"}:
        status = str(data.get(f"{name}_status") or "")
        count = len(data.get(f"{name}_findings") or [])
        console.print(
            Text.assemble(
                (name.ljust(10), "agent"),
                (status, _style(status)),
                ("   ", ""),
                (_count(count), "muted"),
            )
        )
        return
    if name == "release":
        status = str(data.get("release_status") or "")
        console.print(
            Text.assemble(
                (name.ljust(10), "agent"),
                (status, _style(status)),
                ("   ", ""),
                _version_line(data),
            )
        )


def show_report(console: Console, state: dict) -> None:
    console.print()
    console.rule("suggestions", style="muted", align="left")
    facts = Table(box=None, show_header=False, pad_edge=False, padding=(0, 2, 0, 0))
    facts.add_column(style="muted", min_width=10)
    facts.add_column()
    for name in ("interface", "security"):
        status = str(state.get(f"{name}_status") or "")
        facts.add_row(name, Text(status, style=_style(status)))
    release = str(state.get("release_status") or "")
    facts.add_row("release", Text(release, style=_style(release)))
    current = str(state.get("current_version") or "").strip()
    suggested = str(state.get("suggested_version") or "").strip()
    bump = str(state.get("bump") or "").strip()
    if current:
        facts.add_row("Current Version", Text(current, style="version"))
    if suggested:
        recommended = Text(suggested, style="version")
        if bump and bump != "none":
            recommended.append("  ")
            recommended.append(bump, style="muted")
        facts.add_row("Recommended Version", recommended)
    console.print(facts)

    console.print()
    console.print("findings", style="bold")
    findings = [
        *(state.get("interface_findings") or []),
        *(state.get("security_findings") or []),
        *(state.get("release_findings") or []),
    ]
    visible = [
        (str(item.get("filename") or ""), str(item.get("finding") or "").strip())
        for item in findings
        if str(item.get("finding") or "").strip()
    ]
    if not visible:
        console.print("  none", style="muted")
    for index, (filename, text) in enumerate(visible):
        if index:
            console.print()
        console.print(Text("  " + filename, style="bold"))
        console.print(Padding(Text(text), (0, 0, 0, 4)))

    console.print()
    console.print("proposed", style="bold")
    names = [str(item.get("filename") or "") for item in _proposed(state)]
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
    files = _proposed(state)
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
    """Stream the graph. With steps, print a line as each check finishes."""
    done: set[str] = set()
    with _Spinner(console, status or "") as spin:
        for chunk in app.stream(payload, config, stream_mode="updates"):
            if not isinstance(chunk, dict):
                continue
            for name, data in chunk.items():
                if not steps or name not in _STEPS or not isinstance(data, dict):
                    continue
                show_step(console, name, data)
                done.add(name)
                spin.update(waiting_label(done))
