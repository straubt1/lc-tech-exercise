#!/usr/bin/env bash
set -euo pipefail

MINISTACK_PORT="${MINISTACK_PORT:-4566}"
HEALTH_URL="http://127.0.0.1:${MINISTACK_PORT}/_ministack/health"
MAX_WAIT="${MINISTACK_STARTUP_TIMEOUT:-60}"

log() {
  echo "[start-ministack] $*"
}

wait_for_url() {
  local elapsed=0

  while [ "$elapsed" -lt "$MAX_WAIT" ]; do
    if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
      log "MiniStack ready (${elapsed}s)"
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  log "ERROR: MiniStack not ready after ${MAX_WAIT}s (${HEALTH_URL})"
  if [ -f /tmp/ministack.log ]; then
    tail -n 50 /tmp/ministack.log >&2 || true
  fi
  return 1
}

if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
  log "MiniStack already running"
  exit 0
fi

log "Starting MiniStack on :${MINISTACK_PORT}"
export GATEWAY_PORT="${MINISTACK_PORT}"
ministack >/tmp/ministack.log 2>&1 &
echo $! >/tmp/ministack.pid

wait_for_url

log "MiniStack: ${HEALTH_URL}"
