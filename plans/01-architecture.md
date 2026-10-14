# 01 — Architecture draft

## Goal

Write the design doc first, at the depth you would send a customer before a build review. Keep it short enough to present in about ten minutes.

## Maps to

Deliverable 1 (architecture documentation) and the "why" half of the stage 5 presentation.

## Read first

`plans/00-scope.md`. The product is Northwind Desk.

## Out of scope

- Application code.
- LangSmith install or deployment commands.
- Pixel-perfect diagrams. Mermaid in the markdown is the source. Export images later if the submission portal wants them.

## Write `docs/architecture.md`

Use these sections. A few paragraphs each, plus the diagrams. No tutorial voice.

1. **Problem.** Support agents re-read the same policies and sometimes issue refunds the policy does not allow. The assistant drafts; a person approves writes.
2. **Users and trust boundary.** One internal user, one tenant. The model may read tickets and policies. It may not mutate a ticket. The graph may mutate a ticket only after an interrupt resumes with approval.
3. **Request path.** A diagram:

```text
Support agent
  → Agent Server (the graph)
      → policy docs (files)
      → ticket records (files now, system of record later)
      → interrupt, then the write tool
  → LangSmith (traces, datasets, experiments)
```

4. **Graph.** The classify / docs / records / action / interrupt diagram from `00-scope.md`. Name the state fields: messages, intent, ticket id, draft action, decision.
5. **Why a graph.** One paragraph on why the write tool is not model-bound. One paragraph on why docs and records are separate nodes (tool scope and a gradable route). One paragraph on Deep Agents: appropriate when a specialist needs its own multi-step loop and a private context window; unnecessary while each specialist is a single model call plus tools.
6. **LangSmith on the diagram.** Separate "where the agent runs" from "where traces go."
   - Local: `langgraph dev` (Studio + in-memory or sqlite checkpoint). Traces to the LangSmith project.
   - Target deployment: LangSmith Deployment. Control plane manages deployments. Data plane runs Agent Server. Postgres holds thread checkpoints. Redis is the runtime's queue/cache. Assistants carry config (model, prompt version). Threads carry state. Runs are the unit of work. Traces still go to LangSmith observability, which may be Cloud or the instance you host.
   - Do not document Helm charts, Terraform, or the self-host service list beyond naming the split: observability plane versus deployment data plane.
7. **Scale, at the level of the interview.** Agent Server replicas are stateless apart from the checkpoint database. Trace ingest is asynchronous and must not sit on the user path. Eval runs are a batch workload, not the request path. Name the limit: this design is one tenant, one region, no burst plan.
8. **What failure looks like.** Wrong route, answered without a citation, write attempted before approval, approved write against the wrong ticket. These four become the evals in step 3. Say that in the doc so the eval section is a consequence of the design.
9. **Not in this version.** Online evals, annotation queues, CI gates, real ticketing APIs, authn, multi-tenant isolation, Deep Agents.

## Write `docs/decisions.md`

Five short entries. Each one: decision, alternative, why, what would change your mind.

1. LangGraph, not a single tool-calling loop, and not Deep Agents.
2. Files as the system of record for the exercise.
3. Interrupt before write, with the write tool outside the model.
4. Code graders for route and trajectory; LLM-as-judge only for free-text policy answers.
5. One experiment: baseline classifier prompt versus a stricter one.

## Done when

- Both docs exist and a person who has not seen this plan can tell what runs where.
- The deployed diagram uses LangSmith Deployment words (control plane, data plane, Agent Server, assistant, thread, checkpoint) without a install guide.
- Failure modes in the doc are the same four that step 3 will grade.
- No application source files were added.
