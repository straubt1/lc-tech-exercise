# Presentation

http://langchain-presentation.arcbox.local/

Slide outline for `present/index.html`. Copy lives here. The deck is updated from this file once the outline is set.

Reveal.js vertical slides: right and left move between stacks. Down and up move inside the current stack. In the markup, a stack is a parent `<section>` whose children are the slides. The first child is the slide you land on.

Cover Page
Agenda
LangSmith Platform Architecture (Part 1)
- Considerations
- Platform Component Architecture
- External Service Dependencies
- Scalability Approach
Agent Development (Part 2)
- What we built
- Agent Architecture
- Evaluation Results
- Improvements to KPIs (Business Value)
Friction Log
- Challenges or limitations
- What we would ask for
Questions
Closing/Thank You

## Slides

A `###` heading is a horizontal slide. `####` headings under it are the vertical slides below that one. A `###` with no children is a single slide.

First pass. Section titles on the slide are shorter than the outline heading. The friction slides are a draft from the design and the eval plan.

### Cover Page

```text
type: cover
kicker: InnovateCorp
title: LangSmith Self-hosted
lede: Deployment, Adoption, and Scale.
meta:
  - Tom Straub
  - Architect
  - Tuesday, October 27th, 2026
notes: Introduction, some of us have met, if not, here is me in 10 seconds
```

### Agenda

```text
type: points
kicker: Today
heading: Three parts
points:
  - [Deployment] LangSmith Platform Architecture
  - [Adoption] Terraform Module Review Agent Development
  - Friction Log.
  - Q&A
notes: Level set on agenda, quick pause
```

### LangSmith Platform Architecture (Part 1)

```text
type: section
index: 01
title: Platform
lede: Self-hosted LangSmith, on a dedicated GKE cluster in us-west2.
notes: Conceptual design for technical review. No infrastructure code. The picture is plans/diagrams/langsmith-deployment.png. Walk it on the component slide.
```

#### Considerations

```text
type: points
kicker: Platform
heading: What we designed around
points:
  - A dedicated GKE Standard cluster, private nodes, three zones.
  - Agents stay where they are and send traces here.
  - Durable data sits in managed services, outside the cluster.
  - A standard install now. Hosted agents come later.
notes: Staff sign in with OIDC. Agents use API keys. The API key salt is set once and is not rotated. Observability, evaluation, prompts, and Chat are in. Insights stays off, because that path still expects ClickHouse. LangSmith Deployment, KEDA, and agent servers are a later phase and are not sized here.
```

#### Platform Component Architecture

```text
type: diagram
kicker: Platform
heading: Where each piece sits
image: assets/langsmith-deployment.png
notes: General pool runs the interface, the APIs, ingest, the playground, the eval runtime, and Chat. SmithDB cache nodes use local SSD. That disk is a cache and is rebuilt from the SmithDB GCS bucket. It is not the durable copy. Point at the diagram while you say this. In the cluster: Envoy is the only door, stateless services share the general pool, and SmithDB has its own cache and compute pools. Beside the cluster: two Cloud SQL instances and Memorystore on private addresses, plus two GCS buckets. SmithDB requires its own single-region bucket in us-west2 for traces and feedback. The blob bucket is multi-region. Pods use Workload Identity. Nodes reach Cloud Storage through Private Google Access.
```

#### External Service Dependencies

```text
type: split
kicker: Platform
heading: Infrastructure
left:
  title: Application
  body: A dedicated GKE Standard cluster.
  points:
    - General node pool. Interface, APIs, ingest, playground, evals, and Chat.
    - Cache node pool [SmithDB] Writes and reads. Local SSD is a cache.
    - Compute node pool [SmithDB] Compaction and coordination.
right:
  title: Storage
  body:
    - Cloud SQL. Users, projects, datasets, experiments, and Chat.
    - Cloud SQL [SmithDB] Metastore, empty and separate.
    - Memorystore. Ingest queue, cache, and Chat.
    - GCS bucket [SmithDB] Traces and feedback.
    - Blob GCS bucket. Payloads and attachments.
notes: Three node pools. General runs the interface, the APIs, ingest, the playground, the eval runtime, and Chat. The SmithDB cache pool accepts writes and serves reads. Its local SSD is a cache. The SmithDB compute pool runs compaction and coordination. Both Cloud SQL instances are PostgreSQL 18 with regional high availability. The platform database also holds organizations and API keys. SmithDB requires an empty metastore on its own instance, because that catalog records where trace data was written. Memorystore is Standard high availability and also holds Chat's queue. SmithDB requires a GCS bucket. It is single-region in us-west2, holds the durable copy of traces and feedback, and has no lifecycle expiry. Compaction applies retention. The blob GCS bucket is multi-region us. Short-lived objects expire at 14 days and long-lived objects at 400 days. Recovery from a lost region is a restore in us-west2.
```

