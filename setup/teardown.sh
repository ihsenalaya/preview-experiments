#!/usr/bin/env bash
# Remove all experiment namespaces and optionally delete the Kind cluster.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG="$ROOT/config.yaml"

CLUSTER_NAME=$(yq '.cluster.name' "$CONFIG")
NS_PREFIX=$(yq '.app.namespace_prefix' "$CONFIG")

echo "==> Deleting experiment namespaces (prefix: $NS_PREFIX)..."
kubectl get namespaces -o name | grep "namespace/${NS_PREFIX}-" | xargs -r kubectl delete

if [ "${1:-}" = "--delete-cluster" ]; then
  echo "==> Deleting Kind cluster '$CLUSTER_NAME'..."
  kind delete cluster --name "$CLUSTER_NAME"
fi

echo "==> Done."
