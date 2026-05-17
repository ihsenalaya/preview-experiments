#!/usr/bin/env bash
# Diagnostic live S4 — capture l'état postgres + logs restore après smoke.
# Vise à discriminer H1 (schéma), H2 (probe restart), H3 (TRUNCATE FK fail).
set -u
ROOT="/mnt/c/Users/Ihsen/Documents/kubebuilder/experimentation"
TS=$(date -u +%Y%m%dT%H%M%SZ)
DIAG_LOG="$ROOT/logs/s4-diag-${TS}.log"
exec >"$DIAG_LOG" 2>&1

echo "[$(date -u +%FT%TZ)] === S4 restore diagnostic — capture multi-stage ==="

NS="s4diag-${TS,,}"  # lowercase
NS="${NS//t/t}"
PREVIEW_NAME="s4diag-${TS,,}"

# 1. Create a fresh S4 preview with isolation enabled
cat <<YAML | kubectl apply -f -
apiVersion: platform.preview.ihsenalaya.io/v1alpha1
kind: Preview
metadata:
  name: ${PREVIEW_NAME}
  namespace: default
spec:
  prNumber: 9999
  app:
    image: ghcr.io/ihsenalaya/idp-preview:exp-20260514-e2efix-2089
  subject:
    image: ghcr.io/ihsenalaya/s4-umami-adapter:v2.15.1-fix
  probe:
    image: ghcr.io/ihsenalaya/harness-probe:cached
  isolationEnabled: true
  size: medium
YAML

echo "[$(date -u +%FT%TZ)] Preview ${PREVIEW_NAME} créé"

# Wait for namespace
for i in {1..60}; do
  NSNAME=$(kubectl get preview "${PREVIEW_NAME}" -n default -o jsonpath='{.status.namespace}' 2>/dev/null)
  [ -n "$NSNAME" ] && break
  sleep 3
done
echo "[$(date -u +%FT%TZ)] Namespace = $NSNAME"

# 2. Wait until the saving step is done (smoke + checkpoint saved)
echo "[$(date -u +%FT%TZ)] === Phase 1 — wait for saving step (smoke done) ==="
for i in {1..120}; do
  STEP=$(kubectl get preview "${PREVIEW_NAME}" -n default -o jsonpath='{.status.lastStep}' 2>/dev/null)
  PHASE=$(kubectl get preview "${PREVIEW_NAME}" -n default -o jsonpath='{.status.phase}' 2>/dev/null)
  echo "  [$(date -u +%T)] phase=$PHASE step=$STEP"
  if [ "$STEP" = "saving" ] || [ "$STEP" = "restore-regression" ] || [ "$STEP" = "regression" ]; then break; fi
  if [ "$PHASE" = "Failed" ]; then echo "PREVIEW FAILED — aborting"; exit 1; fi
  sleep 5
done

