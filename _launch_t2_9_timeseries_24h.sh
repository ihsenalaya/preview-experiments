#!/usr/bin/env bash
# T2.9 — 24h time-series baseline launcher (PREPARED but not executed yet;
# run manually post-pipeline on AKS). Runs S2 baseline mode=migration in
# small N=6 batches every hour for 24h to characterize cycle-time + flakiness
# drift over time-of-day. Mitigates C3 (time-of-day confounds) and reinforces
# stability of the envelope finding.
#
# Output: results/s2-listmonk/timeseries/flakiness_*.csv (24 batches, each tagged
# with the wall-clock hour). The analysis script T2.9 picks them up by directory.
# ETA: 24h passive (~6 runs × 2 min = 12 min/hour, leaves cluster mostly free
# for any other work in parallel).
set -u
ROOT="/mnt/c/Users/Ihsen/Documents/kubebuilder/experimentation"
LOG="$ROOT/logs/t2-9-timeseries-24h-$(date -u +%Y%m%dT%H%M%SZ).log"
exec >>"$LOG" 2>&1
cd "$ROOT"

OUT_DIR="$ROOT/results/s2-listmonk/timeseries"
mkdir -p "$OUT_DIR"

echo "[$(date -u +%FT%TZ)] === T2.9 24h time-series launcher START ==="

for hour in $(seq 0 23); do
  TS=$(date -u +%Y%m%dT%H%M%SZ)
  echo "[$(date -u +%FT%TZ)] === hour $hour/23, ts=$TS ==="

  # Each batch: 3 iso=True + 3 iso=False = 6 runs ≈ 12 min
  CHECKPOINT_MODE=migration \
  SUBJECT=s2-listmonk \
  EXPERIMENT=flakiness \
  EXP_EXPERIMENTS_FLAKINESS_N_RUNS=3 \
    python3 -u _run_one_subject.py \
    > "logs/t2-9-hour-${hour}-${TS}.log" 2>&1

  # Move just-produced CSV into timeseries/ subfolder with hour tag
  for csv in $(find results/s2-listmonk -maxdepth 1 -name "*_mode-migration.csv" -newer "$OUT_DIR" 2>/dev/null); do
    mv "$csv" "$OUT_DIR/hour${hour}_$(basename $csv)"
  done

  # Sleep until next hour mark (target: batch every 60 min wall-clock)
  next=$(( (hour + 1) * 3600 ))
  start_epoch="${start_epoch:-$(date +%s)}"
  now=$(date +%s)
  elapsed=$(( now - start_epoch ))
  sleep_for=$(( next - elapsed ))
  if [ "$sleep_for" -gt 0 ]; then
    echo "[$(date -u +%FT%TZ)] sleeping ${sleep_for}s until hour $((hour+1))"
    sleep "$sleep_for"
  fi
done

echo "[$(date -u +%FT%TZ)] === T2.9 24h time-series launcher DONE ==="
