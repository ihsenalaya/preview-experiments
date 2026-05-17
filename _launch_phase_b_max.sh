#!/usr/bin/env bash
# Max-parallel launcher post-reboot — PHASE B baseline + S5 fix6 retry + PHASE 2 watch.
#
# Cluster: AKS 3x D4s_v3 (12 vCPU / 48 GiB). 6 parallel experiment procs at peak.
# 5 procs: per-subject baseline (CHECKPOINT_MODE=migration, RQ3 then RQ1)
# 1 proc:  S5 fix6 retry (normal mode, RQ1 then RQ2)
# 1 proc:  PHASE 2 watch (passive assertion outcomes capture)
# After all 7 finish:
#   sequential S5 RQ5 idempotence retry (alone — RQ5 lock)
#   re-consolidate + re-build_all
#
set -u
ROOT="/mnt/c/Users/Ihsen/Documents/kubebuilder/experimentation"
LOG="$ROOT/logs/phase_b_max_launcher.log"
exec >>"$LOG" 2>&1

echo "[$(date -u +%FT%TZ)] === PHASE B MAX launcher started ==="

cd "$ROOT"
mkdir -p logs

# Sanity: cluster + operator 1.0.45
kubectl cluster-info >/dev/null 2>&1 || { echo "ABORT: no cluster"; exit 1; }
OPER_IMG=$(kubectl -n preview-operator-system get deploy preview-operator -o jsonpath='{.spec.template.spec.containers[0].image}')
if [[ "$OPER_IMG" != *"1.0.45"* ]]; then
  echo "ABORT: operator image is $OPER_IMG, expected 1.0.45"; exit 1
fi
echo "[$(date -u +%FT%TZ)] cluster OK, operator=$OPER_IMG"

# ---------------------------------------------------------------------------
# Step 1: launch 7 procs in parallel
# ---------------------------------------------------------------------------

# 5 per-subject baseline procs (CHECKPOINT_MODE=migration)
for SUB in s1-flask-catalog s2-listmonk s3-healthchecks s4-umami s5-petclinic; do
  (
    TS=$(date -u +%Y%m%dT%H%M%SZ)
    echo "[$(date -u +%FT%TZ)] baseline-RQ3 $SUB start"
    CHECKPOINT_MODE=migration SUBJECT="$SUB" EXPERIMENT=performance \
      python3 -u _run_one_subject.py > "logs/baseline-perf-${SUB}-${TS}.log" 2>&1
    echo "[$(date -u +%FT%TZ)] baseline-RQ3 $SUB done rc=$?"

    TS=$(date -u +%Y%m%dT%H%M%SZ)
    echo "[$(date -u +%FT%TZ)] baseline-RQ1 $SUB start"
    CHECKPOINT_MODE=migration SUBJECT="$SUB" EXPERIMENT=flakiness \
      python3 -u _run_one_subject.py > "logs/baseline-flak-${SUB}-${TS}.log" 2>&1
    echo "[$(date -u +%FT%TZ)] baseline-RQ1 $SUB done rc=$?"
  ) &
done

# S5 fix6 retry (NORMAL mode, no CHECKPOINT_MODE) — RQ1 then RQ2
(
  TS=$(date -u +%Y%m%dT%H%M%SZ)
  echo "[$(date -u +%FT%TZ)] S5-retry RQ1 start (fix6, normal mode)"
  SUBJECT=s5-petclinic EXPERIMENT=flakiness \
    python3 -u _run_one_subject.py > "logs/s5-retry-flak-${TS}.log" 2>&1
  echo "[$(date -u +%FT%TZ)] S5-retry RQ1 done rc=$?"

  TS=$(date -u +%Y%m%dT%H%M%SZ)
  echo "[$(date -u +%FT%TZ)] S5-retry RQ2 start (fix6, normal mode)"
  SUBJECT=s5-petclinic EXPERIMENT=cross_pr \
    python3 -u _run_one_subject.py > "logs/s5-retry-crosspr-${TS}.log" 2>&1
  echo "[$(date -u +%FT%TZ)] S5-retry RQ2 done rc=$?"
) &

# PHASE 2 watch (passive — captures assertion outcomes from every preview)
(
  TS=$(date -u +%Y%m%dT%H%M%SZ)
  echo "[$(date -u +%FT%TZ)] PHASE 2 watch start"
  python3 scripts/collect_assertions_from_preview.py watch \
    --out-dir results/ \
    --max-seconds 18000 \
    --poll-every 8 \
    > "logs/assertion-watch-${TS}.log" 2>&1
  echo "[$(date -u +%FT%TZ)] PHASE 2 watch done"
) &

# Wait for ALL parallel jobs
echo "[$(date -u +%FT%TZ)] 7 procs launched, waiting for completion..."
wait
echo "[$(date -u +%FT%TZ)] All parallel jobs finished"

# ---------------------------------------------------------------------------
# Step 2: S5 RQ5 idempotence retry — ALONE (RQ5 lock requirement)
# ---------------------------------------------------------------------------

# Cooldown + cleanup any Failed previews
sleep 60
kubectl get previews -A --no-headers 2>/dev/null | awk '{print $1}' | while read p; do
  PH=$(kubectl get preview "$p" -o jsonpath="{.status.phase}" 2>/dev/null)
  [ "$PH" = "Failed" ] && kubectl delete preview "$p" --wait=false 2>&1 | head -1
done
sleep 30

TS=$(date -u +%Y%m%dT%H%M%SZ)
echo "[$(date -u +%FT%TZ)] S5 RQ5 idempotence retry start (fix6, alone)"
SUBJECT=s5-petclinic EXPERIMENT=idempotence \
  python3 -u _run_one_subject.py > "logs/s5-retry-idemp-${TS}.log" 2>&1
echo "[$(date -u +%FT%TZ)] S5 RQ5 idempotence retry done rc=$?"

# ---------------------------------------------------------------------------
# Step 3: re-consolidate + re-build_all
# ---------------------------------------------------------------------------

echo "[$(date -u +%FT%TZ)] Consolidating new CSVs..."
python3 scripts/consolidate_results.py 2>&1 | tail -10

echo "[$(date -u +%FT%TZ)] Re-checking K-consistency..."
python3 analysis/check_k_consistency.py 2>&1 | tail -10

echo "[$(date -u +%FT%TZ)] Re-generating analyses..."
python3 analysis/build_all.py 2>&1 | tail -15

echo "[$(date -u +%FT%TZ)] === PHASE B MAX launcher DONE ==="
