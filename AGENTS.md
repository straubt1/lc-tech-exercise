# Agent notes

## Cursor Cloud specific instructions

MiniStack is started by `.cursor/scripts/start-ministack.sh` before the agent runs. It listens at `http://127.0.0.1:4566`. Health check: `http://127.0.0.1:4566/_ministack/health`.

Point Terraform at it with dummy credentials. Do not call real AWS.

```bash
export AWS_ENDPOINT_URL=http://127.0.0.1:4566
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1
export AWS_EC2_METADATA_DISABLED=true
```

The module under review is the public repo [straubt1/terraform-aws-object-storage](https://github.com/straubt1/terraform-aws-object-storage). The releaser reads it over the GitHub HTTPS API. `GITHUB_REPO` defaults to `straubt1/terraform-aws-object-storage`. **Candidate code is always branch `latest`; `main` is not used.** Previous published versions are git tags named `vX.Y.Z` (tags that start with `v` and match semver). No token is required until the draft-release tool is implemented.

API keys and `GH_TOKEN` come from the Cloud Agents secrets tab. Do not write them into the repo, the Dockerfile, or agent state. Leave `RELEASE_ENABLED` unset unless a person is explicitly creating a draft release. `GH_TOKEN` stays out of prompts, tool arguments, and graph state.

### Run the release agent (`uv`)

The environment image includes `uv`. Install (on environment builds) runs `uv sync --frozen` in `/workspace`, clones the Terraform module, and verifies `uv run python -m release.terraform_module_releaser --help`.

From the repo root:

```bash
cd /workspace
uv run python -m release.terraform_module_releaser
```

Optional: `--thread-id` to reuse a checkpoint.

**Secrets required for a traced model run** (Cloud Agents → Secrets; names match `.env.example`):

- `MODEL` — provider:model (for example `openai:gpt-4.1-mini`). The stub builds agents and does not call the model, so a stub run can leave this empty.
- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` matching the provider in `MODEL`
- `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, and `LANGSMITH_PROJECT` for LangSmith cloud. The endpoint is `https://api.smith.langchain.com`.

The CLI stops at the human gate on stdin (`approve` / `reject`). The stub does not create a draft release.

**Tests:** `uv run pytest`
