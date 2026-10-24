#!/usr/bin/env bash
# Export present/index.html to a PDF, one slide per page.
# Usage: ./scripts/export-pdf.sh [output.pdf]
# Default output is deliverables/presentation.pdf.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRESENT="$ROOT/present"
OUT="${1:-"$ROOT/deliverables/presentation.pdf"}"

if [[ "$OUT" != /* ]]; then
  OUT="$(pwd)/$OUT"
fi
mkdir -p "$(dirname "$OUT")"

PORT="$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$PRESENT" >/dev/null 2>&1 &
SERVER_PID=$!

ready=0
for _ in $(seq 1 50); do
  if curl -fsS -o /dev/null "http://127.0.0.1:${PORT}/" 2>/dev/null; then
    ready=1
    break
  fi
  sleep 0.1
done
if [[ "$ready" -ne 1 ]]; then
  echo "Presentation server did not start on port ${PORT}." >&2
  exit 1
fi

CHROME=""
for candidate in \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "/Applications/Chromium.app/Contents/MacOS/Chromium" \
  "${CHROME_PATH:-}" \
  "$(command -v google-chrome 2>/dev/null || true)" \
  "$(command -v chromium 2>/dev/null || true)" \
  "$(command -v chromium-browser 2>/dev/null || true)"
do
  if [[ -n "$candidate" && -x "$candidate" ]]; then
    CHROME="$candidate"
    break
  fi
done

if [[ -n "$CHROME" ]]; then
  export PUPPETEER_SKIP_DOWNLOAD=true
fi

args=(
  reveal
  --size 1280x720
  --pause 1000
  --load-pause 1500
  --pdf-title "Presentation"
)
if [[ -n "$CHROME" ]]; then
  args+=(--chrome-path "$CHROME")
fi

npx --yes decktape@3.17.0 "${args[@]}" "http://127.0.0.1:${PORT}/" "$OUT"
echo "Wrote ${OUT}"
