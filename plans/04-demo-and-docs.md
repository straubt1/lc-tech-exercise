# 04 — Docs and demo script

## Goal

Make the repo something you can hand over and narrate in under ten minutes. Update the architecture doc so it matches the code. Leave a friction log you can defend line by line.

## Maps to

Deliverable 1 (final architecture doc), deliverable 3 (the recording script), and the friction log the assignment asks for in the presentation.

## Read first

The code, `docs/eval-results.md`, `docs/friction-log.md`, and `plans/00-scope.md`.

## Out of scope

- Recording the video.
- The deck (step 5 is an outline only).
- New agent behaviour. If a demo path is broken, fix that bug and stop.
- Standing up LangSmith in Kubernetes.

## Revise the docs

Update `docs/architecture.md` where the draft drifted: real node names, MemorySaver as the local checkpointer, project name `triage`, the sink repo, and the eval results as evidence for the failure-mode section.

Update `docs/decisions.md` only if a decision changed during the build. Add one "another week" note: promote failed experiment traces into the dataset, and run `category_exact` and `did_not_post` in CI.

`docs/friction-log.md` must contain at least three entries from this build. Each entry: what you tried, what the framework did, what you did instead, what you wish existed. Drop any entry you cannot point at in a trace, a docstring, or a commit. If you have fewer than three, use the product once more until you do. Do not pad with generic complaints.

Add `docs/running.md`:

- Python version, install, `.env` keys (`LANGSMITH_*`, `MODEL`, `GITHUB_TOKEN`, `GITHUB_SINK_REPO`).
- `langgraph dev` for Studio.
- CLI examples for the three smoke issues, including approve, edit, and reject on the same thread.
- How to rebuild the dataset, sync it, and run both experiment variants.
- How to run `evals/edit_distance.py`.
- One line that the LangSmith in `.env` is the tracing project, and Part 1 is the design for a separate self-hosted instance that this repo does not install.

Keep both briefs. Add a short pointer at the top of the root `README.md` to `docs/running.md`, `docs/architecture.md`, and `docs/eval-results.md`.

## Write `demo/script.md`

A timed script, 8 minutes, so a 5–10 minute recording has room. Use the real issue numbers, the real sink repo, and the real experiment names.

| Minute | On screen | Say |
| --- | --- | --- |
| 0:00 | Platform diagram, then the graph | InnovateCorp hosts LangSmith. This agent is the workflow. The model cannot post. |
| 1:00 | CLI, docs question | Draft cites a file. Open the cached doc and show the sentence. |
| 2:30 | Similar-issue bug | Show the closed issue the retriever returned. |
| 4:00 | Interrupt | Reject once on the same thread. No sink issue. New thread: edit one sentence, approve, open the sink issue. Source repo has no new comment. |
| 6:00 | LangSmith | One trace with the pause. Then grounded versus ungrounded on the groundedness grader. Read the one case the winner still misses. |
| 7:30 | Close | Edit distance if `data/reviews.jsonl` has rows. What you left out: online evals, posting to the public repo, LangSmith Deployment beyond the diagram. |

End the file with a shot list (what to click) so the recording does not depend on memory.

## Done when

- A cold start from `docs/running.md` reaches a traced CLI reply.
- The architecture doc's node names match `src/triage/graph.py`.
- `docs/friction-log.md` has at least three entries you can point at.
- `demo/script.md` is timed, uses real ids and experiment names, and fits in ten minutes.
