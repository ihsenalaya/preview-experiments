#!/usr/bin/env bash
# T2.10 sur s4-umami — 3ᵉ sujet pour sensitivity-K (Umami TS/Prisma plus rapide).
# ETA ~1h30.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$ROOT/logs/t2-10-s4-sensitivity-k-$(date -u +%Y%m%dT%H%M%SZ).log"
exec >>"$LOG" 2>&1
cd "$ROOT"

echo "[$(date -u +%FT%TZ)] === T2.10 s4 sensitivity-K launcher START ==="
echo "[$(date -u +%FT%TZ)] config: SUBJECT=s4-umami EXPERIMENT=flakiness CHECKPOINT_MODE=migration"

CHECKPOINT_MODE=migration \
SUBJECT=s4-umami \
EXPERIMENT=flakiness \
  python3 -u _run_one_subject_retry.py
RC=$?

echo "[$(date -u +%FT%TZ)] === T2.10 s4 done rc=$RC ==="
