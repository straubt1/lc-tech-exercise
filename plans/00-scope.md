# 00 — Scope

Read this before every implementation step. Do not treat this file as a build step.

Precedence: `Take-Home Assignment.md` beats the root `README.md`. This file beats both for implementation choices. If a later step's code disagrees with this file, stop and fix the plan before widening the build.

## Executive summary

Part 2 gets a new pull request a first review without posting it. On a busy repo that review is slow, and a comment that invents an answer is a public mistake. A person still sends it.

A pull request enters in one of two ways. Both load the same PR and then run the same agents:

1. **Watch.** A poller on `fastapi/fastapi` starts a run when a pull request opens.
2. **Link.** A person passes one PR URL, and the graph acts on that PR.

Three agents do the judgment. Two plain steps keep the model away from the write.

- **Classifier** reads the title, body, and changed paths and assigns `bug`, `feature`, `question`, or `docs`. It exists so the category is a grade of the PR itself. No tools, and no gold labels.
- **Retriever** is the only agent allowed to call GitHub. It pulls README and docs pages and similar closed work, and may mark a duplicate. It exists so later text can only use facts that were fetched.
- **Drafter** writes a short maintainer review comment from that context, and flags security, a leaked secret, abuse, or a change the docs cannot support. It has no tools, so it cannot fetch a fact and then treat it as given context.
- **Review** is not an agent. Every run stops for approve, edit, or reject. A rejection sends the draft back, at most twice.
- **Finalize** is not an agent. After approve or edit it posts only to a private sink repo. The source PR is never commented on.

The split is the product. Each agent's output is one thing an eval can grade, and the write cannot sit inside a model call.

## Two parts

**Part 1 — Platform.** A conceptual design for InnovateCorp's self-hosted LangSmith on the Kubernetes they already run. Diagrams and prose. No cluster, no Helm, no Terraform.

**Part 2 — Agents.** Triage: three specialists draft a first review of a GitHub pull request and will not post until a person approves, edits, or rejects it.

Both parts ship. Spend more time on Part 2. Part 1 still has to be specific enough to defend in the room.

## How a run starts

Two inputs. Neither is an agent. Both call one loader, then the graph.

1. **Watch.** `python -m src.triage.watch` polls `GET /repos/fastapi/fastapi/events` and keeps `PullRequestEvent` with action `opened`. A local cursor stores the last event id handed to the graph. One new PR starts one thread. The same PR number does not start a second thread. The events list is a short window, so a PR the poll missed is started with the link. Evals do not run the watcher.
2. **Link.** `python -m src.triage.cli PR_URL` takes one URL, `https://github.com/fastapi/fastapi/pull/<n>`. This is the path for a pinned PR, the demo's happy path, and every eval row.

The loader is plain Python. It writes `trigger`, `pr_url`, `pr_number`, `title`, `body`, and `changed_paths`, then the graph starts at the classifier. It does not classify, draft, or write.

## Agents

One `StateGraph`. The three agents are nodes on it. Review and finalize are nodes on it too, and they do not call a model.

| Agent | Why it exists | What it does | Does not |
| --- | --- | --- | --- |
| **Classifier** | Category has to be graded from the PR alone. Tools or gold labels would make that score meaningless. | One structured call. Sets `category` and `classification_confidence` from title, body, and `changed_paths`. | Call tools. See labels. Write the comment. |
| **Retriever** | The comment may only claim what the repo supports. Duplicate detection needs search, and every GitHub read should show up in one place in the trace. | Fills `retrieved_context`. May set `possible_duplicate_of` when a closed PR or issue is the same report. At most four tool calls: repo docs, then similar closed work. | Draft the comment. Write to GitHub. |
| **Drafter** | The comment and the escalation flag are a separate judgment from search. No tools means the draft cannot widen its own evidence. | Writes `draft_response`, `needs_escalation`, and `escalation_reason` from state. On a redraft, reads the rejection notes and increments `revision_count` before writing. | Call tools. Post. |

Voice of the draft: a FastAPI maintainer's first review comment. Short. Every factual claim cites a doc path or a closed number that appears in `retrieved_context`. If the context does not support a comment, ask for the missing detail. Set `needs_escalation` for a security-sensitive change, a pasted secret, abusive tone, or a diff the context cannot explain.

**Review** pauses the graph. It calls `interrupt()` with the draft, the category, the confidence, the duplicate hint, and the escalation flag. On resume it sets `human_decision` and, for an edit, `human_edited_text`. It does not call the model. `needs_escalation` does not skip this pause. It is part of the payload. The demo's happy path is a non-escalation PR started from a link.

**Finalize** runs only after `approved` or `edited`. On approve it posts `draft_response`. On edit it posts `human_edited_text`. It sets `final_response` and `sink_issue_url`. The sink issue's title is the PR title. The body is the final comment, the source PR URL, the category, and the escalation flag. It never targets `fastapi/fastapi`.

## Graph shape

