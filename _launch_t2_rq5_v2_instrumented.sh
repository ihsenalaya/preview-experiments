#!/usr/bin/env bash
# C — PHASE 8 v2 RQ5 instrumented re-run.
# Adds 3 metrics: duplicate_job_count, lost_status_count, final_state_consistent.
#
# CAUTION: this launcher TUE l'opérateur preview-operator multiple times.
# DO NOT run while another launcher is mid-experiment on the same cluster
# (would crash 22939/80162 mid-run). Safe windows :
#   - after launcher 80162 (S5 baseline) exit (~21h Paris lundi)
#   - in parallel with T2.9 (24h time-series, OK because T2.9 doesn't kill)
#   - NOT in parallel with T2.8 (Kind LOCAL is unrelated, OK)
#
# Default: re-run on s1-flask-catalog (smallest, ~1h cluster time, gives the
# augmented schema reference). User can pass SUBJECT arg to switch.
set -u
ROOT="/mnt/c/Users/Ihsen/Documents/kubebuilder/experimentation"
SUBJECT="${1:-s1-flask-catalog}"
LOG="$ROOT/logs/t2-rq5-v2-${SUBJECT}-$(date -u +%Y%m%dT%H%M%SZ).log"
exec >>"$LOG" 2>&1
cd "$ROOT"

echo "[$(date -u +%FT%TZ)] === T2 PHASE 8 v2 RQ5 instrumented launcher START (SUBJECT=$SUBJECT) ==="

# Safety: refuse to start if any other harness Python runner is alive (besides watchers)
ACTIVE=$(ps -ef | grep -E "_run_one_subject|exp_(flakiness|cross_pr|performance|bug_detection)/run" | grep -v grep | wc -l)
if [ "$ACTIVE" -gt 0 ]; then
  echo "[$(date -u +%FT%TZ)] ABORT: $ACTIVE other harness runner(s) alive — would crash on operator kill"
  ps -ef | grep -E "_run_one_subject|exp_(flakiness|cross_pr|performance|bug_detection)/run" | grep -v grep | head
  exit 1
fi

SUBJECT="$SUBJECT" EXPERIMENT=idempotence \
  python3 -u exp_idempotence/run_v2.py
RC=$?

echo "[$(date -u +%FT%TZ)] === T2 PHASE 8 v2 RQ5 done rc=$RC ==="
