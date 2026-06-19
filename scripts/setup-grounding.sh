#!/usr/bin/env bash
#
# Optional pre-fetch for FindAnything / visual grounding (LocateAnything-3B).
#
# You usually DON'T need to run this: when you enable FindAnything, the
# grounding service downloads the model itself on first use. nvidia/
# LocateAnything-3B is a public, ungated HuggingFace repo, so there is NO
# token, NO login, and NO license click-through required. This script just
# lets you pre-download the ~6 GB ahead of time (e.g. before going offline).
#
# Air-gapped installs that cannot reach huggingface.co can instead point
# GROUNDING_MIRROR_URL at an internal mirror serving the snapshot tarball.
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

if [ -n "$MIRROR" ]; then
  TARNAME="${MODEL_ID//\//_}-${REVISION}.tar.gz"
  URL="${MIRROR%/}/${TARNAME}"
  echo "fetch grounding weights from mirror: $URL"
  TMP="$(mktemp)"
  curl -fSL --retry 3 -o "$TMP" "$URL"
  tar -xzf "$TMP" -C "$DEST"
  rm -f "$TMP"
else
  echo "fetch grounding weights from HuggingFace ($MODEL_ID @ $REVISION) — no token needed"
  # HF_HUB_ENABLE_HF_TRANSFER speeds up the ~6 GB pull when hf_transfer is installed.
  HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-1}" \
  python - "$MODEL_ID" "$REVISION" "$DEST" <<'PY'
import sys
from huggingface_hub import snapshot_download
model_id, revision, dest = sys.argv[1], sys.argv[2], sys.argv[3]
# token is intentionally omitted: the repo is ungated.
snapshot_download(repo_id=model_id, revision=revision, local_dir=dest)
print("done")
PY
fi

echo "done. grounding weights in $DEST"
du -sh "$DEST" 2>/dev/null || true

cat <<'EOF'

Note: LocateAnything-3B is under the NVIDIA non-commercial research license.
Fine for personal / self-hosted use; review the license for other uses:
https://huggingface.co/nvidia/LocateAnything-3B
EOF
