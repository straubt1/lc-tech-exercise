# Standard-library access to environment variables such as MODEL and GITHUB_REPO.
import os

# Reads a local .env file into the environment. Existing variables are left as they are.
from dotenv import load_dotenv

# Command is how a paused graph is resumed. resume carries the yes or no answer.
from langgraph.types import Command

# Terminal layout: header, live progress, the suggestions report, and the final line.
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

# build_graph wires the agents. load_model turns MODEL into a chat model.
from review.graph import build_graph, load_model

# GithubReader is the live GitHub client the agents use to read the module.
from review.reader import GithubReader


def main() -> None:
    # Pull MODEL, keys, and repo settings from .env when they are not already set.
    load_dotenv()

    # MODEL is provider:model, for example openai:gpt-4.1-mini. Blank means unset.
    model_name = os.environ.get("MODEL", "").strip()

    # The agents cannot run without a model, so stop here with a usage line.
    if not model_name:
        raise SystemExit("Set MODEL to provider:model, for example openai:gpt-4.1-mini")

    # Which module to review. Defaults to the public object-storage module.
    repo = os.environ.get("GITHUB_REPO", "straubt1/terraform-aws-object-storage")

    # Which git ref to review. Candidate code is the latest branch, not main.
    ref = os.environ.get("GITHUB_CANDIDATE_REF", "latest")

    # One reader. The checks read the module. Release loads the tag and the diff.
    reader = GithubReader(repo)

    # Build the graph: check the ref, three checks in parallel, recommend, then the gate.
    app = build_graph(load_model(model_name), reader)

    # thread_id names the checkpoint. The same id is required to resume after the question.
    config = {"configurable": {"thread_id": "review"}}

    # Rich console. Colors stay off when output is not a terminal.
    console = make_console()

    # Print the repo and ref once, before any agent starts.
    show_header(console, repo, ref)

    # Stream the graph. steps prints a line as each check finishes.
    # The spinner names the checks still running, then recommend.
    # pr_url starts empty. The gate fills it only after a yes.
    follow(
        app,
        {"repo": repo, "ref": ref, "pr_url": ""},
        config,
        console,
        status=waiting_label(set()),
        steps=True,
    )

    # Read the checkpoint. This is the state after the graph paused or finished.
    state = app.get_state(config).values

    # Enrich failed, usually because the repo or ref does not exist.
    if state.get("error"):
        # Print the reader error in red. markup=False so brackets in the message stay literal.
        console.print(str(state["error"]), style="fail", markup=False)

        # Exit with a failure status. Nothing is left to ask.
        raise SystemExit(1)

    # The gate calls interrupt, so the graph is paused until a person answers.
    # The loop runs once for this graph. It exists because a resume can interrupt again.
    while app.get_state(config).interrupts:
        # Print status, version, findings, and proposed files from the checkpoint.
        show_report(console, app.get_state(config).values)

        # Print the pull request title, then each file with its added and removed counts.
        show_pull_request(console, app.get_state(config).values, reader.read_file)

        # Ask yes or no. Enter, with nothing typed, means no.
        answer = ask_pull_request(console)

        # Resume the gate. yes opens the pull request. no stores the decision and ends.
        # The spinner is shown only for yes, because opening the pull request calls GitHub.
        follow(
            app,
            Command(resume=answer),
            config,
            console,
            status="[muted]opening the pull request[/]" if answer == "yes" else None,
        )

    # Print the pull request URL, or a line saying one was not opened.
    show_done(console, app.get_state(config).values)


# Run main only when this file is the program, as in `uv run python -m review`.
if __name__ == "__main__":
    main()
