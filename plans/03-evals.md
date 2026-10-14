# 03 — Evals

## Goal

A committed dataset and one LangSmith experiment that shows a real difference, plus graders that match the four failure modes in `docs/architecture.md`.

## Maps to

Deliverable 2 (evaluation framework and test datasets) and the results you will put in the demo and the deck.

## Read first

`plans/00-scope.md`, `docs/architecture.md`, and the graph from step 2. Grade the graph you built. Do not add agent features in this step.

## Out of scope

- Online evals, annotation queues, and CI.
- A second product scenario.
- More than two prompt variants.
- Judging tone, helpfulness, or latency.

## Dataset

`evals/examples.json`, about 20 rows. Each row has an input utterance, a split tag, and the reference.

Splits, tagged so they can run alone:

| Tag | Rows | Reference |
| --- | --- | --- |
| `route` | 8 | Expected intent. Include one unclear case and one case that mentions a refund policy but is only a question. |
| `lookup` | 4 | Expected ticket status or "not found". |
| `action` | 4 | Expected draft action and ticket id. At least one must be rejected by policy (out of window, or already refunded) so the correct draft is a refusal, not a write. |
| `grounding` | 4 | A fact that must appear, and the doc file name that contains it. |

Keep the rows in git. A small script syncs them to a LangSmith dataset named `northwind-desk`. Re-running the script updates rows in place rather than duplicating them.

## Graders

Put them in `evals/evaluators.py`.

1. **Route.** Exact match on intent. Code only. Run it on the `route` split by invoking the classify node, not the whole graph.
2. **Trajectory.** On lookup and action rows, score partial credit: required read tool called, `apply_action` never called inside an eval run (evals do not resume the interrupt), draft fields match when the reference has them. Code only, from the graph state or the trace.
3. **Final answer.** Lookup rows: exact status string, code grader. Grounding rows: the required fact and the doc name are present, code grader. If a grounding answer is paraphrased so the code grader is unfair, allow one LLM-as-judge on those four rows only. The judge returns a score and a one-sentence reason, with the reference fact in the prompt. Do not send the judge the whole ticket file.

No grader calls the model to decide the route.

## Experiment

`evals/run_experiment.py`.

- Variant `baseline`: the classify prompt from step 2.
- Variant `strict`: a shorter classify prompt that lists the four intents, one example of a question that mentions "refund" but is not an action, and an instruction to emit `unclear` rather than guess.
- Same dataset, same graders, two experiments (or one experiment with two sessions, whichever the current SDK expresses cleanly).
- Prefix the LangSmith experiment name with the variant and the date.
- Set run metadata `prompt_version` to the variant name.

The strict prompt should be aimed at the row that is a policy question disguised as an action. If both variants score the same, change that row or the strict prompt until the comparison shows a difference you can explain. Do not add rows until the chart moves and then hide the result.

Write the scores into `docs/eval-results.md`: row counts, each grader's aggregate, which variant won on route, and one sentence on a case the winner still gets wrong. Pull the numbers from the run. Do not invent them.

## Done when

- `northwind-desk` exists in LangSmith and matches `evals/examples.json`.
- Both variants have a finished experiment, traces linked, graders attached.
- `docs/eval-results.md` quotes those results and names the remaining failure.
- Eval runs did not execute `apply_action`.
