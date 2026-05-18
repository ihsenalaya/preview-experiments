#!/usr/bin/env bash
# T2.10 v2 — relance après crash v1 (Run 17/30 isoTrue) avec retry-logic
# Utilise _run_one_subject_retry.py qui monkey-patche kubectl apply
# pour retry up to 5x avec exponential backoff.
#
# Lancé pendant que 22939 (S5 fix7 RQ1) tourne — Spring RQ1 ne kill pas
# l'opérateur (contrairement à RQ5), donc contention attendue MUCH LOWER
# que pendant la crash de v1.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$ROOT/logs/t2-10-v2-sensitivity-k-s2-$(date -u +%Y%m%dT%H%M%SZ).log"
exec >>"$LOG" 2>&1
cd "$ROOT"

echo "[$(date -u +%FT%TZ)] === T2.10 v2 sensitivity-K launcher START ==="
echo "[$(date -u +%FT%TZ)] config: SUBJECT=s2-listmonk EXPERIMENT=flakiness CHECKPOINT_MODE=migration N=60"
echo "[$(date -u +%FT%TZ)] retry: enabled via _run_one_subject_retry.py (5 attempts, exp backoff 2-30s)"
echo "[$(date -u +%FT%TZ)] cluster sanity: previews count"
kubectl get previews -A --no-headers 2>/dev/null | wc -l

CHECKPOINT_MODE=migration \
SUBJECT=s2-listmonk \
EXPERIMENT=flakiness \
  python3 -u _run_one_subject_retry.py
RC=$?

echo "[$(date -u +%FT%TZ)] === T2.10 v2 done rc=$RC ==="
