#!/usr/bin/env bash
# Apply one mutant from fault-catalog.yaml to testapp/app.py, rebuild and push.
# Usage: ./apply-mutant.sh <mutant_id> <image_tag>
set -euo pipefail

MUTANT_ID="${1:?Usage: apply-mutant.sh <mutant_id> <image_tag>}"
IMAGE_TAG="${2:?}"
REGISTRY="${REGISTRY:-ghcr.io/ihsenalaya/idp-preview}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../../testapp" && pwd)"
CATALOG="$SCRIPT_DIR/../fault-catalog.yaml"

echo "==> Applying mutant $MUTANT_ID..."

# Extract the diff for this mutant from the catalog and apply it with patch
python3 - <<PYEOF
import sys, yaml, subprocess, tempfile, os

with open("$CATALOG") as f:
    catalog = yaml.safe_load(f)

mutant = next((m for m in catalog["mutants"] if m["id"] == $MUTANT_ID), None)
if not mutant:
    print(f"ERROR: mutant $MUTANT_ID not found in catalog", file=sys.stderr)
    sys.exit(1)

diff = mutant["diff"]

# Write diff to a temp file and apply with patch
with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as tmp:
    tmp.write(diff)
    tmp_path = tmp.name

try:
    result = subprocess.run(
        ["patch", "-p0", "app.py", tmp_path],
        capture_output=True, text=True, cwd="$APP_DIR"
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)
    print(result.stdout.strip())
finally:
    os.unlink(tmp_path)
PYEOF

echo "==> Building image ${REGISTRY}:${IMAGE_TAG}..."
docker build -t "${REGISTRY}:${IMAGE_TAG}" "$APP_DIR"

echo "==> Pushing to registry..."
docker push "${REGISTRY}:${IMAGE_TAG}"

echo "==> Reverting mutant $MUTANT_ID..."
git -C "$APP_DIR" checkout -- app.py

echo "Image ${REGISTRY}:${IMAGE_TAG} ready with mutant $MUTANT_ID"