#### Scalability Approach

```text
type: split
kicker: Platform
heading: Scaling
left:
  title: The size we start at
  body: About 20 concurrent users and 100 traces a second, with bursts toward 1,000.
right:
  title: The size we move to
  body: About 50 concurrent users and 1,000 traces a second, when the first ranges stay full.
  points:
    - Redis - 13 GB to 26 GB.
    - [SmithDB] Cloud SQL - A larger metastore.
    - [SmithDB] Cache and compute - Larger machines.
    - [SmithDB] GCS bucket - Grows with retained traces.
    - Blob GCS bucket - Grows with payloads.
notes: Stateless pods scale at 50 percent CPU or 80 percent memory. Queue workers also scale when Redis has a backlog. SmithDB moves from the medium configuration to the large one. Ingest, query, and compaction scale on their own, up to 10. The scheduler and the cluster manager stay at one replica, on a larger machine. Cache nodes go from n2-standard-32 to n2-standard-64. Compute nodes go from n2-standard-8 to n2-standard-16. The SmithDB metastore goes from 6 vCPU and 32 GB to 10 vCPU and 64 GB. Platform Cloud SQL stays at 2 vCPU and 8 GB. Its disk may grow. Memorystore goes from 13 GB to 26 GB. Published guidance wants more backend replicas than this first size allows. Sitting on that cap is the signal to move up.
```

#### Bring your own cloud

```text
type: bonus
kicker: BYOC
heading: If operating this is more than you want, we can talk about bring your own cloud.
notes: Bonus, after the sizing slide. If running the cluster and the data services is more than they want to take on, LangSmith has bring-your-own-cloud options. Offer to discuss them. Do not design BYOC on this slide.
```

### Agent Development (Part 2)

```text
type: section
index: 02
title: Agents
lede: A module review that stops before it opens a pull request.
notes: The domain is publishing a Terraform module. The slowdown is a README, a changelog, or a security finding that does not match the code. Default repo is straubt1/terraform-aws-object-storage. The picture is plans/diagrams/module-review-v4.excalidraw.
```

#### What we built

```text
type: points
kicker: Agents
heading: A review before the tag
points:
  - The work is a Terraform module that is ready to publish.
  - Interface, security, and release read the repo in parallel.
  - Recommend drafts the files and the pull request.
  - A person answers yes or no before GitHub is called.
notes: Interface compares generated Terraform docs with the README. Security runs Trivy and keeps HIGH and CRITICAL. Release reads the latest tag and the diff, then names the next version. Recommend edits at most ten of the files those findings named. Check has no model. A missing ref ends the run.
```

#### Agent Architecture

```text
type: diagram
kicker: Agents
heading: Agent Architecture
image: assets/module-review-v4.png
notes: Point at the diagram. Three specialists, one writer, and a LangGraph interrupt. Tools fetch the repo. Models return a status and findings. Every publish waits on a person. Recommend stops at ten files. Only a yes opens the pull request. Specialists do not edit files. If the diff is empty, release skips the model and says there is nothing to ship. GH_TOKEN is read from the environment. It is not a tool argument, not in a prompt, and not on graph state. The live compare redacts it before the span is stored.
```

#### Evaluation Results

```text
type: cards
kicker: Agents
heading: What the evals showed
cards:
  - title: The set
    body: Seven frozen modules. The agents call the same tools and receive canned files and diffs.
  - title: The bar
    body: Five scores, each pass or fail. A scenario counts only when all five pass.
  - title: The cost
    body: Median time and tokens for each agent, read off the latest experiment.
notes: Dataset name is tf-module-review. The five keys are interface status, security status, release status, suggested version, and the set of finding files. Do not quote a pass rate until an experiment is on screen. Every current row expects security to pass. Recommend's rewritten files are not scored yet. The printed medians are the number for the third card.
```

#### Improvements to KPIs (Business Value)

