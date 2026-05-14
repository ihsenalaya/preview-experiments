#!/usr/bin/env bash
# Run all experiments in sequence and convert analysis scripts to notebooks.
# Assumes the cluster is already bootstrapped via setup/bootstrap-cluster.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

LOG="$SCRIPT_DIR/results/run-all-$(date -u +%Y%m%dT%H%M%SZ).log"
mkdir -p results
exec > >(tee -a "$LOG") 2>&1

echo "=========================================="
echo " Preview-Operator Experiments"
echo " Started: $(date -u)"
echo "=========================================="

run_exp() {
    local name="$1"
    local script="$2"
    echo ""
    echo "--- $name ---"
    echo "Start: $(date -u)"
    python3 "$script"
    echo "Done: $(date -u)"
}

run_exp "RQ1 Flakiness"      exp_flakiness/run.py
run_exp "RQ2 Cross-PR"       exp_cross_pr/run.py
run_exp "RQ3 Performance"    exp_performance/run.py
run_exp "RQ4 Bug Detection"  exp_bug_detection/run.py
run_exp "RQ5 Idempotence"    exp_idempotence/run.py

echo ""
echo "=========================================="
echo " All experiments done. Converting notebooks..."
echo "=========================================="

if command -v jupytext &>/dev/null; then
    for f in analysis/0*.py; do
        jupytext --to notebook "$f" --output "${f%.py}.ipynb"
    done
    echo "Notebooks generated."
else
    echo "jupytext not found — skipping .ipynb conversion (pip install jupytext)."
fi

echo "Log: $LOG"
echo "Finished: $(date -u)"
