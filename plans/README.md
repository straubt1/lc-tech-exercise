# Stage 4 plan

Step-by-step plan for the LangChain take-home. Stage 5 is only a thin outline so the later presentation has a target.

The interview brief stays in the repo root `README.md`. These files are the build plan. Do not replace the brief.

## How to run a step

Prompt with one file at a time:

> Implement `plans/0N-….md` only. Stop when its "Done when" list is met. Do not start the next file.

Read this file and `plans/00-scope.md` at the start of every step. The product is Northwind Desk. Do not add a second agent or swap the domain.

## Order

| Step | File | What it produces |
| --- | --- | --- |
| 0 | `00-scope.md` | Decisions. Read it. Do not implement it. |
| 1 | `01-architecture.md` | `docs/architecture.md` and `docs/decisions.md` |
| 2 | `02-agent.md` | Working LangGraph app, local data, tracing |
| 3 | `03-evals.md` | Dataset, graders, one comparison experiment |
| 4 | `04-demo-and-docs.md` | Run instructions, decision log updates, demo script |
| 5 | `05-presentation.md` | Slide list only. Build the reveal.js deck later. |

Step 1 is a draft you can build against. Step 4 revises it so the doc matches the code.

## Locked decisions

- **Product:** Northwind Desk, a fake internal support agent. One graph, two specialists, one human approval gate.
- **Language:** Python.
- **Framework:** LangGraph.
- **LangSmith:** already reachable. This plan only wires tracing, a dataset, and an experiment. No install, Helm, or Terraform.
- **Models:** one chat model via `init_chat_model`. The provider is whatever API key is in `.env`.
- **Tools:** local files only. No live ticketing system, no web search.

## What the build includes

- A LangGraph app with separate specialist prompts and tool sets.
- A human interrupt before any write.
- LangSmith traces on every run, with a project name and environment.
- A committed dataset, code graders first, one small LLM-as-judge rubric, and one A/B experiment.
- An architecture doc a customer could read: components, deployment, scale, and what was left out.
- A 5–10 minute demo script that shows the agent, a blocked write, a trace, and the experiment.

## What stays out

- Training or fine-tuning.
- A UI beyond LangGraph Studio and a CLI.
- Production Kubernetes, auth, or multi-tenant tenancy.
- Online evals, annotation queues, and CI. Name them in the doc as the next step.
- More than one comparison experiment.
