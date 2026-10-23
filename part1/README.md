# Part 1

Dumping notes here for now

## Part 1: LangSmith Platform Architecture & Design

Design and document a conceptual architecture for deploying LangSmith Platform (self-hosted) to support InnovateCorp's agent operations.

Your architecture should demonstrate your understanding of the LangSmith Platform's core components. Refer to the [LangSmith self-hosted documentation](https://docs.langchain.com/langsmith/self-hosted) to identify the key services and components that make up a self-hosted LangSmith Platform installation.

Identify the required storage services and explain which ones can or should be externalized for production scaling purposes. Document your deployment architecture showing how LangSmith Platform components would be deployed, including component placement and resource considerations.

Explain your approach to scaling LangSmith Platform components and any other considerations you've identified. You can define the specific requirements and constraints based on your design choices.

InnovateCorp has existing Kubernetes infrastructure. You can choose any cloud provider and region that best fits your design.

Note: Focus on conceptual architecture and understanding of LangSmith Platform (self-hosted) components. No Infrastructure as Code scripts are required, just high-level architectural diagrams and documentation.

---

For Part 1 (LangSmith Platform Architecture), provide a technical explanation covering LangSmith Platform component architecture, external service dependencies, and your scalability approach.

What to Submit

- Submit architecture documentation including diagrams that show LangSmith Platform components, external services, deployment architecture, and scalability design.
- Submit a presentation deck covering the LangSmith Platform architecture overview, technical explanation for both parts, evaluation results, business impact, and product feedback.

## Design Document

filename: [InnovateCorp] LangSmith Self-Managed Design Document.md

Sections
- Purpose: why does this doc exist, 1-3 sentences, call out customer
- Changelog: quick table on iterations to show history, version, date, author, and notes
- LangSmith Platform
  - Considerations: The design constraints for this deployment for the Customer, production, simple, etc...
  - Deployment Architecture: Diagram of the infra, outline high level moving parts
  - Scaling: Infrastructure sizing today (and what might be needed in the future)
- References: quick links to a few key items (no more than 5)


### Infra

GKE Cluster
- standalone
- three AZ's

Cloud SQL
- Regional HA

Redis
- Standard HA

GCS Bucket
- 

SmithDB
- GKE Node Pools (Instance Store and Compute)
- Postgres DB
  - Regional
- GCS Bucket
  - Write Heavy


| Store | Holds | Production home on GCP |
| --- | --- | --- |
| PostgreSQL | Transactional metadata | Cloud SQL, private IP, regional HA |
| Redis | Ingest queue, cache, pub/sub | Memorystore, private IP, Standard HA |
| SmithDB metastore | Segment catalog and coordination | A second Cloud SQL, Postgres 18, private IP, regional HA, empty database |
| SmithDB object storage | Durable trace and feedback files | One single-region GCS bucket, no lifecycle expiry |
| Blob storage | Payloads and attachments | A second GCS bucket, with TTL lifecycle rules |
| SmithDB cache | Hot segment bytes for one pod | Local SSD on the tainted SmithDB pool. Ephemeral |

### Notes

- Install base LangSmith self-hosted into a dedicated Kubernetes Cluster on GCP.
  - The base install covers all of company needs and is the first step of any self-hosted LangSmith Deployment
  - As company needs additional features of LangSmith, those features can be enabled with additional infrastructure (not needed yet) - in other words, your LangSmith installation can grow with you over time
- Disaster Recovery - backups for each data layer and Kubernetes
- Consider if we mention Insights and Chat - requires encryption key per feature and model
- Turning off Insights since there was confusion on if SmithDB supports it or not
  - ClickHouse. Chat fits the current SmithDB-only design. Insights does not, as the module documents it. The Insights overlay still requires ClickHouse (clickhouse_source of langsmith-managed or external), and the standalone Insights path says the same thing. SmithDB does not satisfy that dependency. Enabling Insights on this deployment means adding ClickHouse back, or confirming with LangChain that the 0.17 chart can serve Insights from SmithDB alone.


https://docs.langchain.com/langsmith/self-host-dependency-versions

