# 05 — Presentation outline

Stage 5 is a 35 minute presentation and 15 minutes of questions. This file is a slide list only. Build it later as one reveal.js HTML file. Do not design a theme, write speaker notes, or generate the deck in this step.

## Deck

One HTML file, `presentation/index.html`, when you eventually build it. Diagrams come from `docs/architecture.md`. Numbers come from `docs/eval-results.md`.

| # | Slide | Content |
| --- | --- | --- |
| 1 | Title | Northwind Desk, one sentence on what it does. |
| 2 | Customer problem | Time on repeated policy questions, risk on unapproved writes. |
| 3 | What you built | Three paths: answer, lookup, approve-then-write. |
| 4 | Architecture | Request path: user, Agent Server, files, LangSmith. |
| 5 | Deployment target | Control plane, data plane, checkpoints, traces. Local Studio is what you ran. |
| 6 | Graph | Nodes and the interrupt. |
| 7 | Decision | Write tool is not on the model. Alternative was a normal tool with a prompt warning. |
| 8 | Decision | Two specialists instead of one agent or a Deep Agent. |
| 9 | Evals | Four failure modes, which grader covers each. |
| 10 | Results | Baseline versus strict. The case that still fails. |
| 11 | Scale and limits | One tenant, checkpoint database, evals off the request path. |
| 12 | Business effect | What you would measure in production: containment on questions, write-approval rate, refund policy violations. Label these as proposed, not measured. |
| 13 | Product feedback | Two concrete notes from using tracing, datasets, and experiments. Only notes you can point at in the UI. |
| 14 | With more time | Failed traces back into the dataset. Code graders in CI. A real system of record. |
| 15 | Close | What you want the panel to push on. |

Target 30 minutes of talking, leaving five minutes inside the presentation block.

## Questions to be ready for

Know the answer from the code, not from this list.

- Why is classify a separate node?
- Why not bind the write as a tool and tell the model not to call it?
- How does a thread survive the interrupt, and where would that state live when you leave your laptop?
- What happens with two open tickets for one customer?
- Why were those graders code instead of a judge? Where is a judge actually used?
- What if the strict prompt wins routing and loses grounding?
- How would you add a second tenant without mixing traces or checkpoints?
- What did you choose not to build?

## Done when

This outline still matches the node names and the experiment you ran. No HTML yet, unless you explicitly ask for the deck in a later prompt.
