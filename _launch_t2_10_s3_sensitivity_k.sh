#!/usr/bin/env bash
# T2.10 sur s3-healthchecks — 2ᵉ sujet pour sensitivity-K + cross-subject test-retest.
# Profite du metrics_collector.py fix (rowcount pod now passes ResourceQuota).
# ETA ~2h (s3 healthchecks Python Django, modérément rapide).
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$ROOT/logs/t2-10-s3-sensitivity-k-$(date -u +%Y%m%dT%H%M%SZ).log"
exec >>"$LOG" 2>&1
cd "$ROOT"

echo "[$(date -u +%FT%TZ)] === T2.10 s3 sensitivity-K launcher START ==="
echo "[$(date -u +%FT%TZ)] config: SUBJECT=s3-healthchecks EXPERIMENT=flakiness CHECKPOINT_MODE=migration"

CHECKPOINT_MODE=migration \
SUBJECT=s3-healthchecks \
EXPERIMENT=flakiness \
  python3 -u _run_one_subject_retry.py
RC=$?

echo "[$(date -u +%FT%TZ)] === T2.10 s3 done rc=$RC ==="
