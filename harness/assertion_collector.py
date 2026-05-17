"""PHASE 2 — Assertion-level outcome collector.

Reads the per-suite output captured by the operator into
.status.tests.{smoke,regression,e2e}.output, parses each PASS/FAIL line,
categorizes the assertion, and yields one structured row per assertion.

Designed to be invoked from harness/exp_*/run.py at the end of a run, OR
retroactively via scripts/collect_assertions_from_preview.py on a live preview.

No mutation of the Preview CR — read-only.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from typing import Iterable

from harness.assertion_categories import (
    categorize,
    is_isolation_sensitive,
    normalize_failure_signature,
    parse_expected_observed,
)

# Output line format produced by the test programs:
#   "PASS regression run_log_clean"
#   "FAIL regression teams_list: not 200"
#   "FAIL regression owner_update: update failed"
#
# Pattern catches:
#   group(1)=outcome  group(2)=suite  group(3)=assertion  group(4)=optional reason (after ":")
_LINE_RE = re.compile(r"^(PASS|FAIL)\s+(\S+)\s+(\S+?)(?::\s*(.*))?$")


def parse_output_line(line: str) -> dict | None:
    """Parse a single PASS/FAIL line. Returns None if it doesn't match the format
    (e.g. summary lines like "Results: 8 passed, 1 failed")."""
    m = _LINE_RE.match(line.strip())
    if not m:
        return None
    return {
        "outcome_raw": m.group(1),       # "PASS" or "FAIL"
        "suite": m.group(2),             # "smoke" / "regression" / "e2e"
        "assertion": m.group(3),         # "run_log_clean", etc.
        "message": (m.group(4) or "").strip(),
    }


def collect_from_preview_status(
    *,
    preview_status: dict,
    subject_id: str,
    run_id: str,
    preview_name: str,
    isolation_enabled: bool,
    experiment: str,
    strategy: str = "",
    timestamp: str | None = None,
) -> list[dict]:
    """Build a list of assertion_outcomes rows from a Preview's .status.tests object.

    preview_status is the parsed JSON value of `kubectl get preview ... -o json`,
    specifically the contents of `.status`.

    Returns a list of dicts with the schema defined in PHASE 2.
    """
    ts = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    iso_str = "True" if isolation_enabled else "False"

    rows: list[dict] = []
    tests = preview_status.get("tests", {}) if preview_status else {}
    for suite_name in ("smoke", "regression", "e2e"):
        suite_obj = tests.get(suite_name, {}) or {}
        for line in suite_obj.get("output", []) or []:
            parsed = parse_output_line(line)
            if not parsed:
                continue
            assertion = parsed["assertion"]
            category = categorize(subject_id, suite_name, assertion)
            outcome = "Succeeded" if parsed["outcome_raw"] == "PASS" else "Failed"
            expected, observed = parse_expected_observed(parsed["message"])
            signature = (
                normalize_failure_signature(parsed["message"])
                if outcome == "Failed" else ""
            )
            rows.append({
                "experiment_id": experiment,
                "subject_id": subject_id,
                "run_id": run_id,
                "preview_name": preview_name,
                "isolation_enabled": iso_str,
                "strategy": strategy,
                "suite_name": suite_name,
                "assertion_id": assertion,
                "assertion_category": category,
                "outcome": outcome,
                "expected": expected,
                "observed": observed,
                "normalized_failure_signature": signature,
                "is_isolation_sensitive": str(is_isolation_sensitive(assertion, category)),
                "ts": ts,
            })
    return rows


def fetch_preview_json(name: str, namespace: str = "default") -> dict:
    """Read a live Preview CR via kubectl. Read-only — no mutation."""
    r = subprocess.run(
        ["kubectl", "get", "preview", name, "-n", namespace, "-o", "json"],
        check=True, capture_output=True, text=True,
    )
    return json.loads(r.stdout)


def collect_from_live_preview(
    *,
    name: str,
    subject_id: str,
    run_id: str,
    isolation_enabled: bool,
    experiment: str,
    namespace: str = "default",
    strategy: str = "",
) -> list[dict]:
    """Convenience wrapper: fetch the Preview JSON then parse."""
    preview = fetch_preview_json(name, namespace=namespace)
    return collect_from_preview_status(
        preview_status=preview.get("status", {}),
        subject_id=subject_id,
        run_id=run_id,
        preview_name=name,
        isolation_enabled=isolation_enabled,
        experiment=experiment,
        strategy=strategy,
    )


def iter_rows_to_csv(rows: Iterable[dict], path: str, append: bool = True) -> None:
    """Append rows to a CSV at `path`. Creates the file with header if absent."""
    import csv
    from pathlib import Path

    p = Path(path)
    write_header = (not p.exists()) or (not append)
    p.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if (append and p.exists()) else "w"

    fieldnames = [
        "experiment_id", "subject_id", "run_id", "preview_name",
        "isolation_enabled", "strategy", "suite_name", "assertion_id",
        "assertion_category", "outcome", "expected", "observed",
        "normalized_failure_signature", "is_isolation_sensitive", "ts",
    ]
    with p.open(mode, newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            w.writeheader()
        for r in rows:
            w.writerow(r)
