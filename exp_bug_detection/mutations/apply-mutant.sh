#!/usr/bin/env bash
# Apply one mutmut mutant to the app source, rebuild the image, and push to kind.
# Usage: ./apply-mutant.sh <mutant_id> <image_tag> [cluster_name]
set -euo pipefail

MUTANT_ID="${1:?Usage: apply-mutant.sh <mutant_id> <image_tag> [cluster_name]}"
IMAGE_TAG="${2:?}"
CLUSTER="${3:-preview-exp}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_DIR="$ROOT/../preview/idp-preview"

cd "$APP_DIR"

echo "==> Applying mutant $MUTANT_ID..."
mutmut apply "$MUTANT_ID"

echo "==> Building image idp-preview:$IMAGE_TAG..."
docker build -t "idp-preview:$IMAGE_TAG" .

echo "==> Loading into Kind cluster '$CLUSTER'..."
kind load docker-image "idp-preview:$IMAGE_TAG" --name "$CLUSTER"

echo "==> Reverting mutant $MUTANT_ID (restoring original source)..."
mutmut revert "$MUTANT_ID"

echo "Image idp-preview:$IMAGE_TAG ready with mutant $MUTANT_ID"
