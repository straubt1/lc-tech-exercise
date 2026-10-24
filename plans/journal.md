# Journal

## Decisions

- Which MODEL and why
- Why THESE agents

## Friction

- Limiting number of tool calls (read_file recursion early was a problem)
- As well as token budget to stop things
- Single model throughout, could target specialty agents towards a model better suited for their tasks

## Testing


### Datasets

Upload from disk
```
uv run python -c '
from langsmith import Client
from review.evals import load_spec, sync_dataset
spec = load_spec()
sync_dataset(Client(), spec["examples"], spec.get("description") or "")
'
```

### Expirement

```
uv run python -c '
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(".env"))
from langsmith import Client, evaluate
from review.evals import DATASET, target
evaluate(
    target,
    data=DATASET,
    experiment_prefix=DATASET,
    max_concurrency=1,
    description="What you changed",
    client=Client(),
)
'
```

#### Results

with model = "anthropic:claude-haiku-5-5"
```
View the evaluation results for experiment: 'tf-module-review-b6647a67' at:
https://smith.langchain.com/o/b903f266-4771-4a65-ae1e-cdff888dc287/datasets/3e05bd13-feb4-4db6-87f0-06249c935da4/compare?selectedSessions=b1e1fb78-6408-41b2-a329-c2ebd1a65315


interface median_latency_s=1.95 median_tokens=2759
security median_latency_s=2.47 median_tokens=2671
release median_latency_s=2.34 median_tokens=5640
recommend median_latency_s=4.33 median_tokens=5505
```


with model = "anthropic:claude-sonnet-5-5"
```
View the evaluation results for experiment: 'tf-module-review-f5c4c326' at:
https://smith.langchain.com/o/b903f266-4771-4a65-ae1e-cdff888dc287/datasets/3e05bd13-feb4-4db6-87f0-06249c935da4/compare?selectedSessions=36f37131-8332-4430-b150-519511da932a


interface median_latency_s=3.50 median_tokens=2971
security median_latency_s=3.35 median_tokens=2787
release median_latency_s=2.66 median_tokens=4063
recommend median_latency_s=8.25 median_tokens=5916
```

### Evaluators

Current: code evaluator

Considering LLM as a Judge.

## Evals

`uv run --directory part2 pytest tests/test_evals.py::test_langsmith_experiment -s`

## Important points

- Updating and publishing modules, without proper documentation is a common slow down.

## Questions to be prepared to answer

- What model and why?
- Secret storage and access?

## Flow

Created the plan a few times
Stubbed out agents and tools in python
Implemented Diff agent
- tools -> coded in agent (MCP didnt feel like a good fit)
- prompt updated since the results were trying to assign a version bump but was out of scope

Created evals codified
- unsure how to verify that a test passes

### Retool

We are going to start over - i have deleted all the agent code and diagrams, feel free to look back at the last commit to see what has changed but i do NOT want to carry that flow over.
Only Consider part 2 of the Take-Home Assignment.md
The goal in this prompt is to create the plan, not implement yet

We will create this plan in plans/part2-module-review.md (I have left the old part2-module-release.md for reference only but do not let that file drive decisions, it is completely throw away). Create several steps to this plan that we will implement in order. FIrst step is to frame out the python in a clear and structured way, Avoiding complexity at all costs, but while still functioning. There will likely be 3-5 steps overall


Be as SIMPLE as possible
Use Langchain OSS code and Langgraph python packages everywhere
do not use pydantic unless you have a strong justification
we will use LangSmith to run evaluations, track agent traces, and measure performance metrics. THIS IS CRITICAL so design accordingly.

I wanted to reduce the number of agents and their purpose.

Three Agents:
- Review Agent (async)
  - This looks at a git repo + ref an analyzes it for completeness and best practice
  - Ensures README.md properly shows all the needed things (variables, outputs, etc...) and that they match how they are used
  - Ensure CHANGELOG.md is up to date
  - [Future] examples/ directory has proper examples to help end users
  - Returns:
    - Status: Pass/Fail
    - Findings: [] array of objects if there is any recommendations
      - filename
      - finding
- Version Agent (async)
  - This looks at the git repo + ref, as well as existing tags in the format "vx.x.x" that represent past published versions
  - Checks to see if there are changes between the given ref and the last version published -> describes changes if any
  - Finds current version in CHANGELOG.md
  - Assuming that there are changes in the repo + ref that were made after the last published version, determine what the recommended next version should bump (major.minor.patch)
  - Returns:
    - Suggest Next Version: vx.x.x
    - Findings: [] array of objects if there is any recommendations
      - filename
      - finding
- Recommend Agent (runs after Review and Version agents complete)
  - Takes the findings of previous agents
  - Prints suggestions to output
  - Prompts for Human in the Loop on if suggestions should be created in a PR?
    - yes -> create a structured PR
    - no -> exit



---
Craig
- in order to meet the criteria to release
- take it a step further, what are the things that are outside of you
  - what does this affect outside?
  - go out and consuming workspaces



## Part 1

### Facts (that we made up mostly)

- GKE, standalone cluster
- LangSmith v0.17+
- SmithDB instead

### Data Stores

Postgres
Redis
Blob Storage
Clickhouse

All should be External

ClickHouse is the columnar database that stores LangSmith traces and feedback.
- Grows as trace volume grows
- Large inputs/outputs/attachments go into Blob Storage
- PSQL holds metadata and stays small
- Q: can traces be cleaned up? if so, what is a good retention period?
 