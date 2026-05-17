#!/usr/bin/env bash
# Wait for the max-parallel launcher (PID 9601) to finish — then re-run S5 RQ1+RQ2
# with the freshly-built :v3.4.0-fix7 image (e2e_create_pet + e2e_pet_fetch removed).
set -u
ROOT="/mnt/c/Users/Ihsen/Documents/kubebuilder/experimentation"
WAIT_PID="${1:-9601}"
LOG="$ROOT/logs/s5-fix7-after-max-launcher.log"
exec >>"$LOG" 2>&1
cd "$ROOT"

echo "[$(date -u +%FT%TZ)] watching PID=$WAIT_PID (max launcher) for exit"
while kill -0 "$WAIT_PID" 2>/dev/null; do
  sleep 60
done
echo "[$(date -u +%FT%TZ)] max launcher exited; cooldown 60s"
sleep 60

# Cleanup any Failed previews
kubectl get previews -A --no-headers 2>/dev/null | awk '{print $1}' | while read p; do
  PH=$(kubectl get preview "$p" -o jsonpath="{.status.phase}" 2>/dev/null)
  [ "$PH" = "Failed" ] && kubectl delete preview "$p" --wait=false 2>&1 | head -1
done
sleep 30

# Run S5 RQ1 + S5 RQ2 with :v3.4.0-fix7 (already in config.yaml)
TS=$(date -u +%Y%m%dT%H%M%SZ)
echo "[$(date -u +%FT%TZ)] === S5 RQ1 retry (fix7, e2e_create_pet removed) ==="
SUBJECT=s5-petclinic EXPERIMENT=flakiness \
  python3 -u _run_one_subject.py > "logs/s5-fix7-flak-${TS}.log" 2>&1
echo "[$(date -u +%FT%TZ)] S5 RQ1 fix7 rc=$?"

TS=$(date -u +%Y%m%dT%H%M%SZ)
echo "[$(date -u +%FT%TZ)] === S5 RQ2 retry (fix7) ==="
SUBJECT=s5-petclinic EXPERIMENT=cross_pr \
  python3 -u _run_one_subject.py > "logs/s5-fix7-crosspr-${TS}.log" 2>&1
echo "[$(date -u +%FT%TZ)] S5 RQ2 fix7 rc=$?"

# Final re-consolidate + re-build_all
python3 scripts/consolidate_results.py 2>&1 | tail -8
python3 analysis/check_k_consistency.py 2>&1 | tail -5
python3 analysis/build_all.py 2>&1 | tail -10

echo "[$(date -u +%FT%TZ)] === DONE ==="
