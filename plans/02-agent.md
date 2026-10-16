# 02 — Agent

## Goal

A local LangGraph app that classifies a real FastAPI issue, retrieves grounding from that repo, drafts a reply, and refuses to post until a person approves or edits. Every run is a LangSmith trace. The only GitHub write is to the private sink repo, after resume.

## Maps to

Assignment Part 2, the implementation half. Tracing is the start of the evaluation framework.

## Read first

`plans/00-scope.md` and `docs/architecture.md`. If they disagree, the architecture doc wins until step 4.

## Out of scope

- Building the gold dataset and the experiment (step 3). A handful of live issues for the smoke test is in scope.
- The demo script (step 4).
- A web UI. CLI and `langgraph dev` only.
- Deploying Agent Server. Phase 2 in the architecture doc stays a diagram.
- Any write to `fastapi/fastapi`.

## GitHub access

`.env.example` lists `GITHUB_TOKEN` and `GITHUB_SINK_REPO`. Do not commit `.env`.

Token: classic or fine-grained PAT. Read access to public repositories. Write access to issues on the sink repo only. Nothing else.

`GITHUB_SINK_REPO` is `owner/name` of a private repo you create for this exercise. Finalize opens one issue there. Title is the source title. Body is the final reply, the source issue URL, the category, and the escalation flag. It does not comment on the source.

Cache every read under `data/cache/`, keyed by URL, and commit the cache. A second run of the same issue must not depend on GitHub being up. Respect secondary rate limits with a short backoff. Do not build a general GitHub client beyond the two tools below.

## Tools

Plain functions in `src/triage/tools.py`. Only the retrieve node gets them.

- `fetch_repo_docs(path)` — Contents API. Start from `README.md`. List `docs/` once, then fetch at most three pages whose path overlaps the issue text. Refuse paths outside that allowlist.
- `search_similar_issues(query)` — Search API, `repo:fastapi/fastapi is:issue is:closed`, exclude the current number, return three hits. For each hit, fetch the first comment whose author is a MEMBER or COLLABORATOR and not a bot. Truncate bodies. If the best hit is clearly the same report, set `possible_duplicate_of` to that number.

Cap the retrieve node at four tool calls.

## Behaviour

One compiled graph in `src/triage/graph.py`. State is the `TriageState` in `00-scope.md`. Gold labels are not fields on it.

| Node | Does | Does not |
| --- | --- | --- |
| `classify` | One structured call. Sets `category` and `classification_confidence`. | Call tools, or see labels. |
| `retrieve` | Fills `retrieved_context` and maybe `possible_duplicate_of`. | Draft the reply, or write. |
| `draft` | Writes `draft_response`, `needs_escalation`, `escalation_reason`. On a redraft, reads the rejection notes and increments `revision_count` before writing. | Call tools, or post. |
| `review` | `interrupt()` with the draft, the category, the confidence, the duplicate hint, and the escalation flag. On resume, sets `human_decision` and, for an edit, `human_edited_text`. | Call the model. |
| `finalize` | On `approved`, posts `draft_response`. On `edited`, posts `human_edited_text`. Sets `final_response` and `sink_issue_url`. | Run unless the decision is one of those two. Never target the source repo. |

Routing matches `00-scope.md`. Reject with `revision_count >= 2` ends with no post. Prompts live in `src/triage/prompts.py`.

Draft voice: a FastAPI maintainer's first public reply. Short. Every factual claim cites a doc path or a closed issue number that appears in `retrieved_context`. If the context does not support an answer, ask for the missing detail instead of inventing it. Set `needs_escalation` for a vulnerability report, a pasted secret, abusive tone, or a question the context cannot answer.

`prompt_version=grounded` on these runs. Step 3 adds the empty-retriever variant.

## Runtime

- `langgraph.json` pointing at the graph.
- `.env.example` with `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_ENDPOINT`, `LANGSMITH_PROJECT=triage`, `MODEL`, the provider key name, `GITHUB_TOKEN`, `GITHUB_SINK_REPO`.
- Update the local `.env` project name to `triage` if it still says `northwind-desk`. Do not commit it. Do not print the key.
- CLI: `python -m src.triage.cli ISSUE_NUMBER`. It prints category, duplicate hint, escalation flag, and draft. On the interrupt it accepts `approve`, `edit`, or `reject`. `edit` reads the replacement text. `reject` reads a one-line note and resumes the same thread. MemorySaver is the checkpointer. A thread id is printed so you can explain resume.
- When the CLI finishes a review, append one JSON line to `data/reviews.jsonl` with the thread id, decision, and both texts. Step 3's edit-distance script reads that file. It can be empty until you review something.

## Tracing

Use LangGraph's LangSmith integration. Metadata on the run: `thread_id`, `issue_number`, `category` once known, `prompt_version`.

If a framework behavior blocks you (interrupt payload shape, structured output, Studio resume), append a dated note to `docs/friction-log.md`. Do not file that note as a code comment only.

## Check by hand

Write the three issue numbers you used at the top of the CLI module or in `demo/smoke.md`.

1. A docs or usage question whose correct reply depends on a sentence in the fetched docs. Show the citation in the draft.
2. A bug that should surface a similar closed issue.
3. A full approve on a non-escalation issue: sink repo gains one issue, source repo is unchanged. Then a new thread you reject once: no sink issue for that thread. Then an edit: the sink body is your text, not the original draft.

## Done when

- The three paths work from the CLI, reads come from GitHub or the cache, and the write target is only `GITHUB_SINK_REPO`.
- Reading the graph shows no model bound to the write, and `finalize` is unreachable without a resumed interrupt.
- One trace per path is in the `triage` project, with the nodes as child runs.
- `langgraph dev` starts and Studio shows the same graph, including the pause.
- Dependencies are pinned in `pyproject.toml` if the repo does not already pin them.
