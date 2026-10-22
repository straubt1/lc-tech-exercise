import os
import re

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from review.agents.interface import build as build_interface
from review.agents.recommend import build as build_recommend
from review.agents.release import build as build_release
from review.agents.security import build as build_security
from review.reader import GithubReader, Reader
from review.state import State
from review.tools.checks import (
    build_interface_tools,
    build_release_tools,
    build_security_tools,
)
from review.tools.github import build_recommend_tools, open_pull_request

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
_AGENT = {"recursion_limit": 80}

# Default means the CLI and tests get an in-memory saver. None means no saver,
# which is what LangGraph dev requires so it can attach its own.
_DEFAULT_SAVER = object()


def _user_message(text: str) -> dict:
    return {"messages": [{"role": "user", "content": text}]}


def _no_changes(diff: str) -> bool:
    if "compare not found" in diff:
        return False
    return any(line.strip() == "no changes" for line in diff.splitlines())


def _version(text: str) -> str:
    text = " ".join((text or "").split())
    if not _VERSION.fullmatch(text):
        return text
    if text.startswith("v"):
        return text
    return "v" + text


def _pull_version(state: State) -> str:
    """Branch name uses the recommended version, or the current tag when there is no bump."""
    version = str(state.get("suggested_version") or "").strip()
    if version and version != "none":
        return version
    return str(state.get("current_version") or "").strip()


def _released(status: str, findings: list, suggested: str, bump: str, current: str) -> dict:
    if bump == "none":
        suggested = "none"
    return {
        "release_status": status,
        "release_findings": findings,
        "current_version": current,
        "suggested_version": suggested,
        "bump": bump,
    }


def _bump(text: str) -> str:
    text = (text or "").strip().lower()
    if text in _BUMPS:
        return text
    return ""


def _severity() -> str:
    text = os.environ.get("TRIVY_SEVERITY", "HIGH").strip().upper()
    if text in _SEVERITIES:
        return text
    return "HIGH"


def _findings(body: dict) -> list:
    findings = []
    for item in body.get("findings") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("finding") or "").strip()
        if not text:
            continue
        filename = str(item.get("filename") or "").strip() or "module"
        findings.append({"filename": filename, "finding": text})
    return findings


def _status(body: dict, good: str, bad: str) -> tuple[str, list]:
    findings = _findings(body)
    status = str(body.get("status") or bad)
    if status not in {good, bad}:
        status = bad
    if findings:
        status = bad
    return status, findings


def _invoke(agent, text: str):
    try:
        result = agent.invoke(_user_message(text), _AGENT)
    except GraphRecursionError:
        return None
    return result.get("structured_response") or {}


def _stopped(filename: str) -> tuple[str, list]:
    return "fail", [
        {
            "filename": filename,
            "finding": "Stopped early. The module is larger than this pass can read.",
        }
    ]


def _apply_files(state: State) -> tuple[list[str], list[str]]:
    """Files a finding names, interface then security then release. At most 10 are applied."""
    ordered = []
    for key in ("interface_findings", "security_findings", "release_findings"):
        for item in state.get(key) or []:
            name = str(item.get("filename") or "").strip()
            finding = str(item.get("finding") or "").lower()
            if not name or name in ordered:
                continue
            if "nothing new to release" in finding:
                continue
            ordered.append(name)
    return ordered[:_FILE_CAP], ordered[_FILE_CAP:]


def _with_security(body: str, findings: list) -> str:
    """Keep security findings in the pull request body when the model leaves them out."""
    text = (body or "").strip()
    if not text:
        return ""
    missing = []
    for item in findings or []:
        finding = str(item.get("finding") or "").strip()
        if not finding or finding in text:
            continue
        filename = str(item.get("filename") or "").strip() or "module"
        missing.append(f"- {filename}: {finding}")
    if not missing:
        return text
    return text + "\n\nSecurity\n" + "\n".join(missing)


def _with_skipped(body: str, skipped: list[str]) -> str:
    if not skipped:
        return body
    note = "More recommendations were not applied:\n" + "\n".join(f"- {name}" for name in skipped)
    if body.strip():
        return body.rstrip() + "\n\n" + note
    return note


