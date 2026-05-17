#!/usr/bin/env bash
# T2.10 — Sensitivity-K analysis: launch a 2nd INDEPENDENT N=60 batch for S2 baseline
# mode=migration so we can show claim stability across nested subsamples (N=20, 40, 60)
# AND across the two independent N=60 batches (test-retest reliability).
#
# Runs in parallel with the in-flight chain. Cluster load: +1-2 previews at any
# given moment. ETA ~4h, finishes well before S5 baseline launcher (PID 80162)
# starts → no overlap risk.
#
# Output: results/s2-listmonk/flakiness_test_outcomes_<TS>_mode-migration.csv
#         (consolidate_results.py will pick up a *_mode-migration* file with new TS,
#          analysis script T2.10 will discover both batches and run sensitivity curve)
set -u
ROOT="/mnt/c/Users/Ihsen/Documents/kubebuilder/experimentation"
LOG="$ROOT/logs/t2-10-sensitivity-k-s2-$(date -u +%Y%m%dT%H%M%SZ).log"
exec >>"$LOG" 2>&1
cd "$ROOT"

echo "[$(date -u +%FT%TZ)] === T2.10 sensitivity-K launcher START ==="
echo "[$(date -u +%FT%TZ)] config: SUBJECT=s2-listmonk EXPERIMENT=flakiness CHECKPOINT_MODE=migration N=60"
echo "[$(date -u +%FT%TZ)] cluster sanity: previews count"
kubectl get previews -A --no-headers 2>/dev/null | wc -l

CHECKPOINT_MODE=migration \
SUBJECT=s2-listmonk \
EXPERIMENT=flakiness \
  python3 -u _run_one_subject.py
RC=$?

echo "[$(date -u +%FT%TZ)] === T2.10 done rc=$RC ==="
