# Part 1 — LangSmith platform architecture

Plan for Part 1 of [Take-Home Assignment.md](Take-Home%20Assignment.md). This file is the plan. Step 1 writes repo notes into [Repo notes](#repo-notes). The architecture write-up is filled into [Architecture](#architecture). Diagrams are the only other files, under `plans/diagrams/`.

No Terraform apply, Helm install, or cluster changes. The assignment asks for a conceptual design. The LangChain module is the source for how a GKE install is shaped and sized, not something we run.

Cloud is GCP. The cluster is GKE. The module is [langchain-ai/terraform](https://github.com/langchain-ai/terraform), directory [`modules/gcp`](https://github.com/langchain-ai/terraform/tree/main/modules/gcp). Read a `v0.17.*` tag, not `main`. The root README says `MAJOR.MINOR` is the Helm chart line and `PATCH` is the module revision.

## Primer

Self-hosted LangSmith is the Enterprise product installed with the `langchain/langsmith` Helm chart into a Kubernetes cluster. Chart 0.17.x is the current line. The install runs the product in the customer's project so traces stay under their control. A license key is required. Unless the install is air-gapped, the pods call `https://beacon.langchain.com` to check that license. On an `lcl_` key that call is required at first start: `platform-backend` caches the license in Redis, and with an empty cache it will not start.

The base install is observability, evaluation, prompt engineering, Insights, and Chat. Sandboxes, Engine, Fleet, LLM Gateway, and LangSmith Deployment are optional add-ons. This design uses the base install on the module's production tier.

### Application services

These are stateless pods. The frontend is the only one users and agents reach.

| Service | Role |
| --- | --- |
| `frontend` | Nginx. Serves the UI and proxies API calls. The only service with an external address. |
| `backend` | Product API: projects, datasets, prompts, hub, feedback reads. Port 1984. |
| `platform-backend` | Auth, orgs, users, and the high-volume run ingestion API. Port 1986. |
| `queue` | Reads traces and feedback off Redis and writes them to ClickHouse and blob storage. Retries when the database is briefly unavailable. |
| `ingest-queue` | Same job as `queue`, separated so a high trace rate can scale on its own. |
| `playground` | Forwards Playground requests to model providers. |
| `ace-backend` | Runs custom evaluation code in a restricted environment. |

Three jobs run at install and upgrade, then exit: Postgres migrations, ClickHouse migrations, and bootstrap of the first admin.

### Where a trace goes

1. An agent SDK sends a run to the frontend, which hands it to `platform-backend`.
2. `platform-backend` pushes the run onto Redis.
3. `queue` and `ingest-queue` pull it off Redis.
4. Span and feedback rows land in ClickHouse. Large inputs, outputs, errors, and attachments land in GCS.

Postgres never stores the trace bodies. It stores orgs, users, projects, API keys, prompt hub records, dataset definitions, and settings. Trace volume grows ClickHouse, Redis, the ingest workers, and the bucket.

### Storage

The chart can run Postgres, Redis, and ClickHouse inside the cluster. The module calls that the light tier, for a demo or proof of concept. The production tier points the chart at Cloud SQL, Memorystore, and LangChain-managed ClickHouse. GCS is required on every tier. The module says trace payloads must go to GCS and must not live in ClickHouse. In-cluster ClickHouse is a single pod with no replication and no backups.

| Store | Holds | Production home on GCP |
| --- | --- | --- |
| PostgreSQL | Transactional metadata | Cloud SQL, private IP, regional HA |
| Redis | Ingest queue, cache, pub/sub | Memorystore, private IP, Standard HA |
| ClickHouse | Traces and feedback (columnar) | LangChain-managed ClickHouse (`clickhouse_source = "langsmith-managed"`) |
| Blob storage | Run inputs, outputs, attachments | One GCS bucket |
| SmithDB | Optional trace store on chart 0.17 | Off for this design |

SmithDB runs in the same namespace and Helm release as ClickHouse. Turning it on adds a second Cloud SQL (Postgres 18, its metastore), a second GCS bucket with no lifecycle rules, a Workload Identity account, and two tainted GKE node pools. GKE Autopilot cannot host those pools. Leave it off. Step 1 records the cost from `modules/gcp/SMITHDB.md` so the set-aside line is accurate.

### What we are not installing

- **Sandboxes and Engine.** Firecracker microVMs on a tainted `sandbox-host` pool (N2, nested virtualization) plus JuiceFS. Autopilot cannot run that pool. Useful later, not for tracing and eval.
- **Fleet.** Separate feature services. The module's `enable_fleet` is off by default.
- **LLM Gateway.** Beta as of chart 0.17.1.
- **LangSmith Deployment.** Two flags in the module, and they are not the same thing. `enable_langsmith_deployment` installs KEDA. `enable_deployments` installs `host-backend`, `listener`, and `operator`, and each deployed graph then gets its own API server, queue, Redis, and Postgres. Part 1 is the platform agents report to. Draw Deployment as a later add-on, outside the resource budget. Step 1 confirms both flags.

Insights and Chat stay on. They are part of the base chart from 0.15.1 onward. Each needs its own Fernet encryption key and a path to a model provider.

## Workload we are sizing for

The assignment says to define the requirements. These are the ones the doc will state. Replica counts and machine types wait for Step 1, because the module ships them as sizing profiles.

- InnovateCorp already runs Kubernetes. We treat that cluster as GKE Standard in one region, private nodes, three zones, Workload Identity, and Dataplane V2. We add namespace `langsmith` and the managed data services in the same VPC. We do not design a new cluster. The module can create a cluster; we use it as the picture of what to attach, not as a greenfield build.
- About 20 people use the UI at once. About 100 traces per second are steady, with bursts toward 1,000.
- The module's `production` profile is the starting point. `production-large` is the burst path. The root README describes `production-large` as about 50 concurrent users and about 1,000 traces per second. Step 1 checks that those words still match the GCP values files.
- One region. Availability is regional HA for Cloud SQL and Standard HA for Memorystore. Disaster recovery is restore-from-backup in that region.
- Recovery point and recovery time are stated after Step 1 reads the Cloud SQL backup settings the module actually sets. The app pods are stateless, so the database restore is the long step.

## Locked choices

Service names below match the GCP module. Sizes marked provisional are replaced by Step 1. Change a choice before Step 2 if you disagree. After that, the write-up treats them as given.

- **Cloud.** GCP. Region is the region of the existing GKE cluster. If we have to name one, `us-west2`, the module default, with zone `us-west2-a`.
- **Cluster.** GKE Standard. Private nodes (`enable_private_nodes`), Cloud NAT for egress, `private_ip_google_access` so nodes reach `storage.googleapis.com` without NAT. Workload Identity on. Release channel `REGULAR`. Dataplane V2. Autopilot is off: the module cannot place SmithDB or sandbox pools there, and Standard is how the sizing profiles pick a machine type.
- **Install.** Helm chart line pinned by the latest `v0.17.*` tag of `langchain-ai/terraform` (`~0.17.0`, latest 0.17 patch, never 0.18). Namespace `langsmith`.
- **Tier.** Production: `postgres_source = "external"`, `redis_source = "external"`, `clickhouse_source = "langsmith-managed"`. The module default for ClickHouse is `in-cluster`. We override it.
- **Postgres.** Cloud SQL, private IP, HA on, deletion protection on. Provisional size is the module default: `POSTGRES_15`, `db-custom-2-8192` (2 vCPU, 8 GB), 50 GB. Step 1 replaces this if `sizing_profile` selects a larger tier. Trace growth is not a reason to scale this database.
- **Redis.** Memorystore for Redis 7, private IP, Standard HA. Provisional size is the module default of 5 GB. The public scale guide asks for more at 100 traces per second. Step 1 uses whichever memory size the production profile sets.
- **Blob storage.** One GCS bucket. Lifecycle: `ttl_s/` at 14 days, `ttl_l/` at 400 days, matching `storage_ttl_short_days` and `storage_ttl_long_days`. A workspace with a custom retention period needs a matching `ttl_<days>d/` rule, or those objects never expire. Step 1 records whether pods authenticate with Workload Identity or with GCS HMAC keys. The quickstart shows HMAC. The IAM module wires Workload Identity. The production values file decides.
- **ClickHouse.** LangChain-managed, not a pod. Payloads stay in the customer's bucket. Step 1 records how the module expects the cluster to reach it (peering or Private Service Connect) and what capacity the production profile asks for.
- **Ingress.** Envoy Gateway, which the module installs by default (`install_ingress`, `ingress_type = "envoy"`). The frontend is the only route. Step 1 records whether that Gateway is a public address or an internal one. TLS follows the module: `letsencrypt` when a public name is required, or `existing` when InnovateCorp already terminates TLS.
- **Auth.** OIDC single sign-on for people (`authType: mixed`). API keys for SDKs. Basic auth exists to bootstrap the first admin, then stays as break-glass.
- **Secrets.** GCP Secret Manager, rendered into Helm values. The root README describes this as different from AWS, where External Secrets Operator syncs SSM. The set is the license key, `apiKeySalt`, JWT secret, Insights Fernet key, Chat Fernet key, the Ed25519 signing JWKS (chart 0.16+), and the Cloud SQL and Memorystore connection details. `apiKeySalt` is set once. Changing it invalidates every API key. Step 1 confirms the flow against `modules/README.md`.
- **Sizing profile.** `production` for the steady workload. `production-large` is the documented step up. Replica counts, CPU, memory, and HPA targets come from Step 1. They are not copied from the AWS `SIZING.md`.
- **Autoscaling.** Whatever the production values file configures. Expect an HPA on the stateless services and a separate mechanism for `queue` and `ingest-queue`. KEDA is in the module because `enable_langsmith_deployment` defaults to true. Step 1 says whether KEDA scales the ingest workers or only the Deployment add-on. The GKE node pool autoscaler adds nodes when pods cannot schedule. Provisional pool, from the module defaults: `e2-standard-4`, 2 nodes per zone, min 2, max 10, 100 GB disk. Step 1 replaces the machine type if the profile does.
- **Retention and egress.** TTL at the Helm defaults above. Egress through Cloud NAT: `beacon.langchain.com`, the model endpoints Insights, Chat, and Playground call, and the image registries (`docker.io` and the add-on registries). Air-gap is out.
- **Deployment add-on.** Documented and drawn as a later phase. Not in the v1 budget. `enable_deployments` stays false.

## Deliverables

The assignment asks for architecture documentation and diagrams that show components, external services, deployment, and scalability. These are the pieces, and nothing else.

### Repo notes

Step 1 fills [Repo notes](#repo-notes) in this file. That section is the evidence for every size in the architecture. It is not a second document.

### Sections to write under Architecture

1. **Requirements.** The workload, RPO, RTO, and the existing-GKE assumption. Half a page.
2. **Components.** The seven services, the three jobs, and the trace path versus the metadata path. One diagram.
3. **Storage and what is external.** A table: store, what it holds, the GCP service, why it is outside the cluster. Call out Postgres staying small, GCS being required, ClickHouse being managed, and SmithDB left off.
4. **Deployment and placement.** VPC, private nodes, Cloud NAT, Private Google Access, namespace, Envoy Gateway, node pool, Workload Identity, secrets, and the resource starting point from the production profile. One diagram.
5. **Scaling.** The `production` profile as the steady state and `production-large` as the burst. Which services scale on CPU, which follow queue depth, and which are managed. One diagram.
6. **Other considerations.** License egress to Beacon, SSO, the immutable API-key salt, TTL aligned with GCS lifecycle, ACE network limits, Cloud SQL backups, single-region recovery, upgrades by moving the `v0.17.*` tag, and cost driven by trace volume times retention.
7. **Set aside.** In-cluster databases, Autopilot, SmithDB, Sandboxes, Fleet, LLM Gateway, LangSmith Deployment, and a second region. One line each on what would make us pick it up.
8. **Speaker outline.** About eight minutes, three beats: components, external services, scaling. This is the Part 1 slice of the 40-minute presentation. The slide deck itself waits until Part 2 is in the same story.

### Diagrams

Follow `.cursor/skills/excalidraw-diagrams/SKILL.md`: edit the JSON, export a PNG at scale 2, read the PNG, fix overlap and clipping. Use an architecture palette (app, data, network) rather than the agent-card legend in that skill.

| File | What it shows |
| --- | --- |
| `plans/diagrams/langsmith-components.excalidraw` | Browser and SDK, the seven services, Memorystore as the queue, managed ClickHouse and GCS as the trace sinks, Cloud SQL as metadata. Arrow for the trace path. |
| `plans/diagrams/langsmith-deployment.excalidraw` | VPC, private GKE nodes across zones, namespace `langsmith`, Envoy Gateway, Cloud SQL and Memorystore on private IPs, GCS via Private Google Access, managed ClickHouse, Cloud NAT egress to Beacon and model APIs. |
| `plans/diagrams/langsmith-scale.excalidraw` | `production` beside `production-large`. Groups for CPU autoscaling, ingest scaling, and managed services, using the numbers from Repo notes. |

Each `.excalidraw` has a `.png` beside it. The markdown links the PNG.

### Assignment checklist

| Ask | Where it is answered |
| --- | --- |
| Core components of a self-hosted install | Components section, components diagram |
| Required storage, and what to externalize | Storage section |
| Deployment, placement, resources | Deployment section, deployment diagram |
| Scaling approach | Scaling section, scale diagram, backed by Repo notes |
| Other considerations | Considerations section |
| Requirements defined by us | Requirements section |
| Existing Kubernetes, cloud of our choice | Locked choices, deployment section |
| No IaC | This plan does not add any |

## Steps

### Step 1 — Read the Terraform repo

Deep read of [langchain-ai/terraform](https://github.com/langchain-ai/terraform) at the latest `v0.17.*` tag. The GCP module is the subject. The repo root is in scope because sizing profiles, the chart pin, and the secret flow are defined there and differ by cloud. Write the findings into [Repo notes](#repo-notes). Do not copy the AWS sizing guide into those notes. If a GCP file points at `modules/aws/helm/values/examples/SIZING.md`, record that and then record every place the GCP values differ.

Read, in this order:

- Root `README.md`. Tiers, the four `sizing_profile` values, GCP secret flow, and the rule to deploy from a tag.
- `modules/README.md`. How GCP differs from AWS and Azure, including the secret-flow table.
- `modules/gcp/README.md`. The three passes, production versus light, variable defaults, and the SmithDB and sandbox constraints.
- `modules/gcp/ARCHITECTURE.md` and `modules/gcp/SERVICES.md`. Placement, ingress, and which pods scale.
- `modules/gcp/QUICK_REFERENCE.md` if it lists sizes.
- `modules/gcp/infra/variables.tf` and the locals or Helm script that apply `sizing_profile`. Record the GKE machine type, node counts, Cloud SQL tier, and Memorystore memory for `production` and `production-large`.
- `modules/gcp/helm/values/values.yaml` and `modules/gcp/helm/values/examples/langsmith-values-sizing-production.yaml` plus `langsmith-values-sizing-production-large.yaml`. For each app service: min replicas, max replicas, CPU request, memory request, and the autoscaler (HPA target or KEDA trigger).
- The values or Terraform that set `clickhouse_source = "langsmith-managed"`, and how GCS auth is set (Workload Identity or HMAC).

Repo notes answer:

- Which tag was read.
- The `production` table and what `production-large` changes.
- Node pool shape, Cloud SQL, Memorystore, and GCS for that profile.
- What scales on CPU, what scales on queue depth, and what is a managed service.
- Whether KEDA scales ingest, the Deployment add-on, or both.
- Corrections to every provisional size in [Locked choices](#locked-choices).
- Backup settings that determine RPO.

Done when the scaling section can be written from Repo notes without guessing a replica count or a machine type.

### Step 2 — Write the architecture

Fill in sections 1–7 under [Architecture](#architecture). Use the locked choices, the primer, and Repo notes. Where they disagree, Repo notes win, and update the locked choice in place. Keep each section short enough to present. The diagrams are named and linked even if the PNGs do not exist yet.

Done when every row of the assignment checklist has a paragraph, and a reader can say what Cloud SQL holds, what ClickHouse holds, and why the GCS bucket exists.

### Step 3 — Draw the three diagrams

Create the three scenes in the deliverables table. Export and inspect each PNG. Link them from the matching sections.

Done when each PNG matches its section and the trace path is readable without the prose.

### Step 4 — Speaker outline

Write section 8. Three beats, about eight minutes total:

1. Components and the path a trace takes.
2. The four stores, why each one is external, and what stays in the GCP project.
3. What the `production` profile scales when trace volume grows, what `production-large` changes, and what does not grow (Cloud SQL).

End with the add-ons we left out and the one we would add first if InnovateCorp wants to host agents (LangSmith Deployment, `enable_deployments`).

Done when the outline can be read aloud against the three diagrams without introducing a component the doc does not contain.

## Repo notes

Written in Step 1. Leave this heading in place.

## Architecture

Written in Step 2. Leave this heading in place.
