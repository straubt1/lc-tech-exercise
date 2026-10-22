import os

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from review.agents.recommend import build as build_recommend
from review.agents.review import build as build_review
from review.agents.version import apply_bump, release_brief
from review.agents.version import build as build_version
from review.reader import GithubReader, Reader
from review.state import State
from review.tools.github import (
    build_recommend_tools,
    build_tools,
    build_version_tools,
    open_pull_request,
)


def _user_message(text: str) -> dict:
    return {"messages": [{"role": "user", "content": text}]}


_AGENT = {"recursion_limit": 80}


def _kept(findings) -> list:
    kept = []
    for item in findings or []:
        text = str(item.get("finding", "")).lower()
        if "not a finding" in text or "not a mismatch" in text:
            continue
        kept.append(item)
    return kept


def _with_published(reported, tags: list[str]) -> list:
    found = {}
    order = []
    for item in reported or []:
        if not isinstance(item, dict):
            continue
        version = str(item.get("version") or "").strip()
        if not version or version in found:
            continue
        found[version] = {
            "version": version,
            "published": bool(item.get("published")),
            "source": str(item.get("source") or ""),
        }
        order.append(version)
    for tag in tags:
        current = found.get(tag)
        if current is None:
            found[tag] = {"version": tag, "published": True, "source": "tag"}
            order.append(tag)
            continue
        current["published"] = True
        parts = [part.strip() for part in current["source"].split(",") if part.strip()]
        if "tag" not in parts:
            parts.insert(0, "tag")
        current["source"] = ", ".join(parts)
    rest = [version for version in order if version not in set(tags)]
    return [found[version] for version in [*tags, *rest]]


def _review_message(repo: str, ref: str, tags: list[str]) -> str:
    latest = tags[0] if tags else ""
    lines = [
        f"Review repo {repo} at ref {ref}.",
        "Published versions:",
        *tags,
        f"Latest published version: {latest}" if latest else "Latest published version: none",
        "The latest published version is the first entry. Return status and findings.",
    ]
    return "\n".join(lines)


def _version_findings(findings) -> list:
    kept = []
    for item in _kept(findings):
        if item.get("filename") != "CHANGELOG.md":
            continue
        if "unreleased" in str(item.get("finding", "")).lower():
            continue
        kept.append(item)
    return kept


# Default means the CLI and tests get an in-memory saver. None means no saver,
# which is what LangGraph dev requires so it can attach its own.
_DEFAULT_SAVER = object()


def build_graph(model, reader: Reader, checkpointer=_DEFAULT_SAVER, open_pr=open_pull_request):
    review_agent = build_review(model, build_tools(reader))
    version_agent = build_version(model, build_version_tools(reader))
    recommend_agent = build_recommend(model, build_recommend_tools(reader))

    def enrich(state: State) -> dict:
        message = reader.check(state.get("repo") or "", state.get("ref") or "")
        if message:
            return {"error": message}
        try:
            tags = list(reader.list_release_tags())
        except RuntimeError as exc:
            return {"error": str(exc)}
        return {"release_tags": tags}

    def after_enrich(state: State):
        if state.get("error"):
            return END
        return ["review", "version"]

    def review(state: State) -> dict:
        reader.copy_repo(state["ref"])
        tags = list(state.get("release_tags") or [])
        try:
            result = review_agent.invoke(
                _user_message(
                    _review_message(state.get("repo") or "", state.get("ref") or "", tags)
                ),
                _AGENT,
            )
        except GraphRecursionError:
            return {
                "review_status": "fail",
                "review_findings": [
                    {
                        "filename": state.get("repo") or "review",
                        "finding": (
                            "Review stopped early. The module has more files "
                            "than this pass can read."
                        ),
                    }
                ],
            }
        body = result["structured_response"]
        findings = _kept(body.get("findings"))
        status = "fail" if findings else body.get("status", "fail")
        return {
            "review_status": status,
            "review_findings": findings,
        }

    def version(state: State) -> dict:
        tags = list(state.get("release_tags") or [])
        latest = tags[0] if tags else ""
        diff = reader.compare(latest, state["ref"]) if latest else ""
        result = version_agent.invoke(
            _user_message(
                release_brief(state.get("repo") or "", state.get("ref") or "", tags, diff)
            ),
            _AGENT,
        )
        body = result.get("structured_response") or {}
        suggested, bump, justification = apply_bump(
            body.get("bump") or "",
            body.get("justification") or "",
            latest,
            diff,
            suggested=body.get("suggested_version") or "",
        )
        return {
            "suggested_version": suggested,
            "bump": bump,
            "justification": justification,
            "versions": _with_published(body.get("versions"), tags),
            "version_findings": _version_findings(body.get("findings")),
        }

    def recommend(state: State) -> dict:
        status = state.get("review_status", "")
        if state.get("version_findings"):
            status = "fail"
        result = recommend_agent.invoke(
            _user_message(
                "\n".join(
                    [
                        f"Repo: {state.get('repo', '')}",
                        f"Ref: {state.get('ref', '')}",
                        f"Review status: {status}",
                        f"Review findings: {state.get('review_findings', [])}",
                        f"Suggested version: {state.get('suggested_version', '')}",
                        f"Bump: {state.get('bump', '')}",
                        f"Justification: {state.get('justification', '')}",
                        f"Versions: {state.get('versions', [])}",
                        f"Version findings: {state.get('version_findings', [])}",
                    ]
                )
            ),
            _AGENT,
        )
        body = result["structured_response"]
        return {
            "review_status": status,
            "suggestions": body["suggestions"],
            "proposed_files": body["proposed_files"],
            "pr_title": body.get("pr_title") or "",
            "pr_body": body.get("pr_body") or "",
        }

    def gate(state: State) -> dict:
        suggestions = state.get("suggestions", "")
        answer = interrupt(
            {
                "question": "Create a pull request with these suggestions? (yes/no)",
                "suggestions": suggestions,
            }
        )
        if str(answer).strip().lower() != "yes":
            return {"decision": "no"}
        files = [
            item
            for item in state.get("proposed_files") or []
            if item.get("filename") in {"README.md", "CHANGELOG.md"}
        ]
        if not files:
            return {"decision": "yes"}
        findings = [
            *(state.get("review_findings") or []),
            *(state.get("version_findings") or []),
        ]
        url = open_pr(
            repo=state["repo"],
            base=state["ref"],
            suggested_version=state.get("suggested_version", ""),
            review_status=state.get("review_status", ""),
            findings=findings,
            proposed_files=files,
            title=state.get("pr_title") or "",
            body=state.get("pr_body") or "",
        )
        return {"decision": "yes", "pr_url": url}

    graph = StateGraph(State)
    graph.add_node("enrich", enrich)
    graph.add_node("review", review)
    graph.add_node("version", version)
    graph.add_node("recommend", recommend)
    graph.add_node("gate", gate)
    graph.add_edge(START, "enrich")
    graph.add_conditional_edges(
        "enrich",
        after_enrich,
        ["review", "version", END],
    )
    graph.add_edge("review", "recommend")
    graph.add_edge("version", "recommend")
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
