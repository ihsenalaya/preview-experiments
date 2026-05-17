#!/usr/bin/env bash
# Wait for current idempotence PID to die, validate cluster, then run S1-only idempotence.
# Restores config.yaml at end.
set -u
ROOT="/mnt/c/Users/Ihsen/Documents/kubebuilder/experimentation"
WAIT_PID="${1:-889975}"
LOG="$ROOT/logs/idempotence-s1-launcher.log"
exec >>"$LOG" 2>&1

echo "[$(date -u +%FT%TZ)] Launcher started. Watching PID=$WAIT_PID."

# 1. Wait for current idempotence proc to exit
while kill -0 "$WAIT_PID" 2>/dev/null; do
  sleep 60
done
echo "[$(date -u +%FT%TZ)] PID $WAIT_PID exited; running cluster health check"

# 2. Cluster health check — abort if Failed previews remain
sleep 30  # let operator settle
FAILED=$(kubectl get previews -A --no-headers 2>/dev/null | awk '$3 == "Failed"' | wc -l)
if [ "$FAILED" -gt 0 ]; then
  echo "[$(date -u +%FT%TZ)] ABORT: $FAILED Failed previews present; manual intervention required"
  kubectl get previews -A 2>&1 | head -20
  exit 1
fi

# 3. Validate operator deployment is Available
READY=$(kubectl -n preview-operator-system get deploy preview-operator -o jsonpath='{.status.availableReplicas}' 2>/dev/null)
if [ "$READY" != "1" ]; then
  echo "[$(date -u +%FT%TZ)] ABORT: operator not Available (availableReplicas=$READY)"
  exit 1
fi

# 4. Patch config.yaml: replace enabled list with s1-flask-catalog only
cd "$ROOT"
python3 - <<'PYEOF'
import re
path = "config.yaml"
with open(path) as f:
    content = f.read()
old = """  enabled:
    - s2-listmonk
    - s3-healthchecks
    - s4-umami
    - s5-petclinic"""
new = """  enabled:
    - s1-flask-catalog"""
if old not in content:
    raise SystemExit("ABORT: enabled section not found in expected form; manual check required")
content = content.replace(old, new)
with open(path, "w") as f:
    f.write(content)
print("[ok] config.yaml patched: enabled = [s1-flask-catalog]")
PYEOF
if [ $? -ne 0 ]; then
  echo "[$(date -u +%FT%TZ)] ABORT: config patch failed"
  exit 1
fi

# 5. Launch idempotence S1
TS=$(date -u +%Y%m%dT%H%M%SZ)
RUN_LOG="$ROOT/logs/idempotence-s1-${TS}.log"
echo "[$(date -u +%FT%TZ)] Launching: python3 -u exp_idempotence/run.py  (log: $RUN_LOG)"
python3 -u exp_idempotence/run.py >"$RUN_LOG" 2>&1
RC=$?
echo "[$(date -u +%FT%TZ)] idempotence S1 exited rc=$RC"

# 6. Restore config.yaml from backup
if [ -f "$ROOT/config.yaml.before-s1-idemp" ]; then
  cp "$ROOT/config.yaml.before-s1-idemp" "$ROOT/config.yaml"
  echo "[$(date -u +%FT%TZ)] config.yaml restored from backup"
else
  echo "[$(date -u +%FT%TZ)] WARN: backup config.yaml.before-s1-idemp not found"
fi

echo "[$(date -u +%FT%TZ)] Launcher finished"
