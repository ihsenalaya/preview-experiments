#!/usr/bin/env bash
# Bootstrap a Kind cluster and install all required components.
# Reads config from ../config.yaml via yq. Idempotent.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG="$ROOT/config.yaml"

CLUSTER_TYPE=$(yq '.cluster.type' "$CONFIG")
CLUSTER_NAME=$(yq '.cluster.name' "$CONFIG")
OPERATOR_NS=$(yq '.operator.namespace' "$CONFIG")
HELM_CHART=$(yq '.operator.helm_chart' "$CONFIG")
HELM_RELEASE=$(yq '.operator.helm_release' "$CONFIG")

echo "==> Cluster type: $CLUSTER_TYPE / name: $CLUSTER_NAME"

if [ "$CLUSTER_TYPE" = "kind" ]; then
  if ! kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    echo "==> Creating Kind cluster..."
    kind create cluster --config "$SCRIPT_DIR/kind-config.yaml" --name "$CLUSTER_NAME"
  else
    echo "==> Kind cluster '$CLUSTER_NAME' already exists, skipping."
  fi
  kind get kubeconfig --name "$CLUSTER_NAME" > /tmp/kubeconfig-exp.yaml
  export KUBECONFIG=/tmp/kubeconfig-exp.yaml
fi

echo "==> Installing ingress-nginx..."
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.1/deploy/static/provider/kind/deploy.yaml
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=120s

echo "==> Installing metrics-server (for kubectl top)..."
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl patch deployment metrics-server -n kube-system --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'

echo "==> Building operator image..."
cd "$ROOT/../preview-operator"
docker build -t preview-operator:dev .
kind load docker-image preview-operator:dev --name "$CLUSTER_NAME"

echo "==> Building app image..."
cd "$ROOT/../preview/idp-preview"
docker build -t idp-preview:dev .
kind load docker-image idp-preview:dev --name "$CLUSTER_NAME"

echo "==> Installing preview-operator via Helm..."
helm upgrade --install "$HELM_RELEASE" "$HELM_CHART" \
  --namespace "$OPERATOR_NS" \
  --create-namespace \
  --set image.tag=dev \
  --set image.pullPolicy=IfNotPresent \
  --wait --timeout 120s

echo "==> Cluster ready."
