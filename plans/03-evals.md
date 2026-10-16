# 03 — Evals

## Goal

A dataset pulled from closed `fastapi/fastapi` issues, graders that match the failure modes in `docs/architecture.md`, and one LangSmith experiment that shows retrieval changing the draft.

## Maps to

Assignment Part 2: test dataset, LangSmith evaluations, custom metrics. The numbers you will put in the demo and the deck.

## Read first

`plans/00-scope.md`, `docs/architecture.md`, and the graph from step 2. Grade that graph. Do not add agent features in this step. You may change prompt text for the two variants.

## Out of scope

- Online evals, annotation queues, and CI.
- A second corpus or a second experiment.
- Posting to GitHub from any eval run.
- Treating latency or token cost as a custom grader. Those come from the trace. Quote them in the results doc.

## Dataset

`evals/build_dataset.py` writes `data/dataset.json`, then syncs it to a LangSmith dataset named `triage`. Re-running updates rows in place.

About 48 closed issues. Floor of 8 per category; stop at 48 even if one category is short, and record the shortfall. Selection rules, encoded in the script, not applied by hand:

- Has a non-empty title and body.
- Gold reply is the first issue comment by a MEMBER or COLLABORATOR, not a `[bot]`, not the issue author, and at least 80 characters. Skip issues that fail this. Template nudges are not a reply to grade against.
- Gold category comes from labels, mapped in one dict in the script: `bug` → `bug`, `enhancement` → `feature`, `question` → `question`, `documentation` → `docs`. Inspect live labels before freezing the dict. An issue with two of these labels is skipped. An issue with none is skipped.
- Spread the sample across categories. Do not take the 48 most recent.

Each row stores: issue number, title, body, labels, gold category, gold reply, source URL, and `should_escalate`.

`should_escalate` is `null` from the script. Before the experiment, hand-set it on 16 rows: 8 true (vulnerability, pasted secret, abusive tone, or a question the README cannot answer) and 8 false (ordinary bugs and questions). Leave the other rows null so the escalation grader skips them. Commit the file after that pass.

The row does not store retrieved context. Retrieval is the agent's job. Tool caches from step 2 keep the GitHub reads stable.

## Eval target

Do not pass `graph.invoke` straight to `evaluate`. The graph always interrupts, so a full invoke does not finish, and it must not reach `finalize`.

Target function, one fresh thread per row, MemorySaver:

1. Invoke with `issue_number`, `title`, and `body`.
2. Read state at the interrupt.
3. Return `category`, `classification_confidence`, `retrieved_context`, `possible_duplicate_of`, `draft_response`, `needs_escalation`, `escalation_reason`.

Assert in the target that `sink_issue_url` is empty. The `ungrounded` variant uses the same graph with the retriever forced to write an empty context and a null duplicate. Same classify and draft prompts.

Set metadata `prompt_version` to `grounded` or `ungrounded`.

## Graders

In `evals/evaluators.py`. Register them on the experiment.

| Grader | Type | Scores |
| --- | --- | --- |
| `category_exact` | Code | Predicted category versus gold category. |
| `did_not_post` | Code | Fail the row if `sink_issue_url` is set or a trace child is `finalize`. |
| `groundedness` | LLM judge | Every factual claim in the draft is supported by `retrieved_context`. Judge sees the draft and the context only. Not the gold reply. Returns a score and one sentence. |
| `reply_quality` | LLM judge | Helpfulness, correctness, and tone against the gold reply. Judge sees the issue, the draft, and the gold reply. Not the retrieved context. |
| `escalation` | Code | On rows where `should_escalate` is true or false, match `needs_escalation`. Return no score when the label is null. |

No grader asks a model to pick the category.

`evals/edit_distance.py` reads `data/reviews.jsonl` and prints a character-level diff ratio for `edited` rows, plus counts of approved, edited, and rejected. It is not an experiment grader. If the file has no rows yet, the script says so and exits 0.

## Experiment

`evals/run_experiment.py`.

- `grounded`: real retriever.
- `ungrounded`: empty context.
- Same dataset, same graders.
- Experiment names start with the variant and the date.

Expect `grounded` to win on `groundedness`. If it does not, fix the draft prompt so it can only state facts from context, and run again. Do not add rows to manufacture the gap. `category_exact` should be nearly the same for both, because classify runs before retrieval. If it moves, something is leaking context into classify; fix that before writing up the result.

Write `docs/eval-results.md` from the run, not from memory:

- Row counts and how many of each gold category.
- The label-map dict, and one sentence on labels you dropped.
- Each grader's aggregate for both variants, and which variant won on groundedness.
- One row the winner still gets wrong.
- Escalation precision and recall on the 16 labeled rows.
- p50 latency and token totals taken from the experiment, labeled as trace stats.
- Edit distance: the script's output, or "no live reviews yet."

Also append any eval-SDK friction to `docs/friction-log.md`.

## Done when

- `triage` in LangSmith matches `data/dataset.json`.
- Both variants have a finished experiment, traces linked, graders attached.
- No eval run created a sink issue.
- `docs/eval-results.md` quotes those results and names the remaining failure.
- The 16 escalation labels are filled in. They are judgments you made, not model output.
