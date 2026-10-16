# 01 — Architecture draft

## Goal

Write the design doc first, at the depth you would send InnovateCorp before a build review. Part 1 is the self-hosted LangSmith platform. Part 2 is the triage graph. Keep the whole doc short enough that Part 1 can be presented in about twelve minutes and Part 2 in about ten.

## Maps to

Assignment Part 1 (platform architecture) and the design half of Part 2. Deliverable: architecture documentation with diagrams. No IaC.

## Read first

`plans/00-scope.md`. Use the current self-hosted docs while writing, and cite them:

- https://docs.langchain.com/langsmith/self-hosted
- https://docs.langchain.com/langsmith/kubernetes
- https://docs.langchain.com/langsmith/self-host-scale
- https://docs.langchain.com/langsmith/self-host-disaster-recovery

If a doc and this plan disagree on a component name, use the doc's name and note it in `docs/decisions.md`.

## Out of scope

- Application code.
- Helm values, Terraform, or commands that create cloud resources.
- Pixel-perfect diagrams. Mermaid in the markdown is the source.

## Constraints the doc must state, then honor

Invent nothing beyond this list. These are the requirements:

- InnovateCorp already has GKE in `us-central1` across three zones. Design onto that cluster. Do not propose a new cluster.
- Trace and operational data stay in their GCP project. That is why they are self-hosting.
- Year-1 load is the scale guide's medium/medium point: about 20 concurrent UI users and about 100 traces per second, with headroom for this agent plus two later workflows.
- v1 enables the base platform: observability, evaluation, prompt hub, Insights, and Chat. LangSmith Deployment (control plane, data plane, Agent Server) is drawn as phase 2, not required to go live.
- Sandboxes, Engine, Fleet, and LLM Gateway are out of v1. Say why in one sentence each: no code-interpreter product need, no KVM node pool, Fleet is a separate product, LLM Gateway is still beta.

## Write `docs/architecture.md`

A few paragraphs per section, plus the diagrams. No tutorial voice.

### Part 1 — LangSmith Platform

1. **Problem.** InnovateCorp will run agent workflows against customer data. Traces, datasets, and prompts cannot live in LangSmith Cloud. They want one self-hosted platform their existing platform team can operate.

2. **Component diagram.** Application services and storage, with an edge labeled external or in-cluster.

   Application services, from the self-hosted overview: frontend (Nginx, the only public entry), backend, platform backend, queue, ingest queue, playground, ACE backend. Name what each does in one line. Stateless: a Helm reinstall recreates them.

   Storage:

   | Store | Holds | v1 placement | Why |
   | --- | --- | --- | --- |
   | PostgreSQL | Orgs, users, API keys, datasets, prompts, projects | External, Cloud SQL for PostgreSQL, regional HA | System of record. Docs say externalize for production. |
   | Redis or Valkey | Queues, cache, heartbeats | External, Memorystore | Ephemeral. Rebuild on loss. Managed so a node death does not stall ingest. |
   | Blob (Cloud Storage) | Large run payloads and attachments | External, Cloud Storage in-project | Recommended for production. Trace bodies for this agent include issue text plus retrieved docs. |
   | ClickHouse | Traces and feedback | In-cluster, dedicated node pool | Must stay in the project. Bundled ClickHouse asks for at least 4 vCPU and 16Gi. Do not put it on the app pool. |

   Also name the two stores you considered and rejected for v1, in two sentences: LangChain Managed ClickHouse (leaves the project or is vendor-operated; conflicts with the residency requirement) and SmithDB (valid greenfield option on chart 0.17, object storage plus in-cluster ingestion/query/compaction; defer until the DR story is as clear as ClickHouse backup/restore).

3. **Placement diagram.** VPC, private subnet, GKE.
   - Frontend behind their existing ingress. Every other LangSmith service is ClusterIP.
   - Cloud SQL, Memorystore, and Cloud Storage are private. No public database endpoints. Pods reach GCP APIs with Workload Identity.
   - Two node pools: general for the stateless services, memory-optimized for ClickHouse.
   - License key, database URLs, and the Insights/Chat encryption keys live in Secret Manager and are projected into the release. Do not invent a second secret store.
   - Insights and Chat are on by default. Call out the extra need: one encryption key each, plus model access from the playground path.

