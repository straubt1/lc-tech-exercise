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
