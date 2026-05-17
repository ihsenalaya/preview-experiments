#!/usr/bin/env bash
# Chained sequential RQ2 cross_pr re-run for S1-S4 on AKS.
# Each subject runs K∈{2,4,8} × iso∈{T,F} = 6 batches. Sequentially across subjects
# to avoid K=8 spikes (8 simultaneous Previews × 4 subjects = 32 = saturation).
# Compatible with bug_det_all running in parallel (bug_det has resilient wrappers).
set -u

cd /mnt/c/Users/Ihsen/Documents/kubebuilder/experimentation
export KUBECONFIG=$HOME/.kube/config
export PYTHONPATH=$(pwd)

OVERALL_TS=$(date -u +%Y%m%dT%H%M%SZ)
ORCHESTRATOR_LOG="logs/cross_pr-chained-${OVERALL_TS}.log"

{
  echo "[$(date -u +%T)] Cross-PR chained re-run starting (S1 → S2 → S3 → S4)"
  for sub in s1-flask-catalog s2-listmonk s3-healthchecks s4-umami; do
    TS=$(date -u +%Y%m%dT%H%M%SZ)
    LOG="logs/cross_pr-${sub}-${TS}.log"
    echo "[$(date -u +%T)] START $sub (log: $LOG)"
    SUBJECT="$sub" EXPERIMENT="cross_pr" python3 -u _run_one_subject.py > "$LOG" 2>&1
    rc=$?
    echo "[$(date -u +%T)] DONE $sub (rc=$rc)"
    if [ "$rc" != "0" ]; then
      echo "[$(date -u +%T)] non-zero exit; continuing to next subject anyway"
    fi
    sleep 5
  done
  echo "[$(date -u +%T)] Cross-PR chained re-run finished."
} >> "$ORCHESTRATOR_LOG" 2>&1
