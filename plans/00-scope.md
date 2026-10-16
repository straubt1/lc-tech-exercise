# 00 — Scope

Read this before every implementation step. Do not treat this file as a build step.

Precedence: `Take-Home Assignment.md` beats the root `README.md`. This file beats both for implementation choices. If a later step's code disagrees with this file, stop and fix the plan before widening the build.

## Two parts

**Part 1 — Platform.** A conceptual design for InnovateCorp's self-hosted LangSmith on the Kubernetes they already run. Diagrams and prose. No cluster, no Helm, no Terraform.

**Part 2 — Agent.** Triage: an agent that drafts a first reply to a GitHub issue and will not post until a person approves, edits, or rejects it.

Both parts ship. Spend more time on Part 2. Part 1 still has to be specific enough to defend in the room.

## Product

A reviewer pastes a `fastapi/fastapi` issue number. The graph:

1. Classifies the issue from title and body only.
2. Retrieves README/docs pages and similar closed issues from that same repo.
3. Drafts a reply in a maintainer voice, and flags security, leaked secrets, abuse, or "the docs do not support an answer."
4. Always pauses for a person.
5. On approve or edit, posts the final text to a **private sink repo you own**. On reject, drafts again, at most twice, then stops without posting.

The source repo is read-only. Gold labels and the real maintainer reply are eval data. They never enter a prompt.

## Changes from the first sketch

Keep the sketch except where a change makes the eval honest:

| Sketch | Plan | Why |
| --- | --- | --- |
| Categories include `duplicate` | Classifier emits `bug`, `feature`, `question`, or `docs`. Retriever may set `possible_duplicate_of`. | The classifier has no tools. Duplicate is a retrieval result, and FastAPI labels do not mark it cleanly. |
| `github_labels` on agent state | Gold labels live only on the dataset row | A field on state gets copied into prompts. Ground truth must be unreachable. |
| `evaluate(graph.invoke)` end to end | Eval target runs until the interrupt and returns the draft | `invoke` on a graph that always interrupts never returns a final post. Evals must not post. |
| Human-edit distance inside the experiment | Live metric from real review sessions | A historical dataset has no reviewer. Faking edits would be the metric the sketch said not to fake. |
| Billing as an escalation trigger | Security, leaked secrets, abuse, or unanswerable from context | This corpus is a public OSS repo. |
| Any of three example repos | `fastapi/fastapi` only | One corpus, one label map, one cache. |

## Graph shape

```text
START
  → classify
  → retrieve
  → draft
  → review          interrupt on every run
       → approved or edited → finalize → END
       → rejected, revision_count < 2 → draft
       → rejected, revision_count >= 2 → END    no post
```

`needs_escalation` does not skip the interrupt. It is part of the interrupt payload. Finalize still posts an approved escalation to the sink repo; the payload tells the reviewer not to treat it as a normal public reply. The demo uses a non-escalation issue for the happy path.

Invariants:

- Classify sees title and body only. No tools.
- Retrieve is the only node with GitHub read tools.
- Draft has no tools. It writes from state.
- Review calls `interrupt()`. It does not call the model.
- Finalize is plain Python. It is the only writer, and only to `GITHUB_SINK_REPO`.
- No model is bound to the write.
- Threads have an id. Resume continues the same thread.
- Revision cap is 2. `revision_count` starts at 0 and counts completed redrafts. The edge on `rejected` goes back to `draft` only while `revision_count < 2`. The draft node increments it at the start of a redraft. A third rejection ends with no post.

## State

```python
class TriageState(TypedDict):
    issue_number: int
    title: str
    body: str
    category: str                         # bug | feature | question | docs
    classification_confidence: float
    retrieved_context: list[dict]         # docs + similar closed issues
    possible_duplicate_of: int | None
    draft_response: str
    needs_escalation: bool
    escalation_reason: str | None
    rejection_notes: list[str]
    human_decision: Literal["approved", "edited", "rejected"] | None
    human_edited_text: str | None
    final_response: str | None
    revision_count: int
    sink_issue_url: str | None
```

## Repo layout the later steps create

```text
docs/architecture.md      draft in step 1, revised in step 4
docs/decisions.md
docs/friction-log.md      append when something in the framework fights you
src/triage/state.py
src/triage/graph.py
src/triage/nodes.py
src/triage/tools.py
src/triage/prompts.py
src/triage/cli.py
data/dataset.json         gold rows, committed
data/cache/               GitHub responses, committed
evals/build_dataset.py
evals/evaluators.py
evals/run_experiment.py
evals/edit_distance.py
langgraph.json
demo/script.md
.env.example
```

Leave both briefs in place. Step 4 adds a short pointer at the top of the root `README.md` to the docs. Do not delete interview-process text.

## LangSmith, short version

Two different things:

- **This repo's runs** go to LangSmith via `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, and `LANGSMITH_PROJECT=triage`. Set `LANGSMITH_ENDPOINT` only for a self-hosted instance. The build does not stand one up.
- **Part 1** is the design for InnovateCorp's instance. It is a document.

Dataset name: `triage`. Traces are the contract.

## Explicit non-goals

- Any product other than Triage. Any corpus other than `fastapi/fastapi`.
- Writing to the source repo. Posting during an eval run.
- Postgres, Redis, or Agent Server in Kubernetes as a local dependency. `langgraph dev` plus MemorySaver is the runtime. The architecture doc describes the deployed shape.
- Sandboxes, Engine, Fleet, or LLM Gateway in the v1 platform design.
- A chatbot UI.
- More than two variants in the experiment.

## Locked decisions

| Point | Choice |
| --- | --- |
| Language | Python |
| Product | Triage |
| Corpus | `fastapi/fastapi`, read-only |
| Sink | `GITHUB_SINK_REPO`, private, yours |
| Model | `init_chat_model`, provider from `.env` |
| Checkpointer | `MemorySaver` |
| Platform cloud | GCP, existing GKE, `us-central1` |
