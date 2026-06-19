#!/usr/bin/env bash
#
# One-time, opt-in setup for FindAnything / visual grounding (LocateAnything).
#
# This is the "Enable FindAnything?" step (docs/findanything-design.md §4). It
# is NOT part of the base install: the model is ~6GB and needs a datacenter
# NVIDIA GPU, so ~90% of self-hosters never want it. Running this is the
# explicit opt-in, and accepting the license here is the license consent.
#
# Goal = Ollama-grade UX: when GROUNDING_MIRROR_URL is set, the weights stream
# from the Nurby mirror as a single tarball, no HuggingFace token, no license
# click. Without a mirror it falls back to a token-gated HuggingFace pull
# (set HF_TOKEN). After this runs once, the grounding service is fully offline.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${GROUNDING_WEIGHTS_DIR:-$ROOT/models/grounding}"
MODEL_ID="${GROUNDING_MODEL_ID:-nvidia/LocateAnything-3B}"
REVISION="${GROUNDING_MODEL_REVISION:-main}"
MIRROR="${GROUNDING_MIRROR_URL:-}"

mkdir -p "$DEST"

if [ -n "$(ls -A "$DEST" 2>/dev/null || true)" ]; then
  echo "skip  grounding weights already present in $DEST"
  exit 0
fi

cat <<'EOF'
────────────────────────────────────────────────────────────────────────────
FindAnything uses NVIDIA LocateAnything-3B, licensed for non-commercial /
research use (NVIDIA License). By continuing you accept those terms.
See https://huggingface.co/nvidia/LocateAnything-3B for the full license.
────────────────────────────────────────────────────────────────────────────
EOF

if [ -n "$MIRROR" ]; then
  TARNAME="${MODEL_ID//\//_}-${REVISION}.tar.gz"
  URL="${MIRROR%/}/${TARNAME}"
  echo "fetch grounding weights from mirror: $URL"
  TMP="$(mktemp)"
  curl -fSL --retry 3 -o "$TMP" "$URL"
  tar -xzf "$TMP" -C "$DEST"
  rm -f "$TMP"
else
  : "${HF_TOKEN:?No GROUNDING_MIRROR_URL set and HF_TOKEN is empty. Set one of them.}"
  echo "fetch grounding weights from HuggingFace ($MODEL_ID @ $REVISION)"
  python - "$MODEL_ID" "$REVISION" "$DEST" <<'PY'
import sys
from huggingface_hub import snapshot_download
model_id, revision, dest = sys.argv[1], sys.argv[2], sys.argv[3]
snapshot_download(repo_id=model_id, revision=revision, local_dir=dest)
print("done")
PY
fi

echo "done. grounding weights in $DEST"
du -sh "$DEST" 2>/dev/null || true
