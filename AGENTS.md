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

The module under review is [straubt1/terraform-aws-object-storage](https://github.com/straubt1/terraform-aws-object-storage). The install step clones it to `/workspace/terraform-aws-object-storage` when missing. `MODULE_PATH` defaults to that directory. Previous published versions are git tags named `vX.Y.Z` (tags that start with `v` and match semver).

API keys and `GH_TOKEN` come from the Cloud Agents secrets tab. Do not write them into the repo, the Dockerfile, or agent state. Leave `RELEASE_ENABLED` unset unless a person is explicitly publishing a version branch.

### Run the release agent (`uv`)

The environment image includes `uv`. Install (on environment builds) runs `uv sync --frozen` in `/workspace`, clones the Terraform module, and verifies `uv run python -m release.cli --help`.

From the repo root:

```bash
cd /workspace
uv run python -m release.cli
```

Optional: `--module-path` (defaults to `MODULE_PATH` or `/workspace/terraform-aws-object-storage`), `--thread-id` to reuse a checkpoint.

**Secrets required for a full run** (Cloud Agents → Secrets; names match `.env.example`):

- `MODEL` — provider:model for `init_chat_model` (for example `openai:gpt-4.1-mini`)
- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` matching the provider in `MODEL`

Optional: `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` for traces.

The CLI stops at the human gate on stdin (`approve` / `edit` / `reject`). Without API keys the graph fails at the version agent step.

**Tests:** `uv run pytest`
