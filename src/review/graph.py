import os

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from review.agents.recommend import build as build_recommend
from review.agents.review import build as build_review
from review.agents.version import apply_bump
from review.agents.version import build as build_version
from review.reader import GithubReader, Reader
from review.state import State
from review.tools.github import build_tools, build_version_tools, open_pull_request


def _user_message(text: str) -> dict:
    return {"messages": [{"role": "user", "content": text}]}


_AGENT = {"recursion_limit": 30}


def _kept(findings) -> list:
    kept = []
    for item in findings or []:
        text = str(item.get("finding", "")).lower()
        if "not a finding" in text or "not a mismatch" in text:
            continue
        kept.append(item)
    return kept


def _version_findings(findings) -> list:
    kept = []
    for item in _kept(findings):
        if item.get("filename") != "CHANGELOG.md":
            continue
        if "unreleased" in str(item.get("finding", "")).lower():
            continue
        kept.append(item)
    return kept


def build_graph(model, reader: Reader, checkpointer=None, open_pr=open_pull_request):
    review_agent = build_review(model, build_tools(reader))
    version_agent = build_version(model, build_version_tools(reader))
    recommend_agent = build_recommend(model, [])

    def receive(state: State) -> dict:
        message = reader.check(state.get("repo") or "", state.get("ref") or "")
        if message:
            return {"error": message}
        return {}

    def after_input(state: State):
        if state.get("error"):
            return END
        return ["review", "version"]

    def review(state: State) -> dict:
        reader.copy_repo(state["ref"])
        result = review_agent.invoke(
            _user_message(
                f"Review repo {state['repo']} at ref {state['ref']}. "
                "Return status and findings."
            ),
            _AGENT,
        )
        body = result["structured_response"]
        findings = _kept(body.get("findings"))
        status = "fail" if findings else body.get("status", "fail")
        return {
            "review_status": status,
            "review_findings": findings,
        }

    def version(state: State) -> dict:
        result = version_agent.invoke(
            _user_message(
                f"Version repo {state['repo']} at ref {state['ref']}. "
                "Return bump, justification, versions, and findings."
            ),
            _AGENT,
        )
        body = result["structured_response"]
        tags = reader.list_release_tags()
        highest = tags[0] if tags else ""
        diff = reader.compare(highest, state["ref"]) if highest else ""
        suggested, bump, justification = apply_bump(
            body.get("bump") or "",
            body.get("justification") or "",
            highest,
            diff,
            suggested=body.get("suggested_version") or "",
        )
        return {
            "suggested_version": suggested,
            "bump": bump,
            "justification": justification,
            "versions": body["versions"],
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
        }

    def gate(state: State) -> dict:
        suggestions = state.get("suggestions", "")
        print(suggestions)
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
        )
        return {"decision": "yes", "pr_url": url}

    graph = StateGraph(State)
    graph.add_node("input", receive)
    graph.add_node("review", review)
    graph.add_node("version", version)
    graph.add_node("recommend", recommend)
    graph.add_node("gate", gate)
    graph.add_edge(START, "input")
    graph.add_conditional_edges("input", after_input)
    graph.add_edge("review", "recommend")
    graph.add_edge("version", "recommend")
    graph.add_edge("recommend", "gate")
    graph.add_edge("gate", END)
    return graph.compile(
        checkpointer=checkpointer or InMemorySaver(),
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
graph = build_graph(
    load_model(os.environ.get("MODEL", "").strip() or "openai:gpt-4.1-mini"),
    GithubReader(os.environ.get("GITHUB_REPO", "straubt1/terraform-aws-object-storage")),
)
