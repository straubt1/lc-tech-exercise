# Part 1 — LangSmith platform architecture

Plan for Part 1 of [Take-Home Assignment.md](Take-Home%20Assignment.md). This file is the plan. Step 1 writes repo notes into [Repo notes](#repo-notes). The architecture write-up is filled into [Architecture](#architecture). Diagrams are the only other files, under `plans/diagrams/`.

No Terraform apply, Helm install, or cluster changes. The assignment asks for a conceptual design. The LangChain module is the source for how a GKE install is shaped and sized, not something we run.

Cloud is GCP. LangSmith runs on its own GKE Standard cluster. The module is [langchain-ai/terraform](https://github.com/langchain-ai/terraform), directory [`modules/gcp`](https://github.com/langchain-ai/terraform/tree/main/modules/gcp). Read a `v0.17.*` tag, not `main`. The root README says `MAJOR.MINOR` is the Helm chart line and `PATCH` is the module revision.

## Primer

Self-hosted LangSmith is the Enterprise product installed with the `langchain/langsmith` Helm chart into a Kubernetes cluster. Chart 0.17.x is the current line. The install runs the product in the customer's project so traces stay under their control. A license key is required. Unless the install is air-gapped, the pods call `https://beacon.langchain.com` to check that license. On an `lcl_` key that call is required at first start: `platform-backend` caches the license in Redis, and with an empty cache it will not start.

This design is a new 0.17 install of the standard chart, scoped to tracing, observability, and evaluations. SmithDB is the only trace store. ClickHouse is disabled. On 0.17 that combination is supported for a new installation: `clickhouse.enabled: false`, with SmithDB ingestion and query both enabled. The history-migration path does not apply, because there is no ClickHouse data to backfill.

### Application services

These are stateless pods. The frontend is the only one users and agents reach. They are the standard chart services that tracing, observability, and evaluations use.

| Service | Role |
| --- | --- |
| `frontend` | Nginx. Serves the UI and proxies API calls. The only service with an external address. |
| `backend` | Product API: projects, datasets, experiments, evaluators, feedback reads. Port 1984. |
| `platform-backend` | Auth, orgs, users, and the high-volume run ingestion API. Port 1986. |
| `queue` | Reads traces and feedback off Redis and writes them to SmithDB. Retries when ingestion is briefly unavailable. |
| `ingest-queue` | Same job as `queue`, separated so a high trace rate can scale on its own. |
| `playground` | Forwards model calls for the UI and for model-graded evaluators. |
| `ace-backend` | Runs custom evaluation code in a restricted environment. |

Insights and Chat ship enabled on chart 0.15.1 and later. This design turns both off. They sit outside tracing, observability, and evaluations, and the module describes Insights as ClickHouse-backed.

Three jobs run at install and upgrade, then exit: Postgres migrations for the operational database, the SmithDB metastore migration, and bootstrap of the first admin. There is no ClickHouse migration job and no ClickHouse history backfill.

### SmithDB

SmithDB is the columnar store for traces and feedback. It runs in the `langsmith` namespace, in cluster mode, which is the 0.17 default: separate services, coordinated by a cluster manager. `smithdb.topology` is a 0.18 value and is left unset.

Durable traces live in a dedicated GCS bucket. A second Cloud SQL instance (Postgres 18) holds segment metadata. Each cache-using pod keeps a disposable copy on local disk. Replacing a pod drops that cache. The bucket is the copy that survives.

| Component | Role | Disk cache | Scaling |
| --- | --- | --- | --- |
| Ingestion | Writes traces as immutable files in the SmithDB bucket | Yes | Horizontal |
| Query | Serves trace reads for the UI and API | Yes | Horizontal |
| Compaction worker | Rewrites stored traces so queries stay fast, and applies TTL expiry | Yes | Horizontal |
| Compaction | Schedules that background work | No | Single instance |
| Cluster manager | Assigns key ranges so related reads and writes land on the same pods | No | Single instance |
| Metastore migration | Creates the metastore schema at install | No | Runs once |

Ingestion and query are reached by pod IP. The cluster manager and compaction are reached by Service name. The cluster network has to allow those pod-IP connections. Clients are `platform-backend`, `queue`, `ingest-queue`, and the SmithDB query pods.

### Where a trace goes

1. An agent SDK sends a run to the frontend, which hands it to `platform-backend`.
2. `platform-backend` pushes the run onto Redis.
3. `queue` and `ingest-queue` pull it off Redis and write it to the SmithDB ingestion pod that owns that key range.
4. Ingestion flushes immutable files to the SmithDB GCS bucket and records segment metadata in the metastore.
5. Query serves later reads from its local cache, and reads through to the bucket on a miss.
6. Compaction worker rewrites segments in the background, including retention expiry.

Postgres never stores the trace bodies. It stores orgs, users, projects, API keys, dataset definitions, experiment records, and settings. Trace volume grows the SmithDB bucket, the metastore's segment catalog, Redis, the ingest workers, the SmithDB ingestion and query pods, and the LangSmith blob bucket.

Large inputs, outputs, errors, and attachments still have a LangSmith blob bucket, separate from the SmithDB bucket. Step 1 confirms which payload fields the 0.17 chart writes there once ClickHouse is disabled.

### Storage

Every durable store is outside the cluster. The chart can run Postgres, Redis, and ClickHouse in-cluster. That is the light tier, for a demo. This design uses none of those in-cluster databases.

The SmithDB disk cache stays on the cluster. It is a cache, not a system of record.

| Store | Holds | Production home on GCP |
| --- | --- | --- |
| PostgreSQL | Transactional metadata | Cloud SQL, private IP, regional HA |
| Redis | Ingest queue, cache, pub/sub | Memorystore, private IP, Standard HA |
| SmithDB metastore | Segment catalog and coordination | A second Cloud SQL, Postgres 18, private IP, regional HA, empty database |
| SmithDB object storage | Durable trace and feedback files | One single-region GCS bucket, no lifecycle expiry |
| Blob storage | Payloads and attachments | A second GCS bucket, with TTL lifecycle rules |
| SmithDB cache | Hot segment bytes for one pod | Local SSD on the tainted SmithDB pool. Ephemeral |

The metastore is never the operational database. The SmithDB bucket is never the blob bucket. GCS lifecycle rules belong on the blob bucket only. Deleting a live object in the SmithDB bucket makes that trace unreadable. Retention of trace rows is compaction's job.

### Feature set

In scope: tracing, observability, and evaluations. That is a standard install of the base chart with the optional add-ons left off.

Left off:

- **ClickHouse.** In-cluster, LangChain-managed, and customer-managed. A new 0.17 install uses SmithDB for both ingestion and query.
- **Insights and Chat.** Chart defaults turn them on. We set them off. No Fernet keys, no model access for those two features.
- **Sandboxes and Engine.** Firecracker microVMs on a tainted `sandbox-host` pool, plus JuiceFS. Out of scope for tracing and eval.
- **Fleet.** The module's `enable_fleet` stays off.
- **LLM Gateway.** Beta as of chart 0.17.1. `agent-gateway` is not installed.
- **LangSmith Deployment.** `enable_deployments` stays false, so `host-backend`, `listener`, and `operator` are absent. Agents report to this platform. They are not hosted on it. The module's `enable_langsmith_deployment` flag installs KEDA and is a different switch. Step 1 says whether the production profile needs KEDA to scale `queue` and `ingest-queue`. We do not turn the flag on in order to host agents.
- **SmithDB history migration.** `smithdb_migration_enabled` stays false. That flag also starts an in-chart Postgres for migration task state, which would put a database back inside the cluster.
- **Beta flags.** Anything else the pinned chart or module marks beta stays off. Step 1 lists those flags.

## Workload we are sizing for

The assignment says to define the requirements. These are the ones the doc will state. Replica counts and machine types wait for Step 1, because the module ships them as sizing profiles.

- InnovateCorp already runs Kubernetes for its own applications. LangSmith does not join that cluster. We design a dedicated GKE Standard cluster: one region, private nodes, three zones, Workload Identity, and Dataplane V2. SmithDB needs tainted node pools and pod-IP access from the LangSmith pods. Both are easier to guarantee on a cluster that only runs this product.
- About 20 people use the UI at once. About 100 traces per second are steady, with bursts toward 1,000.
- The module's `production` profile is the starting point. With SmithDB enabled, that profile selects SmithDB size `medium`. `production-large` is the burst path and selects SmithDB size `large`. The root README describes `production` as about 20 concurrent users and about 100 traces per second, and `production-large` as about 50 users and about 1,000 traces per second. Step 1 checks that those words still match the GCP values files, and records the SmithDB replica counts the profile actually sets.
- One region. Availability is regional HA for both Cloud SQL instances and Standard HA for Memorystore. Disaster recovery is restore-from-backup in that region. SmithDB durability is the bucket plus the metastore backup. The cache is rebuilt on read.
- Recovery point and recovery time are stated after Step 1 reads the Cloud SQL backup settings the module sets on both instances. The app pods are stateless, so the database restore is the long step.

## Locked choices

Service names below match the GCP module. Sizes marked provisional are replaced by Step 1. Change a choice before Step 2 if you disagree. After that, the write-up treats them as given.

- **Cloud.** GCP. Region `us-west2`, the module default, with zone `us-west2-a`. The existing application cluster does not pick the region.
- **Cluster.** A new GKE Standard cluster for LangSmith. Private nodes (`enable_private_nodes`), Cloud NAT for egress, `private_ip_google_access` so nodes reach `storage.googleapis.com` without NAT. Workload Identity on. Release channel `REGULAR`. Dataplane V2. Deletion protection on. Autopilot is off: the module rejects SmithDB on Autopilot.
- **Network.** The module's VPC, subnet, pod CIDR, and service CIDR. LangSmith pods, both Cloud SQL instances, and Memorystore share that VPC on private IPs. Agent SDKs on the existing cluster reach the frontend over the ingress. They do not share this cluster.
- **Install.** Helm chart line pinned by the latest `v0.17.*` tag of `langchain-ai/terraform` (`~0.17.0`, latest 0.17 patch, never 0.18). Namespace `langsmith`. Release name `langsmith`.
- **Trace store.** SmithDB only. Helm sets `clickhouse.enabled: false`, `smithdb.enabled: true`, `smithdb.langsmith.ingestion.enabled: true`, `smithdb.langsmith.query.enabled: true`, and `smithdb.langsmith.migration.enabled: false`. The chart requires one ingestion backend and one query backend, so both SmithDB flags are on at install. This is the new-install path, not the staged dual-write path.
- **Module gap.** The published module variables still describe `clickhouse_source` as `in-cluster`, `langsmith-managed`, or `external`, and describe SmithDB ingestion as writing alongside ClickHouse. Step 1 checks whether the `v0.17.*` tag can render `clickhouse.enabled: false`. If it cannot, the Helm values still disable ClickHouse, and we do not provision a ClickHouse service. No managed ClickHouse host, password, or peering.
- **Tier.** Production, every durable store external: `postgres_source = "external"`, `redis_source = "external"`, `enable_smithdb = true`, `smithdb_metastore_source = "create"`.
- **Postgres.** Cloud SQL, private IP, HA on, deletion protection on. Provisional size is the module default: `POSTGRES_15`, `db-custom-2-8192` (2 vCPU, 8 GB), 50 GB. Step 1 replaces this if `sizing_profile` selects a larger tier. Trace growth is not a reason to scale this database.
- **Redis.** Memorystore for Redis 7, private IP, Standard HA. Provisional size is the module default of 5 GB. The public scale guide asks for more at 100 traces per second. Step 1 uses whichever memory size the production profile sets.
- **SmithDB metastore.** Second Cloud SQL, `POSTGRES_18`, private IP, deletion protection on, SSL mode `ENCRYPTED_ONLY`. HA on, overriding the module default of `smithdb_metastore_high_availability = false`. Provisional tier follows `smithdb_sizing = medium`: `db-custom-6-32768`, 50 GB floor with autoresize. The module's Cloud SQL Auth Proxy sidecar is how SmithDB pods reach it (`smithdb_metastore_use_auth_proxy` resolves to true when the module creates the instance). Empty database, user `smithdb`. Never the operational database.
- **SmithDB bucket.** One single-region GCS bucket. No lifecycle rule that expires objects. Workload Identity: a dedicated Google service account with `roles/storage.objectAdmin` on this bucket, bound to the chart's SmithDB Kubernetes service account. Private Google Access for the data path.
- **SmithDB cache.** `smithdb_cache_storage = "local-ssd"` on the production and production-large sizes. Tainted node pool, label and taint `smithdb-local/instance-store=true:NoSchedule`, Local SSD via ephemeral storage so the cache has capacity. Provisional machine type follows size `medium`. Step 1 records the type, the local-SSD count, the zones where that shape exists, and which workloads the module pins to the pool (ingestion, query, compaction worker) versus the general pool (compaction, cluster manager, metastore migration, the LangSmith app pods).
- **Blob storage.** A second GCS bucket for payloads and attachments. Lifecycle: `ttl_s/` at 14 days, `ttl_l/` at 400 days, matching `storage_ttl_short_days` and `storage_ttl_long_days`. A workspace with a custom retention period needs a matching `ttl_<days>d/` rule, or those objects never expire. Step 1 records whether those pods authenticate with Workload Identity or with GCS HMAC keys. SmithDB itself uses Workload Identity.
- **Ingress.** Envoy Gateway, which the module installs by default (`install_ingress`, `ingress_type = "envoy"`). The frontend is the only route. Step 1 records whether that Gateway is a public address or an internal one. TLS follows the module: `letsencrypt` when a public name is required, or `existing` when InnovateCorp already terminates TLS.
- **Auth.** OIDC single sign-on for people (`authType: mixed`). API keys for SDKs. Basic auth exists to bootstrap the first admin, then stays as break-glass. The module's `enable_sso_oidc` turns basic auth off and can lock the UI if it is set before the first admin exists. Step 1 records the order the module expects.
- **Secrets.** GCP Secret Manager, rendered into Helm values. The root README describes this as different from AWS, where External Secrets Operator syncs SSM. The set is the license key, `apiKeySalt`, JWT secret, the Ed25519 signing JWKS (chart 0.16+), both Cloud SQL connection details, and the Memorystore connection details. `apiKeySalt` is set once. Changing it invalidates every API key. Insights and Chat keys are absent because those features are off. Step 1 confirms the flow against `modules/README.md`.
- **Sizing profile.** `production` for the steady workload, which selects SmithDB `medium`. `production-large` is the documented step up and selects SmithDB `large`. Replica counts, CPU, memory, and HPA targets come from Step 1. They are not copied from the AWS `SIZING.md` or from the public SmithDB scale table.
- **Autoscaling.** Whatever the production values file configures for the LangSmith services, plus the SmithDB replica counts for size `medium`. Expect an HPA on the stateless LangSmith services. Ingestion, query, and compaction worker scale on their own. Compaction and the cluster manager stay single-instance. The general node pool autoscaler adds nodes when app pods cannot schedule. The SmithDB pool scales on its own maximum. Provisional general pool, from the module defaults: `e2-standard-4`, 2 nodes per zone, min 2, max 10, 100 GB disk. Step 1 replaces the machine type if the profile does.
- **Pod network.** Network policy allows `platform-backend`, `queue`, `ingest-queue`, and SmithDB query to open connections to SmithDB pod IPs on the ingestion and query ports. Dataplane V2 enforces that policy. Step 1 records the ports the chart uses.
- **Retention and egress.** Blob-bucket TTL at the Helm defaults above. SmithDB retention is compaction, not a bucket lifecycle. Egress through Cloud NAT: `beacon.langchain.com`, the model endpoints Playground and evaluators call, and the image registries (`docker.io` and the chart registries). Air-gap is out.
- **Feature flags.** `enable_insights`, `enable_polly`, `enable_standalone_insights`, `enable_standalone_polly`, `enable_fleet`, `enable_deployments`, and `enable_agent_builder` stay false. No LLM Gateway. No sandbox pool.

## Deliverables

The assignment asks for architecture documentation and diagrams that show components, external services, deployment, and scalability. These are the pieces, and nothing else.

### Repo notes

Step 1 fills [Repo notes](#repo-notes) in this file. That section is the evidence for every size in the architecture. It is not a second document.

### Sections to write under Architecture

1. **Requirements.** The workload, RPO, RTO, and why LangSmith has a dedicated cluster. Half a page.
2. **Components.** The seven LangSmith services, the SmithDB services, the three jobs, and the trace path versus the metadata path. One diagram.
3. **Storage and what is external.** A table: store, what it holds, the GCP service, why it is outside the cluster. Call out the operational database staying small, the metastore as a separate Postgres 18, both buckets, and the local-SSD cache as ephemeral.
4. **Deployment and placement.** Dedicated VPC, private nodes, Cloud NAT, Private Google Access, namespace, Envoy Gateway, general pool, tainted SmithDB pool, Workload Identity, secrets, and the resource starting point from the production profile. One diagram.
5. **Scaling.** The `production` profile as the steady state and `production-large` as the burst. Which LangSmith services scale on CPU, which follow queue depth, which SmithDB services scale, and which stores are managed. One diagram.
6. **Other considerations.** License egress to Beacon, SSO, the immutable API-key salt, blob TTL versus SmithDB compaction, ACE network limits, backups of both Cloud SQL instances, single-region recovery, upgrades by moving the `v0.17.*` tag, and cost driven by trace volume times retention in the SmithDB bucket.
7. **Set aside.** In-cluster databases, ClickHouse, Autopilot, Insights, Chat, Sandboxes, Engine, Fleet, LLM Gateway, LangSmith Deployment, the history-migration task database, and a second region. One line each on what would make us pick it up.
8. **Speaker outline.** About eight minutes, three beats: components, external services, scaling. This is the Part 1 slice of the 40-minute presentation. The slide deck itself waits until Part 2 is in the same story.

### Diagrams

Follow `.cursor/skills/excalidraw-diagrams/SKILL.md`: edit the JSON, export a PNG at scale 2, read the PNG, fix overlap and clipping. Use an architecture palette (app, data, network) rather than the agent-card legend in that skill.

| File | What it shows |
| --- | --- |
| `plans/diagrams/langsmith-components.excalidraw` | Browser and SDK, the seven LangSmith services, Memorystore as the queue, SmithDB ingestion and query, the metastore and the SmithDB bucket as the trace sinks, the blob bucket, Cloud SQL as metadata. Arrow for the trace path. |
| `plans/diagrams/langsmith-deployment.excalidraw` | Dedicated VPC, private GKE nodes across zones, namespace `langsmith`, general pool and tainted SmithDB pool, Envoy Gateway, both Cloud SQL instances and Memorystore on private IPs, both GCS buckets via Private Google Access, Cloud NAT egress to Beacon and model APIs. |
| `plans/diagrams/langsmith-scale.excalidraw` | `production` beside `production-large`. Groups for CPU autoscaling, ingest scaling, SmithDB scaling, and managed services, using the numbers from Repo notes. |

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
| Existing Kubernetes, cloud of our choice | Requirements, locked choices. GCP, dedicated GKE cluster |
| No IaC | This plan does not add any |

## Steps

### Step 1 — Read the Terraform repo

Deep read of [langchain-ai/terraform](https://github.com/langchain-ai/terraform) at the latest `v0.17.*` tag. The GCP module is the subject. The repo root is in scope because sizing profiles, the chart pin, and the secret flow are defined there and differ by cloud. Write the findings into [Repo notes](#repo-notes). Do not copy the AWS sizing guide into those notes. If a GCP file points at `modules/aws/helm/values/examples/SIZING.md`, record that and then record every place the GCP values differ.

Read, in this order:

- Root `README.md`. Tiers, the `sizing_profile` values, GCP secret flow, and the rule to deploy from a tag.
- `modules/README.md`. How GCP differs from AWS and Azure, including the secret-flow table.
- `modules/gcp/README.md`. The three passes, production versus light, variable defaults, and the SmithDB constraints. Record every statement that still assumes ClickHouse stays enabled.
- `modules/gcp/ARCHITECTURE.md` and `modules/gcp/SERVICES.md`. Placement, ingress, and which pods scale.
- `modules/gcp/SMITHDB.md` and `modules/gcp/QUICK_REFERENCE.md`. Node pools, metastore, bucket, and the ingestion, query, and migration gates.
- `modules/gcp/infra/variables.tf` and the locals or Helm script that apply `sizing_profile` and `smithdb_sizing`. Record the GKE machine type, node counts, Cloud SQL tier, Memorystore memory, and the SmithDB machine type, local-SSD count, and metastore tier for `production` (`medium`) and `production-large` (`large`).
- `modules/gcp/helm/values/values.yaml` and `modules/gcp/helm/values/examples/langsmith-values-sizing-production.yaml` plus `langsmith-values-sizing-production-large.yaml`. For each LangSmith service and each SmithDB service: min replicas, max replicas, CPU request, memory request, and the autoscaler (HPA target or KEDA trigger).
- The values or Terraform that render `clickhouse.enabled`, `smithdb.langsmith.ingestion.enabled`, `smithdb.langsmith.query.enabled`, and `smithdb.langsmith.migration.enabled`. Record whether the tag can disable ClickHouse.
- The values that place ingestion, query, and compaction worker on the tainted pool, and the network-policy or firewall rules for pod-IP access.
- How each GCS bucket is authenticated (Workload Identity or HMAC).

Repo notes answer:

- Which tag was read.
- Whether that tag can disable ClickHouse. If it cannot, the Helm override we will state in the architecture.
- The `production` table and what `production-large` changes, including SmithDB.
- General pool, SmithDB pool, both Cloud SQL instances, Memorystore, and both buckets for that profile.
- What scales on CPU, what scales on queue depth, what SmithDB scales, and what is a managed service.
- Whether KEDA scales ingest, and that `enable_deployments` is a separate flag we leave false.
- Which chart flags turn Insights, Chat, and each beta add-on off.
- Corrections to every provisional size in [Locked choices](#locked-choices).
- Backup settings on both Cloud SQL instances that determine RPO.
- What the chart still writes to the LangSmith blob bucket when ClickHouse is disabled.

Done when the scaling section can be written from Repo notes without guessing a replica count or a machine type.

### Step 2 — Write the architecture

Fill in sections 1–7 under [Architecture](#architecture). Use the locked choices, the primer, and Repo notes. Where they disagree, Repo notes win, and update the locked choice in place. Keep each section short enough to present. The diagrams are named and linked even if the PNGs do not exist yet.

Done when every row of the assignment checklist has a paragraph, and a reader can say what each Cloud SQL holds, what the SmithDB bucket holds, what the blob bucket holds, and why the local SSD is not a backup.

### Step 3 — Draw the three diagrams

Create the three scenes in the deliverables table. Export and inspect each PNG. Link them from the matching sections.

Done when each PNG matches its section and the trace path is readable without the prose.

### Step 4 — Speaker outline

Write section 8. Three beats, about eight minutes total:

1. Components and the path a trace takes, through Redis into SmithDB.
2. The external stores: operational Cloud SQL, Memorystore, the metastore, the SmithDB bucket, and the blob bucket. What stays in the GCP project, and why the local-SSD cache is disposable.
3. What the `production` profile scales when trace volume grows, what `production-large` changes, and what does not grow with traces (the operational Cloud SQL).

End with the add-ons we left out. The one we would add first if InnovateCorp wants to host agents is LangSmith Deployment (`enable_deployments`).

Done when the outline can be read aloud against the three diagrams without introducing a component the doc does not contain.

## Repo notes

Written in Step 1. Leave this heading in place.

## Architecture

Written in Step 2. Leave this heading in place.
