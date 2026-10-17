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

echo "==> install-check: OK"