# 3. State capture AFTER smoke, BEFORE restore-regression
echo ""
echo "[$(date -u +%FT%TZ)] === Phase 2 — DB state after smoke (run_log should have smoke marker) ==="
POSTGRES_POD=$(kubectl -n "$NSNAME" get pod -l app=postgres -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
echo "Postgres pod: $POSTGRES_POD"
echo ""
echo "--- schemas présents ---"
kubectl -n "$NSNAME" exec "$POSTGRES_POD" -- psql -U "$(kubectl -n "$NSNAME" get secret postgres-credentials -o jsonpath='{.data.POSTGRES_USER}' | base64 -d)" -d "$(kubectl -n "$NSNAME" get secret postgres-credentials -o jsonpath='{.data.POSTGRES_DB}' | base64 -d)" -c "\dn"
echo ""
echo "--- run_log dans quel(s) schéma(s) ? ---"
kubectl -n "$NSNAME" exec "$POSTGRES_POD" -- psql -U "$(kubectl -n "$NSNAME" get secret postgres-credentials -o jsonpath='{.data.POSTGRES_USER}' | base64 -d)" -d "$(kubectl -n "$NSNAME" get secret postgres-credentials -o jsonpath='{.data.POSTGRES_DB}' | base64 -d)" -c "SELECT schemaname, tablename FROM pg_tables WHERE tablename = 'run_log'"
echo ""
echo "--- contenu run_log AVANT restore (devrait avoir smoke marker) ---"
kubectl -n "$NSNAME" exec "$POSTGRES_POD" -- psql -U "$(kubectl -n "$NSNAME" get secret postgres-credentials -o jsonpath='{.data.POSTGRES_USER}' | base64 -d)" -d "$(kubectl -n "$NSNAME" get secret postgres-credentials -o jsonpath='{.data.POSTGRES_DB}' | base64 -d)" -c "SELECT * FROM public.run_log"
echo ""
echo "--- nombre de tables en public schema ---"
kubectl -n "$NSNAME" exec "$POSTGRES_POD" -- psql -U "$(kubectl -n "$NSNAME" get secret postgres-credentials -o jsonpath='{.data.POSTGRES_USER}' | base64 -d)" -d "$(kubectl -n "$NSNAME" get secret postgres-credentials -o jsonpath='{.data.POSTGRES_DB}' | base64 -d)" -c "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"

# 4. Wait for restore-regression to complete
echo ""
echo "[$(date -u +%FT%TZ)] === Phase 3 — wait for restore-regression to finish ==="
for i in {1..60}; do
  STEP=$(kubectl get preview "${PREVIEW_NAME}" -n default -o jsonpath='{.status.lastStep}' 2>/dev/null)
  echo "  [$(date -u +%T)] step=$STEP"
  if [ "$STEP" = "regression" ] || [ "$STEP" = "restore-e2e" ] || [ "$STEP" = "e2e" ] || [ "$STEP" = "complete" ]; then break; fi
  sleep 3
done

# 5. Capture restore-regression job log
echo ""
echo "[$(date -u +%FT%TZ)] === Phase 4 — restore-regression job logs ==="
RESTORE_JOB=$(kubectl -n "$NSNAME" get job -l preview.step=restore-regression -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -z "$RESTORE_JOB" ]; then
  RESTORE_JOB=$(kubectl -n "$NSNAME" get job -o name 2>/dev/null | grep -i restore | head -1)
fi
echo "Restore job: $RESTORE_JOB"
kubectl -n "$NSNAME" logs job/"${RESTORE_JOB#job/}" --tail=200 2>&1

# 6. State capture AFTER restore-regression (run_log SHOULD be empty if isolation worked)
echo ""
echo "[$(date -u +%FT%TZ)] === Phase 5 — DB state AFTER restore-regression ==="
echo "--- contenu run_log APRÈS restore (devrait être VIDE si isolation OK) ---"
kubectl -n "$NSNAME" exec "$POSTGRES_POD" -- psql -U "$(kubectl -n "$NSNAME" get secret postgres-credentials -o jsonpath='{.data.POSTGRES_USER}' | base64 -d)" -d "$(kubectl -n "$NSNAME" get secret postgres-credentials -o jsonpath='{.data.POSTGRES_DB}' | base64 -d)" -c "SELECT * FROM public.run_log"
echo ""
echo "--- count run_log par suite ---"
kubectl -n "$NSNAME" exec "$POSTGRES_POD" -- psql -U "$(kubectl -n "$NSNAME" get secret postgres-credentials -o jsonpath='{.data.POSTGRES_USER}' | base64 -d)" -d "$(kubectl -n "$NSNAME" get secret postgres-credentials -o jsonpath='{.data.POSTGRES_DB}' | base64 -d)" -c "SELECT suite, count(*) FROM public.run_log GROUP BY suite"

# 7. Probe pod restart events
echo ""
echo "[$(date -u +%FT%TZ)] === Phase 6 — probe pod restart history ==="
kubectl -n "$NSNAME" get pod -l app=probe -o yaml 2>/dev/null | grep -E "restartCount|startedAt|reason"
echo ""
echo "--- events namespace (OOMKilled / restarts) ---"
kubectl -n "$NSNAME" get events --sort-by=.lastTimestamp 2>&1 | grep -iE "oom|kill|restart|fail|warn" | tail -20

# 8. Cleanup
echo ""
echo "[$(date -u +%FT%TZ)] === Phase 7 — cleanup ==="
kubectl delete preview "${PREVIEW_NAME}" -n default --wait=false
echo "Preview deletion requested"

echo ""
echo "[$(date -u +%FT%TZ)] === DIAGNOSTIC TERMINÉ ==="
echo "Log file: $DIAG_LOG"
