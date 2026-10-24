# LangSmith evaluation plan

How this repo answers the Part 2 request in [Take-Home Assignment.md](Take-Home%20Assignment.md):

> Create a comprehensive evaluation plan with a test dataset covering diverse scenarios. Use LangSmith to run evaluations, track agent traces, and measure performance metrics. Define custom evaluation metrics relevant to your domain and implement them using LangSmith's evaluation capabilities.

The agent under test is the module reviewer in [part2-module-review.md](part2-module-review.md) and [diagrams/module-review-v4.md](diagrams/module-review-v4.md). The domain decision is whether a Terraform module is ready to publish: interface docs match, security findings at or above the severity bar are reported, the changelog names the right next version, and the findings point at the right files.

Code lives in `part2/src/review/evals.py`, `part2/evals/tf-module-review.json`, and `part2/tests/test_evals.py`.

## LangSmith objects

LangSmith stores three things. The graph stays in this repo.

| Object | What it is | Where it lives |
| --- | --- | --- |
| Tracing project | One tree per live run of `python -m review` | `LANGSMITH_PROJECT=terraform-module-review` |
| Dataset | Inputs plus the answers we expect | Dataset name `tf-module-review`, sourced from `part2/evals/tf-module-review.json` |
| Experiment | One full pass of the dataset, with a score on every row | Created by `evaluate()`. Each pass is its own project, named `tf-module-review-…` |

A live review and an evaluation do not land in the same project. Live runs go to `terraform-module-review`. `evaluate()` creates a new experiment project each time. `print_performance` reads that experiment, not the tracing project. Opening only the tracing project shows demos and hides the scores.

LangChain and LangGraph emit traces when the three variables below are set. The graph is not wrapped. The only hand-written span is `@traceable` on the live GitHub compare in `part2/src/review/reader.py`, and it exists to redact `GH_TOKEN` before headers are stored. Fixture evals do not hit that path.

## Setup

In `part2/.env` (names match `part2/.env.example`):

```bash
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=terraform-module-review
MODEL=openai:gpt-4.1-mini
```