def _findings_for(state: State, names: list[str]) -> dict[str, list[str]]:
    grouped = {name: [] for name in names}
    for key in ("interface_findings", "security_findings", "release_findings"):
        for item in state.get(key) or []:
            name = str(item.get("filename") or "").strip()
            text = str(item.get("finding") or "").strip()
            if name in grouped and text:
                grouped[name].append(text)
    return grouped


def _kept_files(body: dict, names: list[str]) -> tuple[list, list[str]]:
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


def _recommend_text(state: State, chosen: list[str], skipped: list[str], missing: list[str] | None = None) -> str:
    files = missing or chosen
    grouped = _findings_for(state, files)
    ref = state.get("ref") or ""
    lines = [
        f"Repo: {state.get('repo', '')}",
        f"Ref: {ref}",
        f"Interface: {state.get('interface_status', '')}",
        f"Interface findings: {state.get('interface_findings', [])}",
        f"Security: {state.get('security_status', '')}",
        f"Security findings: {state.get('security_findings', [])}",
        f"Release: {state.get('release_status', '')}",
        f"Release findings: {state.get('release_findings', [])}",
        f"Current version: {state.get('current_version', '')}",
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


def _status_text(state: State) -> str:
    return "\n".join(
        [
            f"Interface: {state.get('interface_status', '')}",
            f"Security: {state.get('security_status', '')}",
            f"Release: {state.get('release_status', '')}",
        ]
    )


def build_graph(model, reader: Reader, checkpointer=_DEFAULT_SAVER, open_pr=open_pull_request):
    held: dict = {}
    allowed: dict = {"files": set()}
    interface_agent = build_interface(model, build_interface_tools(reader))
    security_agent = build_security(model, build_security_tools(reader))
    release_agent = build_release(model, build_release_tools(held))
    recommend_agent = build_recommend(model, build_recommend_tools(reader, allowed))

    def check(state: State) -> dict:
        message = reader.check(state.get("repo") or "", state.get("ref") or "")
        if message:
            return {"error": message}
        return {}

    def after_check(state: State):
        if state.get("error"):
            return END
        return ["interface", "security", "release"]

    def interface(state: State) -> dict:
        repo = state.get("repo") or ""
        ref = state.get("ref") or ""
        body = _invoke(
            interface_agent,
            "\n".join(
                [
                    f"Review the interface of {repo} at ref {ref}.",
                    f"Call terraform_docs once with ref {ref}.",
                    "Return status and findings.",
                ]
            ),
        )
        if body is None:
            status, findings = _stopped("README.md")
        else:
            status, findings = _status(body, "pass", "fail")
        return {"interface_status": status, "interface_findings": findings}

    def security(state: State) -> dict:
        repo = state.get("repo") or ""
        ref = state.get("ref") or ""
        body = _invoke(
            security_agent,
            "\n".join(
                [
                    f"Review the security of {repo} at ref {ref}.",
                    f"Call trivy_config once with ref {ref}.",
                    f"The minimum severity is {_severity()}.",
                    "Return status and findings.",
                ]
            ),
        )
        if body is None:
            status, findings = _stopped("module")
        else:
            status, findings = _status(body, "pass", "fail")
        return {"security_status": status, "security_findings": findings}

    def release(state: State) -> dict:
        ref = state.get("ref") or ""
        try:
            tags = list(reader.list_release_tags())
        except RuntimeError as exc:
            return _released(
                "not ready",
                [{"filename": "CHANGELOG.md", "finding": str(exc)}],
                "",
                "",
                "",
            )
        latest = tags[0] if tags else ""
        diff = reader.compare(latest, ref) if latest else ""
        held["release_tags"] = tags
        held["diff"] = diff
        if latest and _no_changes(diff):
            return _released(
                "not ready",
                [
                    {
                        "filename": "CHANGELOG.md",
                        "finding": f"Nothing new to release since {latest}.",
                    }
                ],
                "none",
                "none",
                latest,
            )
        repo = state.get("repo") or ""
        body = _invoke(
            release_agent,
            "\n".join(
                [
                    f"Decide if {repo} at ref {ref} is ready for a release.",
                    "Call get_last_release_tag, then get_diff_since_last_release.",
                    "When bump is none, suggested_version is none.",
                    "Return status, suggested_version, bump, and findings.",
                ]
            ),
        )
        if body is None:
            return _released(
                "not ready",
                [
                    {
                        "filename": "CHANGELOG.md",
                        "finding": "Stopped early. The module is larger than this pass can read.",
                    }
                ],
                "",
                "",
                latest,
            )
        status, findings = _status(body, "ready", "not ready")
        bump = _bump(body.get("bump") or "")
        return _released(status, findings, _version(body.get("suggested_version") or ""), bump, latest)

    def recommend(state: State) -> dict:
        chosen, skipped = _apply_files(state)
        allowed["files"] = set(chosen)
        body = _invoke(recommend_agent, _recommend_text(state, chosen, skipped)) or {}
        files, missing = _kept_files(body, chosen)
        if missing:
            allowed["files"] = set(missing)
            again = _invoke(recommend_agent, _recommend_text(state, chosen, skipped, missing)) or {}
            extra, _missing = _kept_files(again, missing)
            files.extend(extra)
        return {
            "suggestions": body.get("suggestions") or "",
            "proposed_files": files,
            "pr_title": body.get("pr_title") or "",
            "pr_body": body.get("pr_body") or "",
        }

    def gate(state: State) -> dict:
        answer = interrupt(
            {
                "question": "Create a pull request with these suggestions? (yes/no)",
                "suggestions": state.get("suggestions", ""),
            }
        )
        if str(answer).strip().lower() != "yes":
            return {"decision": "no"}
        chosen, skipped = _apply_files(state)
        allowed_files = set(chosen)
        files = [
            item
            for item in state.get("proposed_files") or []
            if item.get("filename") in allowed_files
        ]
        left_out = [name for name in chosen if name not in {item.get("filename") for item in files}]
        skipped = [*skipped, *left_out]
        if not files:
            return {"decision": "yes"}
        findings = [
            *(state.get("interface_findings") or []),
            *(state.get("security_findings") or []),
            *(state.get("release_findings") or []),
        ]
        body = _with_security(state.get("pr_body") or "", state.get("security_findings") or [])
        url = open_pr(
            repo=state["repo"],
            base=state["ref"],
            suggested_version=_pull_version(state),
            status=_status_text(state),
            findings=findings,
            proposed_files=files,
            title=state.get("pr_title") or "",
            body=_with_skipped(body, skipped),
        )
        return {"decision": "yes", "pr_url": url}

    graph = StateGraph(State)
    graph.add_node("check", check)
    graph.add_node("interface", interface)
    graph.add_node("security", security)
    graph.add_node("release", release)
    graph.add_node("recommend", recommend)
    graph.add_node("gate", gate)
    graph.add_edge(START, "check")
    graph.add_conditional_edges(
        "check",
        after_check,
        ["interface", "security", "release", END],
    )
    graph.add_edge("interface", "recommend")
    graph.add_edge("security", "recommend")
    graph.add_edge("release", "recommend")
    graph.add_edge("recommend", "gate")
    graph.add_edge("gate", END)
    if checkpointer is _DEFAULT_SAVER:
        checkpointer = InMemorySaver()
    return graph.compile(
        checkpointer=checkpointer,
        name="module_review",
    )


def load_model(name: str):
    provider, _, _model = name.partition(":")
    kwargs = {}
    if provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        kwargs["api_key"] = "not-used-until-invoke"
    if provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        kwargs["api_key"] = "not-used-until-invoke"
    return init_chat_model(name, timeout=90, max_retries=1, **kwargs)


load_dotenv()
# No checkpointer here. `langgraph dev` rejects InMemorySaver and attaches its own.
graph = build_graph(
    load_model(os.environ.get("MODEL", "").strip() or "openai:gpt-4.1-mini"),
    GithubReader(os.environ.get("GITHUB_REPO", "straubt1/terraform-aws-object-storage")),
    checkpointer=None,
)
