#!/usr/bin/env bash
# Wait for S4 diag launcher (PID 921800) to die, then run idempotence on
# [s3-healthchecks, s4-umami, s5-petclinic] with the fixed harness
# (resilient get_tests_step + get_phase). Restores config.yaml at end.
set -u
ROOT="/mnt/c/Users/Ihsen/Documents/kubebuilder/experimentation"
WAIT_PID="${1:-921800}"
LOG="$ROOT/logs/idempotence-s3s4s5-launcher.log"
exec >>"$LOG" 2>&1

echo "[$(date -u +%FT%TZ)] Launcher armed. Watching PID=$WAIT_PID (S4 diag)."

# 1. Wait for S4 diag launcher to exit
while kill -0 "$WAIT_PID" 2>/dev/null; do
  sleep 60
done
echo "[$(date -u +%FT%TZ)] PID $WAIT_PID exited; cooldown 60s + cluster health check"
sleep 60

# 2. Cluster health check
FAILED=$(kubectl get previews -A --no-headers 2>/dev/null | awk '$3 == "Failed"' | wc -l)
if [ "$FAILED" -gt 0 ]; then
  echo "[$(date -u +%FT%TZ)] WARN: $FAILED Failed previews present; cleanup before run"
  kubectl get previews -A 2>&1 | head -10
  # Clean up Failed previews to avoid pollution
  kubectl get previews -A --no-headers 2>/dev/null | awk '$3 == "Failed" {print "preview/"$2" -n "$1}' | while read p; do
    kubectl delete $p --wait=false 2>&1 || true
  done
  sleep 30
fi

READY=$(kubectl -n preview-operator-system get deploy preview-operator -o jsonpath='{.status.availableReplicas}' 2>/dev/null)
if [ "$READY" != "1" ]; then
  echo "[$(date -u +%FT%TZ)] ABORT: operator not Available (availableReplicas=$READY)"
  exit 1
fi

# 3. Backup current config (in case)
cp "$ROOT/config.yaml" "$ROOT/config.yaml.before-s3s4s5-idemp"

# 4. Patch config.yaml to enable only S3+S4+S5
cd "$ROOT"
python3 - <<'PYEOF'
import re
path = "config.yaml"
with open(path) as f:
    content = f.read()
# Match the enabled section (any combination)
m = re.search(r"  enabled:\n((?:    - \S+\n)+)", content)
if not m:
    raise SystemExit("ABORT: could not locate enabled section")
new = """  enabled:
    - s3-healthchecks
    - s4-umami
    - s5-petclinic
"""
content = content[:m.start()] + new + content[m.end():]
with open(path, "w") as f:
    f.write(content)
print("[ok] config.yaml patched: enabled = [s3-healthchecks, s4-umami, s5-petclinic]")
PYEOF
if [ $? -ne 0 ]; then
  echo "[$(date -u +%FT%TZ)] ABORT: config patch failed"
  exit 1
fi

# 5. Verify the fixed preview_factory.py is in place
python3 -c "
import inspect
import sys
sys.path.insert(0, 'harness')
import preview_factory
src = inspect.getsource(preview_factory.get_tests_step)
assert 'Resilient' in src or 'check=False' in src, 'FIX NOT PRESENT in get_tests_step'
src = inspect.getsource(preview_factory.get_phase)
assert 'Resilient' in src or 'check=False' in src, 'FIX NOT PRESENT in get_phase'
print('[ok] resilient wrappers verified in preview_factory.py')
"
if [ $? -ne 0 ]; then
  echo "[$(date -u +%FT%TZ)] ABORT: harness fix verification failed"
  cp "$ROOT/config.yaml.before-s3s4s5-idemp" "$ROOT/config.yaml"
  exit 1
fi

# 6. Launch idempotence S3+S4+S5
TS=$(date -u +%Y%m%dT%H%M%SZ)
RUN_LOG="$ROOT/logs/idempotence-s3s4s5-${TS}.log"
echo "[$(date -u +%FT%TZ)] Launching: python3 -u exp_idempotence/run.py  (log: $RUN_LOG)"
python3 -u exp_idempotence/run.py >"$RUN_LOG" 2>&1
RC=$?
echo "[$(date -u +%FT%TZ)] idempotence S3+S4+S5 exited rc=$RC"

# 7. Restore original config
cp "$ROOT/config.yaml.before-s3s4s5-idemp" "$ROOT/config.yaml"
echo "[$(date -u +%FT%TZ)] config.yaml restored"

echo "[$(date -u +%FT%TZ)] Launcher finished"