`MODEL` is required. `run_evaluation` raises when it is blank. A free account is at [smith.langchain.com](https://smith.langchain.com/).

## What already runs

`run_evaluation` in `part2/src/review/evals.py`:

1. Loads `part2/evals/tf-module-review.json`.
2. Upserts the LangSmith dataset `tf-module-review` and tags it with the Agent value in `LANGSMITH_PROJECT`. That tag is what makes the dataset show up when that agent is selected. Each example id is a UUID derived from `inputs.id`, so a resync updates the same row instead of minting a new one. Rows that are no longer in the file are deleted. Old experiments stay, and a later experiment still lines up with an earlier one on the same scenario.
3. Calls `langsmith.evaluate` with the target and five evaluators. `experiment_prefix` is `tf-module-review`. `max_concurrency` is 1.
4. Prints median latency and median token count for `interface`, `security`, `release`, and `recommend`.

The target builds the real graph with the real model and a `FixtureReader`, then `invoke`s it. `gate` calls `interrupt`, so `invoke` returns the state at the pause. That state already has the three specialist results and recommend's draft. The score uses the specialist fields only. Recommend still runs, and its tokens show up in the medians, and its draft is not graded. The evaluation does not resume past the interrupt, so it does not open a pull request.

Run it with:

```bash
uv run --directory part2 pytest tests/test_evals.py::test_langsmith_experiment -s
```

`test_status_fields_are_exact` and `test_finding_files_matches_the_set` score hand-written outputs and never call LangSmith. Those exist so a broken scorer fails in milliseconds. `test_langsmith_experiment` spends the model calls. It fails the pytest run unless every evaluator on every row returns 1.

That strict bar is a product choice. A non-deterministic model will occasionally miss one row and fail the suite. For a demo, the dataset is the release bar. While editing a prompt, compare the new experiment to the previous one and treat a drop on a single row as the signal.

## What "correct" means

Score the publish decision, not the prose. The reference outputs are:

- `interface_status` — `pass` or `fail`. Pass when the generated Terraform docs and `README.md` describe the same variables and outputs (`part2/src/review/prompts/interface.md`).
- `security_status` — `pass` or `fail`. Pass when nothing at or above the named minimum severity remains. The user message names the minimum. `part2/.env` sets `TRIVY_SEVERITY=HIGH` (`part2/src/review/prompts/security.md`).
- `release_status` — `ready` or `not ready`. Ready when the top changelog heading is a real version that matches the diff. `## Unreleased` is not ready (`part2/src/review/prompts/release.md`).
- `suggested_version` — `vX.Y.Z`. Major for a break, minor for a new optional variable or output, patch for anything else. `v1.0.0` when there is no tag and the changelog has no version.
- `finding_files` — the set of filenames across `interface_findings`, `security_findings`, and `release_findings`.

`target()` returns those fields plus the three finding lists. The finding sentence is stored on the run and is not compared. Two runs can both score 1 while one of them describes the wrong problem on the right file.

## Dataset

Each example is one frozen module. Inputs are what the reader needs: `repo`, `ref`, `tags`, `files`, `compares`. `fixture_from_inputs` turns that JSON into a `FixtureReader`, so the agents call the same tools they call in production and receive canned bytes.

`compares` keys are `base...head`. `files` are nested by ref, then path.

The seven rows in `part2/evals/tf-module-review.json`:

| id | What it forces the agent to notice | Expected |
| --- | --- | --- |
| `docs-match` | No diff since `v1.0.0` | `suggested_version` is `none`. Release not ready. Finding on `CHANGELOG.md`. |
| `optional-variable-stale-readme` | New optional variable, README silent, changelog says Unreleased | Interface fail on `README.md`. Minor `v1.1.0`. Release not ready. Finding also on `CHANGELOG.md`. |
| `required-variable-documented` | New required variable, README and changelog updated | Interface pass. Major `v2.0.0`. Release ready. No findings. |
| `output-renamed` | Output renamed, README still lists the old name, changelog ready | Interface fail on `README.md`. Major `v2.0.0`. Release ready. |
| `changelog-misses-fix` | Versioning added, contract unchanged, changelog still on `1.0.0`. Trivy reports LOW only | Interface pass. Patch `v1.0.1`. Release not ready. Security pass. Finding on `CHANGELOG.md`. |
| `no-tags-no-version` | No tags, changelog has no version | Suggest `v1.0.0`. Release not ready. Finding on `CHANGELOG.md`. |
| `public-bucket` | Bucket ACL is `public-read`. Trivy HIGH on `main.tf`, plus a LOW logging finding to drop | Interface pass. Security fail on `main.tf`. Patch `v1.0.1`. Release ready. |

### Still thin

- Recommend's rewritten files are in the trace and are not in `outputs`. Add a row whose expected `README.md` or changelog heading is known, so the score says whether the pull request would actually fix the finding.
- `bump` (`major`, `minor`, `patch`, `none`) is on graph state and is not a reference output. A right version can hide a wrong reason.

### Adding a row

1. Append an object under `examples` in `part2/evals/tf-module-review.json` with `inputs.id`, `inputs.files`, `inputs.tags`, `inputs.compares`, and `outputs`.
2. Re-run `test_langsmith_experiment`. `sync_dataset` upserts the cloud examples by scenario id.
3. Open the new row in the experiment. If the model followed the prompt and the JSON expected the other status, fix the JSON. If the tool output is right and the structured response is wrong, fix the prompt.

## Evaluators

A LangSmith evaluator is `(run, example) -> {"key", "score"}`. `run.outputs` is what `target` returned. `example.outputs` is the reference. The key is the column name in the experiment table.

Already implemented, all score 0 or 1:

| Key | Rule |
| --- | --- |
| `interface_status` | Exact match |
| `security_status` | Exact match |
| `release_status` | Exact match |
| `suggested_version` | Exact match |
| `finding_files` | Set equality of filenames. Order does not matter. An extra or missing file scores 0. |

`_exact` and `finding_files` are plain functions in `part2/src/review/evals.py`. They are passed in the `evaluators` list to `evaluate`.

`decisions_passed` is a summary evaluator over the whole experiment. Its score is the fraction of rows where all five keys are 1. The comment is the count, such as `4 of 7`.

`finding_groundedness` is an LLM-as-judge. It reads the diff, the files at the candidate ref, and the finding sentences, and returns 0 or 1 for "the sentences describe that evidence." The comment is the reason. It is a column on the experiment and is not part of `decisions_passed`. The prompt is `part2/src/review/prompts/groundedness.md`.

### Next metrics

Add these in the same style. Keep code checks on fields that have a known answer. Use a judge only for sentences.

- **bump** — exact match on `major` / `minor` / `patch` / `none`. Return it from `target` and add it to each example's outputs.
- **tool trajectory** — score 1 when interface called `terraform_docs` once, security called `trivy_config` once, and release called `get_last_release_tag` then `get_diff_since_last_release`. Read this off the child runs. A model that guesses the changelog without the diff should fail even when the version matches. On `docs-match`, release has no model call: the graph sees `no changes` and returns the current tag itself. That row's trajectory is "tools not called, and that is correct."
- **changelog heading** — the proposed `CHANGELOG.md` starts with `##` plus `suggested_version`. This scores recommend, which is currently unscored. `target` would also return `proposed_files`.

## Performance metrics

LangSmith records start time, end time, token counts, and cost on every run. `print_performance` lists the runs in the experiment, keeps the four agent names, drops nested duplicates of those names, and prints the median latency, the median token count, and the median cost. Tokens and cost are summed from leaf runs so a parent span that already includes its children is not counted twice. Cost is LangSmith's price for the model. Tool runs have none.

Interface, security, and release run in parallel, then recommend waits for all three. A slow security tool shows up as security latency. A recommend that re-invokes because a file was missing shows up as recommend tokens. The wall clock of one example is about `max(interface, security, release) + recommend`.

Use the medians as a budget. When a prompt change holds the pass rate flat and recommend's median tokens jump, the prompt got more expensive without getting more correct.

Printed line shape:

```text
interface median_latency_s=1.20 median_tokens=800 median_cost=0.000300
security median_latency_s=1.40 median_tokens=900 median_cost=0.000350
release median_latency_s=1.10 median_tokens=700 median_cost=0.000280
recommend median_latency_s=2.00 median_tokens=1500 median_cost=0.001000
```

## How to read a trace

In the UI: Datasets → `tf-module-review` → the latest experiment. Each row is one example. A cell under a key is that evaluator's score. Click a row with a 0 and open the trace.

```text
module_review
├── check
├── interface
│     └── terraform_docs
│     └── chat model → structured status + findings
├── security
│     └── trivy_config
│     └── chat model
├── release
│     └── get_last_release_tag
│     └── get_diff_since_last_release
│     └── chat model → version, bump, findings
├── recommend
│     └── read_first
│     └── read_file  (once per file in the apply list)
│     └── chat model → suggestions, proposed files, PR title and body
└── gate   (interrupt, waiting for yes/no)
```

`check` has no model. On `docs-match`, release also has no model: `release()` in `part2/src/review/graph.py` sees `no changes` in the compare payload and returns the current tag. A missing chat span there is that short-circuit.

When a score is 0, read in this order:

1. The tool output. If `terraform_docs` or the diff text is wrong, the model is not the problem. Fix the fixture or the tool.
2. The model's structured response. This is what the agent decided.
3. The graph's write to state. `_status` forces `fail` or `not ready` whenever the findings list is non-empty, and it rewrites a bad status string. A model can return `pass` with a finding and the state will still be `fail`. Check which layer the dataset meant to grade.
4. Recommend's second invoke. If files were dropped, the node calls the agent again. Two chat spans under recommend usually mean the first draft omitted an apply-list file.

The same tree appears for `uv run --directory part2 python -m review`, in the tracing project. Live runs use `GithubReader`, so `github_compare` is there with the token redacted. The gate stays open until yes or no. After the answer, the resumed run continues in the same thread.

## Using a failure to change the agent

Change one cause, then run the experiment again.

**The reference is wrong.** The trace shows the model followed the prompt, and the JSON expected the other status. Edit `part2/evals/tf-module-review.json`. The next `sync_dataset` updates that example in place. Do this when the rubric changed.

**The prompt is wrong.** The tool output is right and the structured response is wrong. Edit one file under `part2/src/review/prompts/`. Open the comparison between the two experiments. LangSmith lines the rows up by example. The previously failing row should flip to 1, and the previously passing rows should stay 1. A prompt that fixes `output-renamed` and breaks `docs-match` shows up on one screen.

**The graph rewrote a good answer.** The structured response matches the dataset and the state does not. Look at `_status`, `_version`, and the "nothing new to release" short-circuit before editing the prompt.

**The model never looked.** The trajectory is missing a required tool call, or the run hit the recursion limit and the graph substituted "Stopped early." That finding is on `README.md` or `CHANGELOG.md`, so `finding_files` can still pass. A trajectory evaluator catches this.

Three habits:

- After a live review of `straubt1/terraform-aws-object-storage`, if the status is wrong, capture the files and the compare text as a new example with the corrected outputs. The JSON file is the source of truth. The UI can also attach a trace to a dataset, and the next sync would overwrite that unless the JSON has the row.
- On resume, attach the human yes or no with `client.create_feedback` on the run id, key `human_decision`, score 1 for yes. After a few real reviews, that label shows whether people accept a recommendation when release was `not ready`.
- Change one variable per experiment: `MODEL`, or one prompt, or one tool description. The prefix stays `tf-module-review`, so the dataset page lists them in order. The comparison is the evidence for the slide: pass rate, which rows moved, and the median tokens per agent.

Online evaluators are the same functions attached to the tracing project, so a live run is scored without pytest. Attach them after the offline dataset is trustworthy. Until then, a live score has no reference output. Rules that do not need one: a required tool was called, latency under a budget, or a finding filename that exists in the repo.

## Demo

1. Run one live review with tracing on. Open the trace and point at the three parallel branches, the single tool call each prompt requires, recommend, and the interrupt waiting at the gate.
2. Open the `tf-module-review` dataset and one experiment. Show a passing row and a row that a later experiment fixed, with the two columns side by side.
3. Read one failing trace in order: tool output, structured response, state write.
4. Quote the printed medians as the cost of a review, split by agent, and the pass bar as "all five scores are 1 on every scenario."

## Iteration log

| Date | Change | Experiment | What moved |
| --- | --- | --- | --- |
|  |  |  |  |
