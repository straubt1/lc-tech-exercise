# 00 — Scope

Read this before every implementation step. Do not treat this file as a build step.

## Product

Build **Northwind Desk** only: an internal assistant for support agents at a fictional retailer.

A support agent asks a question in plain language. The assistant does one of three things:

1. Answers from a small policy corpus and cites the doc.
2. Looks up a ticket or customer and reports what it found.
3. Drafts a write (refund, escalate, or close). It stops for a person to approve. Only an approval runs the write.

Four policy docs, about eight tickets, about twenty eval cases, one graph.

The write path is not reachable from the read path, and doc search is not available to the action agent. Keep the policy text and ticket facts original.

## Graph shape

```text
START
  → classify
      → docs specialist      → respond → END
      → records specialist   → respond → END
      → action specialist    → interrupt → execute or cancel → respond → END
      → clarify              → END
```

Invariants:

- Specialists do not share tool lists.
- The action tool that mutates state is not bound to the action model. The graph calls it after the interrupt returns approval.
- Classify is its own node so it can be graded without running the specialists.
- Threads have an id. The same thread can continue after the interrupt.

## Repo layout the later steps create

```text
docs/architecture.md      draft in step 1, revised in step 4
docs/decisions.md
src/desk/state.py
src/desk/graph.py
src/desk/nodes.py
src/desk/tools.py
src/desk/prompts.py
data/docs/*.md
data/tickets.json
evals/examples.json
evals/evaluators.py
evals/run_experiment.py
langgraph.json
demo/script.md
.env.example
```

Leave the root `README.md` interview brief in place until step 4. Step 4 adds run instructions without deleting the brief. Put run instructions in `docs/running.md` if mixing them into the brief gets messy.

## LangSmith, short version

You deploy or sign in yourself. The build only needs:

- `LANGSMITH_TRACING=true`
- `LANGSMITH_API_KEY`
- `LANGSMITH_ENDPOINT` if it is not Cloud
- `LANGSMITH_PROJECT=northwind-desk`

Traces are the contract. Datasets and experiments are created with the LangSmith SDK against that project. No platform install steps belong in this repo.

## Explicit non-goals

- Any product other than Northwind Desk.
- A chatbot UI, or a live ticketing integration.
- Postgres, Redis, or Agent Server in Kubernetes. Local `langgraph dev` is enough to show Studio. The architecture doc describes the deployed shape.
- Graders for tone, style, or latency.
- More than two prompt variants in the experiment.

## Locked decisions

| Point | Choice |
| --- | --- |
| Language | Python |
| Product | Northwind Desk |
| Model | `init_chat_model`, provider from `.env` |
