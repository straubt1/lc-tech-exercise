# 05 — Presentation outline

The assignment asks for a 40-minute presentation to InnovateCorp's technical and business stakeholders. The live panel in the root `README.md` is 35 minutes plus 15 minutes of questions. Build one deck that covers the assignment, paced at about 32 minutes, so the same slides fit the panel slot.

This file is a slide list only. Build it later as one reveal.js HTML file. Do not design a theme, write speaker notes, or generate the deck in this step.

## Deck

One HTML file, `presentation/index.html`, when you eventually build it. Diagrams come from `docs/architecture.md`. Numbers come from `docs/eval-results.md`. Friction items come from `docs/friction-log.md`. If a number is not in those files, it does not go on a slide.

| # | Slide | Content |
| --- | --- | --- |
| 1 | Title | Triage for InnovateCorp. One sentence: draft the first reply, a person sends it. |
| 2 | Agenda | Part 1 platform, Part 2 agent, what the evals say, what it is worth, what the tools made hard. |
| 3 | Why self-host | Traces and prompts stay in their project. Existing GKE, `us-central1`. |
| 4 | Components | Frontend, backend, platform backend, queues, playground, ACE. Postgres, Redis, Cloud Storage, ClickHouse. Mark external versus in-cluster. |
| 5 | Placement | Ingress, private data stores, two node pools, secrets. |
| 6 | Scale | UI users versus trace rate. KEDA on the queues. ClickHouse as the stateful limit. Medium/medium year-1 point. |
| 7 | Phase 2 | Same cluster, LangSmith Deployment, checkpoints in Postgres. Laptop is what you actually ran. |
| 8 | The workflow | Classify, retrieve, draft, always interrupt, post only to the sink repo. |
| 9 | Trust boundary | Write is not a tool. Source repo is read-only. Reject loops at most twice. |
| 10 | Decision | Five nodes, not one loop, not a Deep Agent. Review and finalize are deterministic on purpose. |
| 11 | Decision | ClickHouse in-cluster. What would move you to SmithDB or managed ClickHouse. |
| 12 | Evals | Dataset from closed issues. The five graders and which failure each covers. Edit distance sits outside the experiment. |
| 13 | Results | Grounded versus ungrounded. The case that still fails. Escalation precision and recall on the 16. |
| 14 | Business effect | Measured: approval mix, edit distance, groundedness, escalation recall. Proposed, and labeled proposed: time to first reply, maintainer hours, public corrections avoided. |
| 15 | Friction | Three entries from the log. Each one names a missing product behavior. |
| 16 | Limits | One region, one tenant, no online evals, no public posting, label noise in the gold categories. |
| 17 | Close | What you want the room to push on. |

## Questions to be ready for

Know the answer from the doc or the code, not from this list.

- Why is ClickHouse in the cluster if the docs tell you to externalize storage?
- What breaks if trace volume goes from 100 per second to the high tier?
- Why not LangSmith Cloud with a no-train agreement instead of this design?
- Why does every run interrupt, including high-confidence docs questions?
- Why is `duplicate` not a classifier label?
- How does a thread survive the interrupt on a laptop, and where does that state go in phase 2?
- Why is the eval target not a full `invoke`? What would a premature finalize look like in a trace?
- The gold labels are maintainer tags. When the model disagrees, which one is wrong?
- What if groundedness goes up and reply quality goes down?
- How would a second team get a workspace without seeing these traces?
- Which friction-log item would you file, and what workaround did you ship?

## Done when

This outline still matches the node names, the platform choices, and the experiment you ran. No HTML yet, unless you explicitly ask for the deck in a later prompt.
