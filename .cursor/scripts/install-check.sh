#!/usr/bin/env bash
set -euo pipefail

echo "==> install-check: verifying toolchain"

terraform version
python3 --version

if ! command -v ministack >/dev/null 2>&1; then
  echo "ministack CLI is not on PATH" >&2
  exit 1
fi

python3 -c "import importlib.metadata as m; print('ministack', m.version('ministack'))"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is not on PATH" >&2
  exit 1
fi
uv --version

echo "==> install-check: syncing Python dependencies with uv"
cd /workspace
uv sync --frozen
uv run python -m release.cli --help >/dev/null

MODULE_DIR="/workspace/terraform-aws-object-storage"
if [[ ! -d "${MODULE_DIR}/.git" ]]; then
  echo "==> install-check: cloning terraform-aws-object-storage"
  git clone https://github.com/straubt1/terraform-aws-object-storage.git "${MODULE_DIR}"
  git -C "${MODULE_DIR}" fetch --tags --depth 1 origin
fi

echo "==> install-check: OK"
