# Module review

The flow is drawn in [module-review-v4.excalidraw](module-review-v4.excalidraw).

`check` confirms the repo and ref. Interface, security, and release then run in parallel. Recommend applies their findings to at most 10 files and offers a pull request. The gate asks for yes or no, and opens the pull request only on yes.

The graph state is one `State` dict. A step writes only the keys listed under **Writes**. Keys it does not write stay as they were. `repo` and `ref` are set before the graph starts. `GH_TOKEN` is read from the environment inside `open_pull_request` and is never written to state.

| Key | Set by | Meaning |
| --- | --- | --- |
| `repo` | caller | `owner/name` |
| `ref` | caller | Candidate branch, normally `latest` |
| `error` | check | Why the ref could not be verified. Empty when the run continues |
| `interface_status` | interface | `pass` or `fail` |
| `interface_findings` | interface | `{filename, finding}` list |
| `security_status` | security | `pass` or `fail` |
| `security_findings` | security | `{filename, finding}` list |
| `release_status` | release | `ready` or `not ready` |
| `release_findings` | release | `{filename, finding}` list |
| `current_version` | release | Latest published tag. Empty when the repo has no tag |
| `suggested_version` | release | `vX.Y.Z`, or `none` when `bump` is `none` |
| `bump` | release | `major`, `minor`, `patch`, or `none` |
| `suggestions` | recommend | Report shown at the gate |
| `proposed_files` | recommend | `{filename, content}` list to commit |
| `pr_title` | recommend | Pull request title |
| `pr_body` | recommend | Pull request body |
| `decision` | gate | `yes` or `no` |
| `pr_url` | gate | URL returned by GitHub. Empty when no pull request is opened |

A finding is `filename` plus `finding`. A proposed file is `filename` plus the full new `content`.

## check

Confirms the candidate ref exists. This step has no model and no prompt.

| | |
| --- | --- |
| Prompt | none |
| Tools | none |
| Required inputs | `repo`, `ref` |

**Reads:** `repo`, `ref`.

**Writes:** `error` when `reader.check` returns a message. Writes nothing when the ref exists, and the run continues to interface, security, and release. An error ends the run.

## interface

Compares generated Terraform docs with `README.md`. The tool does not change files.

| | |
| --- | --- |
| Prompt | `part2/src/review/prompts/interface.md` |
| Tools | `terraform_docs(ref)` |
| Required inputs | `repo`, `ref` |
| Returns | `status` (`pass` or `fail`), `findings` |

`terraform_docs` checks out `ref`, runs `terraform-docs markdown table` in memory, and returns that markdown beside the current `README.md`.

**Reads:** `repo`, `ref`. The user message is built from those two. The tool reads `README.md` from the reader, not from graph state.

**Writes:** `interface_status`, `interface_findings`.

Any finding forces `fail`. A pass has status `pass` and an empty findings list. If the agent stops early, status is `fail` and the finding is on `README.md`.

## security

Runs Trivy on the module and keeps findings at or above a severity the model chooses. The default is HIGH, which keeps HIGH and CRITICAL. Nothing in code enforces that cutoff.

| | |
| --- | --- |
| Prompt | `part2/src/review/prompts/security.md` |
| Tools | `trivy_config(ref)` |
| Required inputs | `repo`, `ref` |
| Returns | `status` (`pass` or `fail`), `findings` |

`trivy_config` checks out `ref` and runs `trivy config`. It returns the full JSON report. It does not filter by severity and it does not change files.

**Reads:** `repo`, `ref`.

**Writes:** `security_status`, `security_findings`.

Findings in one file can be a single finding. Findings on the same line with the same fix are one finding. Any finding that remains forces `fail`. A pass has status `pass` and an empty findings list. A tool error is a `fail` with that error as the finding. If the agent stops early, status is `fail` and the filename is `module`.

## release

Decides whether `CHANGELOG.md` is ready and recommends the next version. The node loads the latest release tag and the diff before the model runs. Those two values are held for the tools. They are not graph state.

