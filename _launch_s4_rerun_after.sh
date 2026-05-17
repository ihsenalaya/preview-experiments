#!/usr/bin/env bash
# After PID 950821 (S3+S4+S5 idemp launcher) finishes:
#  1. Verify config.yaml was restored with image :v2.15.1-fix2
#  2. Re-run S4 idempotence  (expect 18/18 Succeeded with fixed tests)
#  3. Re-run S4 flakiness    (RQ1: expect iso=True 0% fail, iso=False 100% fail)
#  4. Re-run S4 cross_pr K=8 (RQ2: same Δ=-100pp pattern as other subjects)
#
# Sequential: each waits for the previous. Restores nothing; config already correct.
set -u
ROOT="/mnt/c/Users/Ihsen/Documents/kubebuilder/experimentation"
WAIT_PID="${1:-950821}"
LOG="$ROOT/logs/s4-rerun-launcher.log"
exec >>"$LOG" 2>&1
cd "$ROOT"

echo "[$(date -u +%FT%TZ)] S4 rerun launcher armed; watching PID=$WAIT_PID"

# 1. Wait for current idempotence chain to exit
while kill -0 "$WAIT_PID" 2>/dev/null; do
  sleep 60
done
echo "[$(date -u +%FT%TZ)] PID $WAIT_PID exited; cooldown 60s + verifications"
sleep 60

# 2. Verify config.yaml has the new image
IMG=$(grep "s4-umami:" config.yaml | awk '{print $2}')
if [ "$IMG" != "ghcr.io/ihsenalaya/s4-umami-adapter:v2.15.1-fix2" ]; then
  echo "[$(date -u +%FT%TZ)] WARN: config.yaml has $IMG, patching to :v2.15.1-fix2"
  sed -i 's|s4-umami: ghcr.io/ihsenalaya/s4-umami-adapter:v2.15.1-fix$|s4-umami: ghcr.io/ihsenalaya/s4-umami-adapter:v2.15.1-fix2|' config.yaml
  IMG=$(grep "s4-umami:" config.yaml | awk '{print $2}')
fi
echo "[$(date -u +%FT%TZ)] using S4 image: $IMG"

# 3. Cleanup any orphan Failed previews
FAILED=$(kubectl get previews -A --no-headers 2>/dev/null | awk '$3 == "Failed" {print $2}')
for p in $FAILED; do
  echo "[$(date -u +%FT%TZ)] cleaning Failed preview $p"
  kubectl delete preview "$p" --wait=false 2>&1 | head -1
done
sleep 30

# 4. S4 idempotence (with fixed image, expect 18/18 Succeeded)
TS=$(date -u +%Y%m%dT%H%M%SZ)
echo "[$(date -u +%FT%TZ)] === S4 idempotence rerun ==="
SUBJECT=s4-umami EXPERIMENT=idempotence python3 -u _run_one_subject.py \
  > "$ROOT/logs/s4-rerun-idemp-${TS}.log" 2>&1
RC=$?
echo "[$(date -u +%FT%TZ)] S4 idempotence rerun rc=$RC"

# 5. S4 flakiness (RQ1)
TS=$(date -u +%Y%m%dT%H%M%SZ)
echo "[$(date -u +%FT%TZ)] === S4 flakiness rerun (RQ1) ==="
SUBJECT=s4-umami EXPERIMENT=flakiness python3 -u _run_one_subject.py \
  > "$ROOT/logs/s4-rerun-flak-${TS}.log" 2>&1
RC=$?
echo "[$(date -u +%FT%TZ)] S4 flakiness rerun rc=$RC"

# 6. S4 cross_pr K=8 (RQ2)
TS=$(date -u +%Y%m%dT%H%M%SZ)
echo "[$(date -u +%FT%TZ)] === S4 cross_pr K=8 rerun (RQ2) ==="
SUBJECT=s4-umami EXPERIMENT=cross_pr python3 -u _run_one_subject.py \
  > "$ROOT/logs/s4-rerun-crosspr-${TS}.log" 2>&1
RC=$?
echo "[$(date -u +%FT%TZ)] S4 cross_pr rerun rc=$RC"

echo "[$(date -u +%FT%TZ)] === S4 rerun chain complete ==="
