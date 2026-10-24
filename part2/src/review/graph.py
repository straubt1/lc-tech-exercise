import os

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
from review.normalize import (
    apply_files,
    bump,
    kept_files,
    no_changes,
    pull_version,
    recommend_text,
    released,
    severity,
    status,
    status_text,
    stopped,
    version,
    with_security,
    with_skipped,
)
from review.reader import GithubReader, Reader
from review.state import State
from review.tools.checks import (
    build_interface_tools,
    build_release_tools,
    build_security_tools,
)
from review.tools.github import build_recommend_tools, open_pull_request

_AGENT = {"recursion_limit": 40}

# Default means the CLI and tests get an in-memory saver. None means no saver,
# which is what LangGraph dev requires so it can attach its own.
_DEFAULT_SAVER = object()


def invoke(agent, text: str):
    try:
        result = agent.invoke({"messages": [{"role": "user", "content": text}]}, _AGENT)
    except GraphRecursionError:
        return None
    return result.get("structured_response") or {}


def review_status(agent, text: str, good: str, bad: str, stopped_file: str) -> tuple[str, list]:
    body = invoke(agent, text)
    if body is None:
        return stopped(stopped_file)
    return status(body, good, bad)


def run_check(state: State, reader: Reader) -> dict:
    message = reader.check(state.get("repo") or "", state.get("ref") or "")
    if message:
        return {"error": message}
    return {}


def after_check(state: State):
    if state.get("error"):
        return END
    return ["interface", "security", "release"]


def run_interface(state: State, agent) -> dict:
    repo = state.get("repo") or ""
    ref = state.get("ref") or ""
    label, rows = review_status(
        agent,
        "\n".join(
            [
                f"Review the interface of {repo} at ref {ref}.",
                f"Call terraform_docs once with ref {ref}.",
                "Return status and findings.",
            ]
        ),
        "pass",
        "fail",
        "README.md",
    )
    return {"interface_status": label, "interface_findings": rows}


def run_security(state: State, agent) -> dict:
    repo = state.get("repo") or ""
    ref = state.get("ref") or ""
    label, rows = review_status(
        agent,
        "\n".join(
            [
                f"Review the security of {repo} at ref {ref}.",
                f"Call trivy_config once with ref {ref}.",
                f"The minimum severity is {severity()}.",
                "Return status and findings.",
            ]
        ),
        "pass",
        "fail",
        "module",
    )
    return {"security_status": label, "security_findings": rows}


def run_release(state: State, agent, reader: Reader, held: dict) -> dict:
    ref = state.get("ref") or ""
    try:
        tags = list(reader.list_release_tags())
    except RuntimeError as exc:
        return released(
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
    if latest and no_changes(diff):
        return released(
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
    held["changelog"] = reader.read_file("CHANGELOG.md", ref)
    repo = state.get("repo") or ""
    body = invoke(
        agent,
        "\n".join(
            [
                f"Decide if {repo} at ref {ref} is ready for a release.",
                "Call get_last_release_tag, then get_diff_since_last_release.",
                "Read the top CHANGELOG.md heading and its unpublished notes from that tool.",
                "Compare those notes to the diff.",
                "When that heading is the suggested version, the heading check reports nothing.",
                "When the diff has changes, suggested_version is the next version, not none.",
                "The finding names that version as the new changelog heading, such as ## v1.0.2.",
                "When bump is none, suggested_version is none.",
                "Return status, suggested_version, bump, and findings.",
            ]
        ),
    )
    if body is None:
        return released(
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
    label, rows = status(body, "ready", "not ready")
    suggested = version(body.get("suggested_version") or "")
    chosen = bump(body.get("bump") or "")
    return released(label, rows, suggested, chosen, latest)


def run_recommend(state: State, agent, allowed: dict) -> dict:
    chosen, skipped = apply_files(state)
    allowed["files"] = set(chosen)
    body = invoke(agent, recommend_text(state, chosen, skipped)) or {}
    files, missing = kept_files(body, chosen)
    if missing:
        allowed["files"] = set(missing)
        again = invoke(agent, recommend_text(state, chosen, skipped, missing)) or {}
        extra, _missing = kept_files(again, missing)
        files.extend(extra)
    return {
        "suggestions": body.get("suggestions") or "",
        "proposed_files": files,
        "pr_title": body.get("pr_title") or "",
        "pr_body": body.get("pr_body") or "",
    }


def run_gate(state: State, answer, open_pr) -> dict:
    if str(answer).strip().lower() != "yes":
        return {"decision": "no"}
    chosen, skipped = apply_files(state)
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
    rows = [
        *(state.get("interface_findings") or []),
        *(state.get("security_findings") or []),
        *(state.get("release_findings") or []),
    ]
    body = with_security(state.get("pr_body") or "", state.get("security_findings") or [])
    url = open_pr(
        repo=state["repo"],
        base=state["ref"],
        suggested_version=pull_version(state),
        status=status_text(state),
        findings=rows,
        proposed_files=files,
        title=state.get("pr_title") or "",
        body=with_skipped(body, skipped),
    )
    return {"decision": "yes", "pr_url": url}


def build_graph(model, reader: Reader, checkpointer=_DEFAULT_SAVER, open_pr=open_pull_request):
    held: dict = {}
    allowed: dict = {"files": set()}
    interface_agent = build_interface(model, build_interface_tools(reader))
    security_agent = build_security(model, build_security_tools(reader))
    release_agent = build_release(model, build_release_tools(held))
    recommend_agent = build_recommend(model, build_recommend_tools(reader, allowed))

    def check(state: State) -> dict:
        return run_check(state, reader)

    def interface(state: State) -> dict:
        return run_interface(state, interface_agent)

    def security(state: State) -> dict:
        return run_security(state, security_agent)

    def release(state: State) -> dict:
        return run_release(state, release_agent, reader, held)

    def recommend(state: State) -> dict:
        return run_recommend(state, recommend_agent, allowed)

    def gate(state: State) -> dict:
        answer = interrupt(
            {
                "question": "Create a pull request with these suggestions? (yes/no)",
                "suggestions": state.get("suggestions", ""),
            }
        )
        return run_gate(state, answer, open_pr)

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
