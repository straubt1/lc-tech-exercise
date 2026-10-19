import os

from dotenv import load_dotenv
from langgraph.types import Command

from review.graph import build_graph, load_model
from review.reader import GithubReader


def main() -> None:
    load_dotenv()
    model_name = os.environ.get("MODEL", "").strip()
    if not model_name:
        raise SystemExit("Set MODEL to provider:model, for example openai:gpt-4.1-mini")

    repo = os.environ.get("GITHUB_REPO", "straubt1/terraform-aws-object-storage")
    ref = os.environ.get("GITHUB_CANDIDATE_REF", "latest")
    app = build_graph(load_model(model_name), GithubReader(repo))
    config = {"configurable": {"thread_id": "review"}}
    result = app.invoke({"repo": repo, "ref": ref, "pr_url": ""}, config)
    if result.get("error"):
        raise SystemExit(result["error"])
    while result.get("__interrupt__"):
        payload = result["__interrupt__"][0].value
        print(payload["question"])
        answer = input().strip().lower()
        result = app.invoke(Command(resume=answer), config)
    print(result.get("decision", ""))
    if result.get("pr_url"):
        print(result["pr_url"])


if __name__ == "__main__":
    main()