```text
watch: PullRequestEvent opened ──┐
                                 ├→ load → classify → retrieve → draft → review
link: PR URL ────────────────────┘                              interrupt on every run
                                      → approved or edited → finalize → END
                                      → rejected, revision_count < 2 → draft
                                      → rejected, revision_count >= 2 → END    no post
```

Invariants:

- Watch and link differ only by `trigger`. From `load` onward the graph is one path.
- Load fetches one PR. No model.
- Classify sees title, body, and changed paths. No tools.
- Retrieve is the only agent with GitHub read tools.
- Draft has no tools. It writes from state.
- Review calls `interrupt()`. Resume continues the same thread via `Command`.
- Finalize is plain Python. It is the only writer, and only to `GITHUB_SINK_REPO`.
- No model is bound to the write.
- Revision cap is 2. `revision_count` starts at 0 and counts completed redrafts. The edge on `rejected` goes back to `draft` only while `revision_count < 2`. The drafter increments it at the start of a redraft. A third rejection ends with no post.

## Rules that keep the eval honest

- The classifier emits `bug`, `feature`, `question`, or `docs`. It has no tools, so duplicate is not a category. The retriever may set `possible_duplicate_of`. FastAPI labels do not mark duplicates cleanly.
- Gold labels live only on the dataset row. A field on agent state gets copied into prompts, so ground truth stays off the state.
- Eval rows are historical PRs started through the link path. The watcher does not run inside an experiment.
- The eval target runs until the interrupt and returns the draft. `invoke` on a graph that always interrupts never returns a final post, and evals must not post.
- Human-edit distance is a live metric from real review sessions. The historical dataset has no reviewer, so invented edits would fake the metric.
- Escalation is security, leaked secrets, abuse, or a change the context cannot explain.
- The corpus is `fastapi/fastapi` only. One corpus, one label map, one cache.

## State

```python
class TriageState(TypedDict):
    trigger: Literal["watch", "link"]
    pr_url: str
    pr_number: int
    title: str
    body: str
    changed_paths: list[str]              # loader output, not a tool result
    category: str                         # bug | feature | question | docs
    classification_confidence: float
    retrieved_context: list[dict]         # docs + similar closed PRs and issues
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

## Hard requirements

Use these. A hand-rolled chat loop, a single tool-calling agent, or another framework does not satisfy Part 2.

| Requirement | API | Binds to |
| --- | --- | --- |
| Workflow | LangGraph `StateGraph` and conditional edges | The one graph: load, three agents, review, finalize |
| Specialist agents | `langchain.agents.create_agent` | Classifier, retriever, drafter, each as a node |
| Model | `langchain.chat_models.init_chat_model` | Every agent. Provider and model name come from `.env` |
| Typed output | `response_format` on `create_agent` | Classifier and drafter |
| Tools | LangChain `@tool`, passed only into that agent | Retriever. Cap four calls |
| Human gate | `langgraph.types.interrupt`, resume with `langgraph.types.Command` | Review node. Not a tool approval |
| Threads | `langgraph.checkpoint.memory.InMemorySaver` and a `thread_id` | Every run, so reject and resume keep the same thread |
| Observe and grade | LangSmith tracing, datasets, and `evaluate` | Every run. Dataset name `triage` |

Classifier and drafter are `create_agent` with an empty tool list and a `response_format`. Retriever is `create_agent` with the GitHub tools. Review and finalize stay ordinary functions on the same `StateGraph`. The checkpointer is compiled onto that outer graph only.

## Repo layout the later steps create

```text
docs/architecture.md      draft in step 1, revised in step 4
docs/decisions.md
docs/friction-log.md      append when something in the framework fights you
src/triage/state.py
src/triage/graph.py
src/triage/agents.py      classifier, retriever, drafter
src/triage/nodes.py       load, review, finalize
src/triage/tools.py
src/triage/prompts.py
src/triage/cli.py         link path
src/triage/watch.py       event path
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
- Writing to the source repo, including review comments on the source PR. Posting during an eval run. Running the watcher inside an experiment.
- Tailing `api.github.com/events`. The watch is this repo's event list only.
- Postgres, Redis, or Agent Server in Kubernetes as a local dependency. `langgraph dev` plus `InMemorySaver` is the runtime. The architecture doc describes the deployed shape.
- Sandboxes, Engine, Fleet, or LLM Gateway in the v1 platform design.
- A chatbot UI.
- More than two variants in the experiment.

## Locked decisions

| Point | Choice |
| --- | --- |
| Language | Python |
| Product | Triage |
| Inputs | Repo `PullRequestEvent` watch, and one PR URL |
| Corpus | `fastapi/fastapi`, read-only |
| Sink | `GITHUB_SINK_REPO`, private, yours |
| Agents | Classifier, retriever, drafter via `create_agent` |
| Graph | LangGraph `StateGraph` |
| Model | `init_chat_model`, provider from `.env` |
| Human gate | `interrupt` and `Command` on every run |
| Checkpointer | `InMemorySaver` |
| Platform cloud | GCP, existing GKE, `us-central1` |
