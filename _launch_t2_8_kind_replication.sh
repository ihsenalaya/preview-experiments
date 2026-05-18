#!/usr/bin/env bash
# T2.8 — Kind cross-cluster replication launcher (PREPARED but not executed yet;
# run manually post-pipeline). Replicates the RQ1 + RQ3 findings on S1+S2+S3 with
# N=20 per condition on a LOCAL Kind cluster, to demonstrate cluster-independence
# (E1 mitigation).
#
# Prerequisites checked:
#   - kind binary in PATH
#   - docker daemon reachable
#   - kubectl context can be switched (we restore AKS context on exit)
#
# Output: results/kind/<subject>/{flakiness,performance}_*.csv
# ETA: ~4h on a 16 GiB / 8 vCPU workstation.
set -u
ROOT="/mnt/c/Users/Ihsen/Documents/kubebuilder/experimentation"
LOG="$ROOT/logs/t2-8-kind-replication-$(date -u +%Y%m%dT%H%M%SZ).log"
exec >>"$LOG" 2>&1
cd "$ROOT"

trap '
  echo "[$(date -u +%FT%TZ)] cleanup: restoring AKS context"
  kubectl config use-context "$AKS_CTX" 2>/dev/null || true
  if [ "${KEEP_KIND:-0}" != "1" ]; then
    echo "[$(date -u +%FT%TZ)] cleanup: deleting Kind cluster (set KEEP_KIND=1 to preserve)"
    kind delete cluster --name preview-repro 2>/dev/null || true
  fi
' EXIT

echo "[$(date -u +%FT%TZ)] === T2.8 Kind replication launcher START ==="

# Preflight
for bin in kind docker kubectl helm python3; do
  command -v "$bin" >/dev/null || { echo "[fatal] missing $bin in PATH"; exit 1; }
done
AKS_CTX=$(kubectl config current-context 2>/dev/null || echo "")
echo "[$(date -u +%FT%TZ)] AKS context preserved: $AKS_CTX"

# Create Kind cluster
echo "[$(date -u +%FT%TZ)] creating Kind cluster (config: repro/kind-config.yaml)"
kind create cluster --config repro/kind-config.yaml || exit 1
kubectl config use-context kind-preview-repro

# Install operator (assumes preview-operator chart in sibling repo)
# OP_CHART can be overridden via env var (e.g. OP_CHART=$HOME/preview-operator/...
# on the VM where the path differs from the PC's WSL mount).
OP_CHART="${OP_CHART:-/mnt/c/Users/Ihsen/Documents/kubebuilder/preview/preview-operator/charts/preview-operator}"
helm install preview-operator "$OP_CHART" \
  --set image.tag=v1.0.45 \
  --create-namespace --namespace preview-operator-system \
  --wait --timeout 5m || { echo "[fatal] operator install failed"; exit 1; }

# Wait for operator ready
for i in $(seq 1 30); do
  READY=$(kubectl -n preview-operator-system get deploy preview-operator -o jsonpath='{.status.availableReplicas}' 2>/dev/null)
  [ "$READY" = "1" ] && break
  sleep 10
done

# Run RQ1 + RQ3 on S1, S2, S3 with N=20 (small batch for replication, not full N=60)
for SUBJECT in s1-flask-catalog s2-listmonk s3-healthchecks; do
  for EXP in performance flakiness; do
    echo "[$(date -u +%FT%TZ)] === Kind/$SUBJECT/$EXP start ==="
    TS=$(date -u +%Y%m%dT%H%M%SZ)
    SUBJECT="$SUBJECT" EXPERIMENT="$EXP" \
      EXP_EXPERIMENTS_FLAKINESS_N_RUNS=20 \
      EXP_EXPERIMENTS_PERFORMANCE_N_RUNS=20 \
      python3 -u _run_one_subject.py \
        > "logs/t2-8-kind-${SUBJECT}-${EXP}-${TS}.log" 2>&1
    echo "[$(date -u +%FT%TZ)] === Kind/$SUBJECT/$EXP done rc=$? ==="
  done
done

# Move generated CSVs to results/kind/ (separate namespace from AKS results)
mkdir -p results/kind
for sub in s1-flask-catalog s2-listmonk s3-healthchecks; do
  mkdir -p "results/kind/$sub"
  # The runner writes to results/$sub/ by default; we move the *just-generated* files
  # by matching the t2-8 timestamp window — pragmatic, not perfect.
  find "results/$sub" -name "*.csv" -newer /tmp/.t2_8_marker -exec mv {} "results/kind/$sub/" \; 2>/dev/null
done

# Consolidate Kind results separately
python3 scripts/consolidate_results.py --results-dir results/kind \
  --frozen-dir results/kind/frozen 2>&1 | tail -10 || true

echo "[$(date -u +%FT%TZ)] === T2.8 Kind replication launcher DONE ==="
