#!/usr/bin/env bash
# Export Excalidraw scenes to PNG.
# A scene used by the design document or the deck writes a PNG beside the
# .excalidraw file and copies that PNG into deliverables/.
# A scene under plans/ is an earlier version. Its PNG stays beside the scene.
#
# Usage: ./scripts/export-diagrams.sh [scene.excalidraw ...]
# With no arguments, exports the scenes the design document and the deck use.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p "$ROOT/deliverables"

if [[ $# -eq 0 ]]; then
  left="part1/langsmith-deployment.excalidraw"
  right="present/assets/langsmith-deployment.excalidraw"
  if [[ -f "$left" && -f "$right" ]] && ! cmp -s "$left" "$right"; then
    echo "part1/langsmith-deployment.excalidraw and present/assets/langsmith-deployment.excalidraw differ." >&2
    echo "Copy the edited scene over the other copy, then run this script again." >&2
    exit 1
  fi
  scenes=(
    "$left"
    "$right"
    "present/assets/module-review-v4.excalidraw"
  )
else
  scenes=("$@")
fi

for scene in "${scenes[@]}"; do
  if [[ "$scene" != /* ]]; then
    scene="$ROOT/$scene"
  fi
  if [[ ! -f "$scene" ]]; then
    echo "No scene at ${scene#"$ROOT/"}" >&2
    exit 1
  fi
  png="${scene%.excalidraw}.png"
  npx --yes @moona3k/excalidraw-export "$scene" -o "$png" --scale 2
  rel="${png#"$ROOT/"}"
  echo "Wrote ${rel}"
  case "$rel" in
    plans/*) ;;
    *)
      cp "$png" "$ROOT/deliverables/$(basename "$png")"
      echo "Wrote deliverables/$(basename "$png")"
      ;;
  esac
done