| | |
| --- | --- |
| Prompt | `part2/src/review/prompts/release.md` |
| Tools | `get_last_release_tag()`, `get_diff_since_last_release()` |
| Required inputs | `repo`, `ref` |
| Returns | `status` (`ready` or `not ready`), `suggested_version`, `bump` (`major`, `minor`, `patch`, or `none`), `findings` |

`get_last_release_tag` returns the newest tag loaded for this run, or empty when the repo has no release tag. `get_diff_since_last_release` returns the compare from that tag to `ref`, or `No prior release.` when there is no tag.

**Reads:** `repo`, `ref`. The tools then read the tag list and the diff the node just loaded. They do not read other state keys.

**Writes:** `release_status`, `release_findings`, `current_version`, `suggested_version`, `bump`.

When the diff says there are no changes, the model is not called. Status is `not ready`, `current_version` is the current tag, `suggested_version` is `none`, `bump` is `none`, and the finding on `CHANGELOG.md` says there is nothing new to release. A model reply with `bump` `none` is stored the same way. A tag lookup error is also `not ready`, with that error as the finding and an empty version and bump. The other two agents still run.

Any finding forces `not ready`. A version that is plain semver is stored with a leading `v`. If the agent stops early, status is `not ready` and the finding is on `CHANGELOG.md`.

## recommend

Turns the three reports into file edits and pull request text. It runs only after interface, security, and release have written their keys.

| | |
| --- | --- |
| Prompt | `part2/src/review/prompts/recommend.md` |
| Tools | `read_pr_template(paths, ref)`, `read_file(path, ref)` |
| Required inputs | `repo`, `ref`, and the six status and findings keys, `suggested_version`, `bump` |
| Returns | `suggestions`, `pr_title`, `pr_body`, `proposed_files` |

The node builds one apply list before the model runs. Filenames come from interface findings, then security findings, then release findings. A filename is kept once. A finding that says there is nothing new to release does not add its file. The first 10 names are the apply list. The rest are skipped.

`read_pr_template` takes the template paths in order and returns the first file that exists, or empty. `read_file` reads one apply-list file. Any other path returns `not in this run`.

**Reads:** `repo`, `ref`, `interface_status`, `interface_findings`, `security_status`, `security_findings`, `release_status`, `release_findings`, `current_version`, `suggested_version`, `bump`.

**Writes:** `suggestions`, `proposed_files`, `pr_title`, `pr_body`.

Every apply-list file must come back in `proposed_files` with the full new text. A security finding is an edit to that file. If the first reply leaves a file out, recommend asks once more for only the missing files and merges what comes back. Files still missing after that stay out of `proposed_files`. The gate names them on the pull request.

## gate

Asks whether to open the pull request. This step has no model and no prompt. `open_pull_request` is called by the node after the answer is yes.

| | |
| --- | --- |
| Prompt | none |
| Tools | `open_pull_request` |
| Required inputs | `repo`, `ref`, the three finding lists, `suggested_version`, `suggestions`, `proposed_files`, `pr_title`, `pr_body` |
| Returns | `decision`, `pr_url` |

The question is `Create a pull request with these suggestions? (yes/no)`. The interrupt carries `suggestions`.

**Reads:** `repo`, `ref`, `interface_status`, `security_status`, `release_status`, `interface_findings`, `security_findings`, `release_findings`, `suggested_version`, `suggestions`, `proposed_files`, `pr_title`, `pr_body`. It rebuilds the same apply list recommend used.

**Writes:** `decision`. On yes with at least one file, also `pr_url`. On no, `decision` is `no` and `pr_url` stays empty. On yes with no files left, `decision` is `yes` and no pull request is opened.

Only proposed files whose names are on the apply list are committed. Security findings missing from `pr_body` are appended. Skipped files, and apply-list files that never came back, are appended as `More recommendations were not applied:`. `open_pull_request` commits those files on a `review/<version>-<suffix>` branch and opens the pull request against `ref`. The commit author is Review Agent.