4. **Ingest path.** A small diagram: SDK → frontend/platform backend → Redis → ingest queue → ClickHouse, with large fields in Cloud Storage. One paragraph: ingest is asynchronous and must not sit on the reviewer's request path. The triage CLI blocks on the model and on GitHub, not on trace insert.

5. **Scale.** Tie replicas to the two axes in the scale guide, not to a single "make it bigger."
   - UI users push frontend and backend.
   - Trace rate pushes platform backend and ingest queue. Prefer KEDA on queue depth for those workers. HPA on CPU is the wrong signal for a queue.
   - ClickHouse is the stateful limit. Scale disk and the dedicated pool before you add app replicas.
   - Eval runs are a batch workload. They share the trace pipeline and must not be sized as if they were the online path.
   - Cluster autoscaler is assumed, because the cluster is theirs.

6. **Failure and recovery.** One paragraph from the DR model: stateless services are a Helm reinstall; Postgres is the backup that matters; Cloud Storage is versioned; Redis is rebuilt empty; ClickHouse is backup/restore, not a hot cross-region replica. State a single-region limit. RPO is whatever their Cloud SQL PITR already is. Do not invent a second region.

7. **Phase 2, same cluster.** When they want this graph hosted rather than on a laptop: enable LangSmith Deployment. Control plane manages deployments. Data plane runs Agent Server. Checkpoints move from MemorySaver to Postgres. Redis is already there. KEDA scales the workers. Assistants carry the prompt version. Threads carry state. Traces still land in the same ClickHouse. This is the bridge into Part 2. Do not design a second cluster for it.

### Part 2 — Triage

8. **Problem.** First replies on a busy public repo are slow, and an ungrounded reply is a public mistake. The assistant drafts. A person sends.

9. **Users and trust boundary.** One reviewer. The model may read `fastapi/fastapi`. The model may not write anywhere. The graph may write only after `interrupt()` resumes with `approved` or `edited`, and only to `GITHUB_SINK_REPO`.

10. **Graph.** The diagram from `00-scope.md`. Name the state fields from that file. One paragraph on why review and finalize are not model calls: the pause has to be real, and the write has to be outside the model. One paragraph on why classify, retrieve, and draft are separate nodes: different tools, and each output is a grader target.

11. **What failure looks like.** These become the evals in step 3. Say that.
    - Wrong category against the mapped GitHub label.
    - A draft claim that is not in the retrieved context.
    - A draft that does not cover what the real maintainer reply covered.
    - An escalation the hand labels said to flag, and the reverse.
    - A write that happened before resume, or a write aimed at the source repo.

12. **Not in this version.** Online evals, annotation queues, CI gates, posting to the public repo, multi-tenant isolation, Sandboxes/Engine/Fleet/LLM Gateway, SmithDB, a second region.

## Write `docs/decisions.md`

Six short entries. Each one: decision, alternative, why, what would change your mind.

1. Self-host on their existing GKE, not LangSmith Cloud, and not a new cluster from the published Terraform module.
2. External Cloud SQL, Memorystore, and Cloud Storage. ClickHouse in-cluster on its own pool. Not LangChain Managed ClickHouse, not SmithDB, for v1.
3. LangGraph with five nodes, not one tool-calling loop, and not Deep Agents.
4. `fastapi/fastapi` as the corpus. Read-only. Sink repo for the single write.
5. Interrupt on every run. The write function is not a model tool.
6. One experiment: the same graph with retrieval, and with an empty retriever. Code graders for category and for "did not post." LLM-as-judge only for groundedness and for reply quality.

## Done when

- A person who has not seen this plan can tell which processes run, which stores are external, and what never leaves the GCP project.
- The component names match the self-hosted docs you cited.
- The year-1 numbers are the medium/medium scale point, and the scale section splits UI load from trace load.
- Part 2 failure modes are the same ones step 3 will grade.
- No application source files were added.
