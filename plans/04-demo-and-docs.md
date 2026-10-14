# 04 — Docs and demo script

## Goal

Make the repo something you can hand over and narrate in under ten minutes. Update the architecture doc so it matches the code.

## Maps to

Deliverable 1 (final doc), deliverable 3 (the recording script), and the decision write-up inside deliverable 2.

## Read first

The code, `docs/eval-results.md`, and `plans/00-scope.md`.

## Out of scope

- Recording the video.
- The reveal.js deck (step 5, and even that is only an outline).
- New agent behaviour. If a demo path is broken, fix that bug and stop.

## Revise the docs

Update `docs/architecture.md` where the draft drifted: real node names, where the checkpoint lives locally, the LangSmith project name, and the eval results as evidence for the failure-mode section.

Add to `docs/decisions.md` only if a decision changed during the build. Note one thing you would do with another week: promote the failed traces from the experiment into the dataset, and gate merges on the code graders.

Add `docs/running.md`:

- Python version, install, `.env` keys.
- `langgraph dev` for Studio.
- CLI examples for the three paths, including approve and reject.
- How to sync the dataset and run both experiment variants.
- A line that LangSmith itself is assumed to be already up, with `LANGSMITH_ENDPOINT` optional for a self-hosted instance.

Keep the interview brief in the root `README.md`. Add a short pointer at the top to `docs/running.md`, `docs/architecture.md`, and `docs/eval-results.md`.

## Write `demo/script.md`

A timed script, 8 minutes, so a 5–10 minute recording has room.

| Minute | On screen | Say |
| --- | --- | --- |
| 0:00 | Architecture diagram | Who the user is, and that the model cannot write. |
| 1:00 | CLI or Studio, policy question | Answer cites a file. Open that file and show the sentence. |
| 2:30 | Ticket lookup | Read-only. Show the trace's tool run. |
| 4:00 | Refund request | Interrupt payload. Reject. Ticket unchanged. New thread, approve, ticket changed. |
| 6:00 | LangSmith experiment | Baseline versus strict on the route grader. Read the one case the winner still misses. |
| 7:30 | Close | What you left out on purpose: online evals, a real ticket API, deployment beyond local Studio. |

End the file with a shot list (what to click) so the recording does not depend on memory.

## Done when

- A cold start from `docs/running.md` reaches a traced CLI reply.
- The architecture doc's node names match `src/desk/graph.py`.
- `demo/script.md` is timed, uses the real ticket ids and the real experiment names, and fits in ten minutes.
