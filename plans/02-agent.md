# 02 — Agent

## Goal

A local LangGraph app that answers a policy question, looks up a ticket, and refuses to write until a person approves. Every run shows up as a LangSmith trace.

## Maps to

Deliverable 2, the implementation half. Tracing is the start of deliverable 2's evaluation framework.

## Read first

`plans/00-scope.md` and `docs/architecture.md`. If they disagree, the architecture doc wins until you are in step 4.

## Out of scope

- Eval datasets and experiments (step 3).
- The demo script (step 4).
- A web UI.
- Deploying Agent Server to LangSmith. `langgraph dev` locally is the runtime.

## Data

Create only what the three demo paths need.

`data/docs/` — four short markdown policies, each under about 40 lines:

- refunds (window, condition, who may approve)
- shipping (lost package versus late package)
- account access (what support may reset)
- escalation (when a ticket must leave the queue)

`data/tickets.json` — eight tickets. Cover: in-window refund, out-of-window refund, lost shipment, already refunded, needs escalation, simple status lookup, unknown id, and one ambiguous customer with two open tickets. Include id, customer, status, order total, created date, and a one-line summary.

## Behaviour

One compiled graph in `src/desk/graph.py`.

State: `messages`, `intent`, `ticket_id`, `draft` (action name, ticket id, reason), `decision` (`approved` or `rejected` or empty).

Nodes:

| Node | Does | Does not |
| --- | --- | --- |
| `classify` | Sets `intent` to `question`, `lookup`, `action`, or `unclear`. Pulls a ticket id if one is present. | Call tools. |
| `docs` | Searches `data/docs` and answers with the file name it used. | See tickets. |
| `records` | Reads tickets with `get_ticket` and `search_tickets`. | Change a ticket or search docs. |
| `draft_action` | Fills `draft` for refund, escalate, or close. Checks the refund doc when the action is a refund. | Call the mutating tool. |
| `approve` | `interrupt()` with the draft. On resume, sets `decision`. | Talk to the model. |
| `execute` | If `decision` is approved, runs `apply_action` in Python and appends the result. If rejected, appends a refusal. | Run when `decision` is empty. |
| `clarify` | Asks one question when intent is unclear or two tickets match. | Guess a ticket. |

Routing is conditional edges from `classify` and from `approve`. Keep prompts in `src/desk/prompts.py`. Keep tools in `src/desk/tools.py` as plain functions over the files. Doc search can be keyword overlap. Do not add a vector database.

`apply_action` updates the in-memory ticket list for the process and returns the new status. It is not a tool on any model.

## Runtime

- `langgraph.json` pointing at the graph.
- `.env.example` with `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_ENDPOINT`, `LANGSMITH_PROJECT`, and the model env var. Do not commit `.env`.
- A CLI `python -m src.desk.cli` that takes one utterance, prints the reply, and on an interrupt prints the draft and accepts `approve` or `reject`.
- Checkpoint on a thread id so resume works. MemorySaver is fine. Mention sqlite in a comment only if you actually use it.

## Tracing

Rely on LangGraph's LangSmith integration. Set metadata on the run: `thread_id`, `intent` once known, and `prompt_version=baseline`. Step 3 needs `prompt_version` to tell the two experiments apart.

## Check by hand

Three scripted utterances, written down in a comment at the top of the CLI or in `demo/smoke.md` (a scratch list is fine; the real script is step 4):

1. A policy question whose answer is only true because of one sentence in the refund or shipping doc.
2. A lookup by ticket id.
3. A refund request that interrupts. Reject once and show the ticket unchanged. Start a new thread, approve, and show the ticket changed.

## Done when

- The three paths work from the CLI against local files.
- The refund write is impossible without a resumed interrupt. Confirm by reading the graph: no model has `apply_action`.
- One trace for each path is visible in the LangSmith project, with the graph nodes as child runs.
- `langgraph dev` starts and the same graph is visible in Studio.
- Dependencies are pinned in whatever the repo already uses; if nothing is set up yet, use `pyproject.toml` with a recent LangGraph and LangSmith.
