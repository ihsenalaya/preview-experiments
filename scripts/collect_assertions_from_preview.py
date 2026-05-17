"""PHASE 2 — Standalone CLI to capture assertion-level outcomes from a live Preview.

Two modes:

  1. One-shot capture of a specific Preview:
       python3 scripts/collect_assertions_from_preview.py one-shot \
           --preview idem-abcdef12 --subject s4-umami \
           --run-id idempotence-s4-umami-stepe2e-00-abc123 \
           --experiment idempotence --iso True \
           --out results/s4-umami/assertion_outcomes_<TS>.csv

  2. Watch-mode (opportunistic capture of every Preview that reaches a
     terminal test phase). Useful to retrofit assertion data on a running
     experiment chain without modifying exp_*/run.py:
       python3 scripts/collect_assertions_from_preview.py watch \
           --out-dir results/ \
           --max-seconds 7200    # ~2 hours

Read-only: only `kubectl get preview ... -o json` is called. The Previews
themselves are not modified. CSV files in --out / --out-dir are appended.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.assertion_collector import (  # noqa: E402
    collect_from_preview_status,
    iter_rows_to_csv,
)

# Heuristic to derive subject/experiment/run_id from a Preview's spec/labels
# when watch-mode encounters a previously-unseen Preview.
RUN_ID_PATTERNS = [
    re.compile(r"^(?P<exp>flakiness|cross_pr|performance|bug_detection|idempotence)-"
               r"(?P<sid>[a-z0-9-]+?)-(.+)$"),
]


def _run_kubectl(*args, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", *args], check=check, capture_output=True, text=True)


def _list_previews() -> list[dict]:
    r = _run_kubectl("get", "previews", "-A", "-o", "json", check=False)
    if r.returncode != 0:
        return []
    return json.loads(r.stdout).get("items", []) or []


def _terminal(preview: dict) -> bool:
    """A Preview is 'terminal' enough to capture when all 3 suites have a
    non-Provisioning phase (Succeeded or Failed)."""
    tests = preview.get("status", {}).get("tests", {})
    for s in ("smoke", "regression", "e2e"):
        phase = tests.get(s, {}).get("phase", "")
        if phase not in ("Succeeded", "Failed"):
            return False
    return True


def _infer_run_metadata(preview: dict) -> tuple[str, str, str, bool]:
    """Best-effort: return (experiment, subject_id, run_id, isolation_enabled).
    Falls back to ("unknown", "unknown", preview-name, True)."""
    name = preview.get("metadata", {}).get("name", "")
    spec = preview.get("spec", {})
    db = spec.get("database", {}) or {}
    iso = bool(db.get("isolationEnabled", True))
    sid_path = ""
    image = spec.get("image") or ""
    # The image tag often encodes the subject (e.g. s4-umami-adapter).
    # Extended aliases handle non-canonical image tags (e.g. S1 uses
    # "idp-preview" instead of "s1-flask-catalog").
    subject_image = spec.get("subject", {}).get("image", "") if isinstance(
        spec.get("subject"), dict) else ""
    for canonical, aliases in (
        ("s1-flask-catalog", ("s1-flask-catalog", "idp-preview", "flask-catalog")),
        ("s2-listmonk",      ("s2-listmonk", "listmonk-adapter", "listmonk")),
        ("s3-healthchecks",  ("s3-healthchecks", "healthchecks-adapter", "healthchecks")),
        ("s4-umami",         ("s4-umami", "umami-adapter")),
        ("s5-petclinic",     ("s5-petclinic", "petclinic-adapter", "petclinic")),
    ):
        if any(a in image or a in subject_image for a in aliases):
            sid_path = canonical
            break
    # run_id derivable from prefix of name
    prefix = name.split("-", 1)[0] if "-" in name else ""
    exp = {
        "fl":   "flakiness",
        "cp":   "cross_pr",
        "pf":   "performance",
        "bd":   "bug_detection",
        "idem": "idempotence",
    }.get(prefix, "unknown")
    run_id = name  # fallback
    return (exp, sid_path or "unknown", run_id, iso)


def cmd_one_shot(args) -> int:
    rows = collect_from_preview_status(
        preview_status=_load_status(args.preview, args.namespace),
        subject_id=args.subject,
        run_id=args.run_id,
        preview_name=args.preview,
        isolation_enabled=(args.iso.lower() in ("true", "1", "yes")),
        experiment=args.experiment,
        strategy=args.strategy,
    )
    iter_rows_to_csv(rows, args.out, append=True)
    print(f"[ok] {len(rows)} assertion rows appended to {args.out}")
    return 0


def _load_status(name: str, namespace: str) -> dict:
    r = _run_kubectl("get", "preview", name, "-n", namespace, "-o", "json", check=False)
    if r.returncode != 0:
        print(f"[err] kubectl: {r.stderr}", file=sys.stderr)
        return {}
    return json.loads(r.stdout).get("status", {})


def cmd_watch(args) -> int:
    seen: set[str] = set()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + args.max_seconds
    poll_every = args.poll_every
    ts_session = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    n_captured = 0

    print(f"[ok] watch-mode armed; polling every {poll_every}s; max {args.max_seconds}s")
    print(f"[ok] out dir: {out_dir}")

    while time.time() < deadline:
        try:
            previews = _list_previews()
        except Exception as exc:
            print(f"[warn] list_previews error: {exc}", file=sys.stderr)
            time.sleep(poll_every)
            continue

        for p in previews:
            name = p.get("metadata", {}).get("name", "")
            uid = p.get("metadata", {}).get("uid", "")
            key = f"{name}/{uid}"
            if key in seen:
                continue
            if not _terminal(p):
                continue

            exp, sid, run_id, iso = _infer_run_metadata(p)
            rows = collect_from_preview_status(
                preview_status=p.get("status", {}),
                subject_id=sid,
                run_id=run_id,
                preview_name=name,
                isolation_enabled=iso,
                experiment=exp,
            )
            if not rows:
                seen.add(key)
                continue

            out_path = out_dir / sid / f"assertion_outcomes_{ts_session}.csv"
            iter_rows_to_csv(rows, str(out_path), append=True)
            seen.add(key)
            n_captured += len(rows)
            try:
                rel = out_path.relative_to(ROOT)
            except ValueError:
                rel = out_path
            print(f"[ok] {name}  exp={exp}  sid={sid}  iso={iso}  +{len(rows)} rows  "
                  f"→ {rel}")

        time.sleep(poll_every)

    print(f"[ok] watch done. total {len(seen)} previews captured, {n_captured} assertion rows")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    one = sub.add_parser("one-shot")
    one.add_argument("--preview", required=True)
    one.add_argument("--namespace", default="default")
    one.add_argument("--subject", required=True)
    one.add_argument("--run-id", required=True)
    one.add_argument("--experiment", required=True)
    one.add_argument("--iso", default="True")
    one.add_argument("--strategy", default="")
    one.add_argument("--out", required=True)
    one.set_defaults(func=cmd_one_shot)

    w = sub.add_parser("watch")
    w.add_argument("--out-dir", default=str(ROOT / "results"))
    w.add_argument("--max-seconds", type=int, default=7200)
    w.add_argument("--poll-every", type=int, default=10)
    w.set_defaults(func=cmd_watch)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
