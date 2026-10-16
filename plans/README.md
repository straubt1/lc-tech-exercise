# Take-home plan

Step-by-step plan for the Deployed Architect take-home. The brief that wins on conflict is `Take-Home Assignment.md`. The root `README.md` is the interview-process note (one week, then a live panel). Where they disagree, follow the assignment.

These files are the build plan. Do not replace either brief.

## How to run a step

Prompt with one file at a time:

> Implement `plans/0N-….md` only. Stop when its "Done when" list is met. Do not start the next file.

Read this file and `plans/00-scope.md` at the start of every step. The product is Triage. Do not add a second workflow or swap the domain.

## Order

| Step | File | What it produces |
| --- | --- | --- |
| 0 | `00-scope.md` | Decisions. Read it. Do not implement it. |
| 1 | `01-architecture.md` | `docs/architecture.md` and `docs/decisions.md` |
| 2 | `02-agent.md` | Working LangGraph app, GitHub tools, tracing |
| 3 | `03-evals.md` | Dataset from closed issues, graders, one comparison experiment |
| 4 | `04-demo-and-docs.md` | Run instructions, friction log, demo script |
| 5 | `05-presentation.md` | Slide list only. Build the deck later. |

Step 1 is a draft you can build against. Step 4 revises it so the doc matches the code.

## Locked decisions

- **Client framing:** InnovateCorp already runs Kubernetes and wants LangSmith Platform self-hosted, plus one production agent workflow.
- **Part 1:** conceptual architecture only. GCP, existing GKE, `us-central1`. No Terraform, no Helm install, no cluster.
- **Part 2 product:** Triage. Classify a GitHub issue, retrieve the repo's docs and similar closed issues, draft a maintainer reply, stop for a person on every run, then post only to a private sink repo.
- **Corpus:** `fastapi/fastapi`. Active, documented, and large enough for a gold set. Not so large that search burns the rate limit.
- **Language:** Python. **Framework:** LangGraph. Deep Agents stay unused.
- **LangSmith for the build:** Cloud (or whatever `.env` already points at) for traces, datasets, and experiments. Part 1 describes the self-hosted platform InnovateCorp would run. This repo does not install it.
- **Models:** one chat model via `init_chat_model`. Provider comes from `.env`.
- **Human gate:** every run, not only low confidence.

## What the build includes

- A design doc a customer could read: LangSmith services, which stores are external, where they sit on GKE, and how the design scales.
- One LangGraph app with a classifier, a retriever, a drafter, an interrupt, and a finalize node.
- LangSmith traces on every run.
- A committed dataset built from real closed issues, code graders plus two LLM judges, and one ablation experiment (retrieval on versus off).
- A friction log of framework gaps, written while building, not invented at the end.
- A 5–10 minute demo script: draft, interrupt, approve or edit, sink-repo post, trace, experiment.

## What stays out

- Infrastructure as code, and a real LangSmith install.
- Commenting on `fastapi/fastapi` or any repo you do not own.
- A second agent workflow.
- Training or fine-tuning.
- A UI beyond LangGraph Studio and a CLI.
- Online evals, annotation queues, and CI. Name them as the next step.
- More than one comparison experiment.
