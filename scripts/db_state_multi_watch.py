"""PHASE 3 multi-watch — capture DB snapshot of EVERY preview that reaches a
test step, across multiple parallel previews. Useful when several procs run
simultaneously (PHASE B baseline) and we want db_state_metrics across all.

For each preview detected in Running phase with a test step:
- captures a one-shot snapshot at the current step
- dedupes by (preview_uid, step) to avoid re-capture

Read-only (kubectl exec + SELECT only). Designed to run alongside other procs.
"""
from __future__ import annotations
import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.db_state_collector import (  # noqa: E402
    discover_postgres_in_namespace,
    snapshot,
    iter_rows_to_csv,
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", default=str(ROOT / "results"))
    p.add_argument("--max-seconds", type=int, default=28800)
    p.add_argument("--poll-every", type=int, default=15)
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts_session = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    deadline = time.time() + args.max_seconds
    seen: set[str] = set()
    n_captured = 0

    print(f"[ok] multi-watch armed, polling every {args.poll_every}s, max {args.max_seconds}s")

    while time.time() < deadline:
        try:
            r = subprocess.run(
                ["kubectl", "get", "previews", "-A", "--no-headers"],
                check=False, capture_output=True, text=True,
            )
            lines = r.stdout.strip().split("\n") if r.stdout else []
        except Exception as exc:
            print(f"[warn] list previews: {exc}", file=sys.stderr)
            time.sleep(args.poll_every)
            continue

        for line in lines:
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            name = parts[0]
            phase = parts[1] if len(parts) > 1 else ""
            if phase != "Running":
                continue
            # Get UID + step
            try:
                meta = subprocess.run(
                    ["kubectl", "get", "preview", name, "-o",
                     "jsonpath={.metadata.uid}|{.status.namespaceName}|{.status.tests.step}|{.spec.image}"],
                    check=False, capture_output=True, text=True, timeout=10,
                )
                uid, ns, step, img = meta.stdout.split("|", 3)
            except Exception:
                continue
            if not (uid and ns and step):
                continue
            key = f"{uid}/{step}"
            if key in seen:
                continue
            # Infer subject from image tag — extended with image-tag aliases
            # for cases where the canonical sid string is absent from the image
            # (e.g. S1 uses "idp-preview" instead of "s1-flask-catalog").
            sid = "unknown"
            for canonical, aliases in (
                ("s1-flask-catalog", ("s1-flask-catalog", "idp-preview", "flask-catalog")),
                ("s2-listmonk",      ("s2-listmonk", "listmonk-adapter", "listmonk")),
                ("s3-healthchecks",  ("s3-healthchecks", "healthchecks-adapter", "healthchecks")),
                ("s4-umami",         ("s4-umami", "umami-adapter")),
                ("s5-petclinic",     ("s5-petclinic", "petclinic-adapter", "petclinic")),
            ):
                if any(a in img for a in aliases):
                    sid = canonical
                    break

            try:
                tgt = discover_postgres_in_namespace(ns)
                rows = snapshot(
                    tgt=tgt,
                    run_id=name,
                    subject_id=sid,
                    preview_name=name,
                    isolation_enabled=True,
                    step=step,
                )
            except Exception as exc:
                print(f"[warn] snapshot {name} step={step}: {exc}", file=sys.stderr)
                seen.add(key)
                continue

            out_path = out_dir / sid / f"db_state_metrics_{ts_session}.csv"
            iter_rows_to_csv(rows, str(out_path), append=True)
            seen.add(key)
            n_captured += len(rows)
            try:
                rel = out_path.relative_to(ROOT)
            except ValueError:
                rel = out_path
            print(f"[ok] {name}  sid={sid}  step={step}  +{len(rows)} rows  → {rel}")

        time.sleep(args.poll_every)

    print(f"[ok] multi-watch done. captured {len(seen)} (preview, step) pairs, {n_captured} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
