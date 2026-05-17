"""PHASE 3 — CLI to capture DB-state snapshots from a live Preview.

Three modes:

  1. one-shot: snapshot now for a given preview + step label
       python3 scripts/collect_db_state_from_preview.py one-shot \
           --preview idem-abc12345 --step post_checkpoint \
           --subject s4-umami --run-id myrun --iso True \
           --out results/s4-umami/db_state_metrics_<TS>.csv

  2. watch: poll a Preview's .status.tests.step, snapshot at every transition
       python3 scripts/collect_db_state_from_preview.py watch \
           --preview idem-abc12345 --subject s4-umami --run-id myrun \
           --out results/s4-umami/db_state_metrics_<TS>.csv

  3. verify: read a db_state_metrics CSV and check that
     post_checkpoint snapshot_hash_global matches post_restore_regression and
     post_restore_e2e for every run_id. Reports per-run pass/fail.
       python3 scripts/collect_db_state_from_preview.py verify --csv FILE

Read-only: only ``kubectl exec ... psql -c <SELECT>`` is used. No DDL, no DML.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.db_state_collector import (  # noqa: E402
    PIPELINE_STEPS,
    discover_postgres_in_namespace,
    snapshot,
    iter_rows_to_csv,
)


# Map operator step labels (kubectl) to our PHASE 3 step labels
# Operator emits: postgres-migrate, saving, smoke, restore-regression, regression,
#                 restore-e2e, e2e, complete
# Our PHASE 3 (prompt.txt) labels are slightly different:
OPERATOR_TO_PHASE3 = {
    # On transition INTO these operator steps we record:
    #   the operator just finished the PREVIOUS step → snapshot is post_<prev>
    # We use "transition out of <X>" mapping. Easier: snapshot when we see the
    # NEXT step start, label with post_<previous>.
    # Direct mapping for clarity:
    "postgres-migrate": None,      # arriving here = beginning of pipeline ; nothing to snapshot
    "saving":           "post_migration",
    "smoke":            "post_checkpoint",
    "restore-regression":"post_smoke",   # also = pre_restore_regression
    "regression":       "post_restore_regression",
    "restore-e2e":      "post_regression",   # also = pre_restore_e2e
    "e2e":              "post_restore_e2e",
    "complete":         "post_e2e",
}


def _get_preview_ns(name: str) -> str:
    """Resolve the runtime namespace of a Preview CR."""
    r = subprocess.run(
        ["kubectl", "get", "preview", name, "-o",
         "jsonpath={.status.namespaceName}"],
        check=True, capture_output=True, text=True,
    )
    ns = r.stdout.strip()
    if not ns:
        raise RuntimeError(f"preview {name} has no .status.namespaceName yet")
    return ns


def cmd_one_shot(args) -> int:
    ns = _get_preview_ns(args.preview)
    tgt = discover_postgres_in_namespace(ns)
    rows = snapshot(
        tgt=tgt,
        run_id=args.run_id,
        subject_id=args.subject,
        preview_name=args.preview,
        isolation_enabled=(args.iso.lower() in ("true", "1", "yes")),
        step=args.step,
    )
    iter_rows_to_csv(rows, args.out, append=True)
    n_tables = len([r for r in rows if r["table_name"] != "*"])
    summary = next((r for r in rows if r["table_name"] == "*"), {})
    print(f"[ok] {n_tables} tables snapshotted; "
          f"snapshot_hash_global={summary.get('snapshot_hash_global', '')[:12]}..."
          f"  step={args.step}  ns={ns}")
    print(f"[ok] wrote {len(rows)} rows to {args.out}")
    return 0


def cmd_watch(args) -> int:
    print(f"[ok] watching preview {args.preview} ; snapshotting at every operator step "
          f"transition for up to {args.max_seconds}s")
    last_step = None
    deadline = time.time() + args.max_seconds
    captured: set[str] = set()
    while time.time() < deadline:
        try:
            r = subprocess.run(
                ["kubectl", "get", "preview", args.preview, "-o",
                 "jsonpath={.status.tests.step}"],
                check=False, capture_output=True, text=True, timeout=10,
            )
            step = r.stdout.strip()
        except subprocess.SubprocessError:
            step = ""

        if step and step != last_step:
            phase3_label = OPERATOR_TO_PHASE3.get(step)
            if phase3_label and phase3_label not in captured:
                try:
                    ns = _get_preview_ns(args.preview)
                    tgt = discover_postgres_in_namespace(ns)
                    rows = snapshot(
                        tgt=tgt,
                        run_id=args.run_id,
                        subject_id=args.subject,
                        preview_name=args.preview,
                        isolation_enabled=(args.iso.lower() in ("true", "1", "yes")),
                        step=phase3_label,
                    )
                    iter_rows_to_csv(rows, args.out, append=True)
                    summary = next((r for r in rows if r["table_name"] == "*"), {})
                    print(f"[ok] {phase3_label:25s}  hash={summary.get('snapshot_hash_global','')[:12]}...")
                    captured.add(phase3_label)
                except Exception as exc:
                    print(f"[warn] snapshot failed at step={step}: {exc}",
                          file=sys.stderr)
            last_step = step

        # Stop after we've captured post_e2e or saw "complete"
        if "post_e2e" in captured or step == "complete":
            print(f"[ok] preview reached terminal state — done. Captured {len(captured)} steps.")
            break
        time.sleep(args.poll_every)

    print(f"[ok] watch finished. captured steps: {sorted(captured)}")
    return 0


def cmd_verify(args) -> int:
    """Read a db_state_metrics CSV and check the restore invariants."""
    with open(args.csv) as f:
        rows = list(csv.DictReader(f))
    # Group by run_id, then step → global hash
    by_run: dict[str, dict[str, str]] = defaultdict(dict)
    for r in rows:
        if r.get("table_name") != "*":
            continue
        by_run[r["run_id"]][r["step"]] = r.get("snapshot_hash_global", "")

    if not by_run:
        print("[warn] no global-hash rows found in CSV")
        return 1

    print(f"=== Verifying restore invariants across {len(by_run)} runs ===")
    n_pass = n_fail = n_skip = 0
    for run_id, steps in sorted(by_run.items()):
        cp = steps.get("post_checkpoint")
        post_rr = steps.get("post_restore_regression")
        post_re = steps.get("post_restore_e2e")
        if not cp:
            print(f"  SKIP {run_id} : no post_checkpoint snapshot")
            n_skip += 1
            continue
        results = []
        if post_rr:
            results.append(("post_checkpoint == post_restore_regression",
                            cp == post_rr))
        if post_re:
            results.append(("post_checkpoint == post_restore_e2e",
                            cp == post_re))
        if not results:
            print(f"  SKIP {run_id} : no post_restore_* snapshots")
            n_skip += 1
            continue
        ok = all(r[1] for r in results)
        if ok:
            n_pass += 1
            tags = " ".join(t.split("==")[1].strip() for t, _ in results)
            print(f"  PASS {run_id}  restore_verified ({tags})")
        else:
            n_fail += 1
            print(f"  FAIL {run_id}")
            for tag, status in results:
                mark = "OK" if status else "DIRTY"
                print(f"        {mark}: {tag}")

    print(f"\n=== Summary: {n_pass} pass, {n_fail} fail, {n_skip} skip ===")
    return 0 if n_fail == 0 else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    one = sub.add_parser("one-shot")
    one.add_argument("--preview", required=True)
    one.add_argument("--subject", required=True)
    one.add_argument("--run-id", required=True)
    one.add_argument("--step", required=True,
                     help=f"One of: {', '.join(PIPELINE_STEPS)}")
    one.add_argument("--iso", default="True")
    one.add_argument("--out", required=True)
    one.set_defaults(func=cmd_one_shot)

    w = sub.add_parser("watch")
    w.add_argument("--preview", required=True)
    w.add_argument("--subject", required=True)
    w.add_argument("--run-id", required=True)
    w.add_argument("--iso", default="True")
    w.add_argument("--out", required=True)
    w.add_argument("--max-seconds", type=int, default=900)
    w.add_argument("--poll-every", type=int, default=3)
    w.set_defaults(func=cmd_watch)

    v = sub.add_parser("verify")
    v.add_argument("--csv", required=True)
    v.set_defaults(func=cmd_verify)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