```text
type: cards
kicker: Agents
heading: Value before the module is tagged
cards:
  - title: Self-service
    body: The module is the interface teams use to build infrastructure. Clear variables and usable settings are what let that scale. Interface gaps become edits on the next release.
  - title: The right bump
    body: Major, minor, and patch are applied inconsistently. Every candidate gets the same recommendation from the org rule, before the tag.
  - title: Caught in development
    body: The same checks run on every upcoming release. A person approves the pull request. Consumers do not find the miss.
notes: Two outcomes. Catch problems while the release is still in development, and leave a module that is easier to use.

  Self-service is the point of the catalog. A missing description, a README that drifted, or a setting that is hard to use becomes a ticket. The interface check is the usage recommendation. Recommend writes the file. The person decides whether it ships.

  The bump is the contract consumers plan around. The release agent does not invent a scheme. A breaking change is major. A new optional variable or output is minor. Anything else is a patch. Applying that on every ref is how the recommendation stays consistent once there are more modules than reviewers.

  KPIs, as directions. This exercise has no production baseline. The evals measure whether status, bump, and finding files are right. These are what that accuracy is for.

  - Adoption time. Consumers spend less time decoding the module.
  - Bump accuracy. Share of tags that match the org rule.
  - Escaped defects. Interface, security, and changelog misses found on the candidate ref, before the tag.
  - Review capacity. Specialists run in parallel. A person only says yes or no.

  After launch, write that yes or no back onto the trace. A yes on a ready release is the good case. A no when the release is not ready is also a good case. A tagged module that still misses is the number to drive down.
```

### Friction Log

```text
type: section
index: 03
title: Friction
lede: Where the tools slowed the work, and what would fix it.
notes: Product feedback. One item per slide is the shape, three is the cap. This pass is inferred from the design and the eval plan. Drop anything you did not actually hit.
```

#### Challenges or limitations

```text
type: points
kicker: Friction
heading: What got in the way
points:
  - The eval stops at the human gate, so the pull request is never scored.
  - One drifted row fails the suite. The previous experiment is another view.
notes: The gate came up because interrupt returns before GitHub is called, and the experiment does not resume. The strict bar is intentional, and it makes a one-row prompt regression loud.
```

#### What we would ask for

```text
type: points
kicker: Friction
heading: What we would ask for
points:
  - Let a dataset example carry a scripted yes or no for the interrupt.
  - A scorer that checks the required tool calls, not only the final fields.
  - A score for the rewritten file against the finding it was meant to fix.
notes: Median tokens and latency per named node are printed from the experiment runs today. Asking for that on the experiment page is the product request. Tool trajectory and a changelog-heading score are the next evaluators. A model can name the right version without reading the diff, and the current scores still pass. A token is stripped with a hand-written span on the live compare. Keep the tone to a log of what would have saved time.
```

### Questions

```text
type: questions
heading: Questions
notes: Stop. Take questions in this order. Platform, then agents, then the business number. Light slide. The word is centered.
```

### Closing/Thank You

```text
type: thanks
kicker: InnovateCorp
title: Thank you
lede: Deployment, Adoption, and Scale.
meta:
  - Tom Straub
  - October 2026
notes: Close. Thank them.
```




## Slide Types

Ten layouts. Every slide sets `type` to one of these names. `notes` is speaker notes on every type. Press `S` in the deck to read them.

Light slides use the black logo on `#f2faff`. The section slide uses the white logo on `#030710`.

### Cover

Opening slide. Large title, one lede, a two-item footer, and the arc graphic.

```text
type: cover
kicker:
title:
lede:
meta:
  -
  -
notes:
```

### Section

Dark divider that opens a stack. A short index, a large title, and one lede.

```text
type: section
index:
title:
lede:
notes:
```

### Points

Content slide. A heading and a short list. Three to five lines.

```text
type: points
kicker:
heading:
points:
  -
  -
  -
notes:
```

### Diagram

Content slide. A heading and one image. The image path is relative to `present/`. Copy the file into `present/assets` so the deck server can load it.

```text
type: diagram
kicker:
heading:
image:
notes:
```

### Pill

Inline label used beside SmithDB infrastructure. In the outline, write it as `[SmithDB]`.

```html
<span class="pill">SmithDB</span>
```

### Split

Content slide. A heading and two columns. Each column is a title and one paragraph.

```text
type: split
kicker:
heading:
left:
  title:
  body:
right:
  title:
  body:
notes:
```

### Cards

Content slide. A heading and three cards. Each card is a title and one paragraph.

```text
type: cards
kicker:
heading:
cards:
  - title:
    body:
  - title:
    body:
  - title:
    body:
notes:
```

### Bonus

Dark aside. A short kicker and one large sentence. Use it when the offer should stand apart from the content slides.

```text
type: bonus
kicker:
heading:
notes:
```

### Statement

Content slide. One large sentence and an optional byline. Styled in the deck and unused so far.

```text
type: statement
kicker:
statement:
byline:
notes:
```

### Questions

Light slide. One centered heading.

```text
type: questions
heading:
notes:
```

### Thanks

Closing slide. Same shape as Cover.

```text
type: thanks
kicker:
title:
lede:
meta:
  -
  -
notes:
```
