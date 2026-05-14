#!/usr/bin/env bash
# Apply one mutmut mutant to testapp/app.py, rebuild and push to ghcr.io.
# Usage: ./apply-mutant.sh <mutant_id> <image_tag>
set -euo pipefail

MUTANT_ID="${1:?Usage: apply-mutant.sh <mutant_id> <image_tag>}"
IMAGE_TAG="${2:?}"
REGISTRY="${REGISTRY:-ghcr.io/ihsenalaya/idp-preview}"

export PATH="$PATH:/home/ihsen/.local/bin"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../../testapp" && pwd)"

cd "$APP_DIR"

echo "==> Applying mutant $MUTANT_ID..."
python3 -m mutmut apply "$MUTANT_ID"

echo "==> Building image ${REGISTRY}:${IMAGE_TAG}..."
docker build -t "${REGISTRY}:${IMAGE_TAG}" .

echo "==> Pushing to registry..."
docker push "${REGISTRY}:${IMAGE_TAG}"

echo "==> Reverting mutant $MUTANT_ID..."
python3 -m mutmut revert "$MUTANT_ID"

echo "Image ${REGISTRY}:${IMAGE_TAG} ready with mutant $MUTANT_ID"
