import os

from dotenv import load_dotenv
from langgraph.types import Command

from review.display import (
    ask_pull_request,
    follow,
    make_console,
    show_done,
    show_header,
    show_pull_request,
    show_report,
    waiting_label,
)
from review.graph import build_graph, load_model
from review.reader import GithubReader


def main() -> None:
    load_dotenv()
    model_name = os.environ.get("MODEL", "").strip()
    if not model_name:
        raise SystemExit("Set MODEL to provider:model, for example openai:gpt-4.1-mini")

    repo = os.environ.get("GITHUB_REPO", "straubt1/terraform-aws-object-storage")
    # Candidate code is the latest branch. main is not used.
    ref = os.environ.get("GITHUB_CANDIDATE_REF", "latest")
    reader = GithubReader(repo)
    app = build_graph(load_model(model_name), reader)
    config = {"configurable": {"thread_id": "review"}}
    console = make_console()
    show_header(console, repo, ref)
    follow(
        app,
        {"repo": repo, "ref": ref, "pr_url": ""},
        config,
        console,
        status=waiting_label(set()),
        steps=True,
    )

    state = app.get_state(config).values
    if state.get("error"):
        console.print(str(state["error"]), style="fail", markup=False)
        raise SystemExit(1)

    # A resume can interrupt again.
    while app.get_state(config).interrupts:
        show_report(console, app.get_state(config).values)
        show_pull_request(console, app.get_state(config).values, reader.read_file)
        answer = ask_pull_request(console)
        follow(
            app,
            Command(resume=answer),
            config,
            console,
            status="[muted]opening the pull request[/]" if answer == "yes" else None,
        )

    show_done(console, app.get_state(config).values)


if __name__ == "__main__":
    main()
