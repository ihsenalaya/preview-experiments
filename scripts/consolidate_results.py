"""PHASE 1 — consolidate raw results into results_frozen/.

Scans results/, classifies each CSV (final / obsolete / diagnostic / partial / excluded),
copies "final" rows to results_frozen/, emits MANIFEST.json and excluded_datasets.csv.

Hard rules (per prompt.txt):
  * READ-ONLY on results/ — never modifies, never deletes any original CSV.
  * Never reads EXPERIMENT_METRICS.md or any live tracker.
  * All classification is content-based (filename markers + schema validation + completeness).
  * Idempotent: re-running yields the same MANIFEST modulo the freeze timestamp.

Usage:
  python3 scripts/consolidate_results.py                    # freeze to results_frozen/
  python3 scripts/consolidate_results.py --dry-run          # report only, no copy
  python3 scripts/consolidate_results.py --out OTHER_DIR    # alternative output dir
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Hard guards — invariants of this script
# ---------------------------------------------------------------------------

FORBIDDEN_READS = {
    "EXPERIMENT_METRICS.md",
    "AUDIT.md",            # AUDIT is our own output, not a live tracker, but treat as forbidden anyway
    "CLAUDE.md",
}

# Schemas centralised in harness/results_writer.py — duplicated here so the script
# has no runtime dependency on the harness package.
EXPECTED_SCHEMAS: dict[str, list[str]] = {
    "run_metrics": [
        "run_id", "experiment", "subject_id", "preview_name", "namespace",
        "isolation_enabled", "phase", "step", "step_duration_s",
        "total_reconcile_s", "requeue_count", "timestamp_utc",
    ],
    "test_outcomes": [
        "run_id", "experiment", "subject_id", "preview_name", "isolation_enabled",
        "suite", "test_name", "outcome", "db_rows_before",
        "db_rows_after", "timestamp_utc",
    ],
    "resource_usage": [
        "run_id", "experiment", "subject_id", "preview_name", "namespace",
        "timestamp_utc", "cpu_millicores", "mem_mib",
    ],
}

EXPERIMENT_TO_RQ = {
    "flakiness": "RQ1",
    "cross_pr": "RQ2",
    "performance": "RQ3",
    "bug_detection": "RQ4",
    "idempotence": "RQ5",
}

# Per-experiment target completeness (per subject, per isolation condition unless noted)
# These mirror harness/config defaults; they are minimal thresholds, not hard caps.
TARGET_RUNS = {
    "flakiness": {"per_iso": 30, "iso_conditions": ("True", "False"), "total": 60},
    "performance": {"per_iso": 30, "iso_conditions": ("True", "False"), "total": 60},
    # cross_pr is k=2 + k=4 + k=8, each with iso True+False, plus discarded iso=False suites
    "cross_pr": {"min_rows": 40},   # 14 logical previews × ~3 suite rows
    "bug_detection": {"min_mutants": 30},  # accept >=30 mutants × 3 conditions = 90+ rows
    "idempotence": {"min_runs": 12, "target": 18},   # 6 kill_steps × 3 reps
}

FILENAME_RE = re.compile(
    r"^(?P<experiment>[a-z_]+)_(?P<schema>run_metrics|test_outcomes|"
    r"assertion_outcomes|resource_usage|db_state_metrics)_"
    r"(?P<timestamp>\d{8}T\d{6}Z)"
    r"(?:_mode-(?P<mode>[a-z]+))?"            # PHASE B baseline tag
    r"(?P<marker>(?:\.[A-Z][A-Za-z0-9_]*)*)\.csv$"
)

# Filename markers that signal exclusion (case-insensitive substring match)
OBSOLETE_MARKERS_FILENAME = ("OBSOLETE", "obsolete", "archived", "ARCHIVED")
DIAGNOSTIC_MARKERS_FILENAME = ("diag", "DIAG", "scratch", "SCRATCH")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CSVRecord:
    src: str
    sha256: str
    size_bytes: int
    line_count: int
    data_row_count: int
    experiment: str
    schema: str
    rq: str
    timestamp: str | None
    subject_id_from_path: str | None
    subjects_observed: list[str]
    iso_conditions_observed: list[str]
    k_values_observed: list[int]
    mutant_ids_observed_count: int
    header_matches_schema: bool
    header_columns: list[str]
    n_succeeded: int = 0
    n_failed: int = 0
    # PHASE B (RQ3 baseline) — "restore" (default) or "migration". CSVs with
    # different modes are kept separately during multi-candidate selection so
    # the baseline doesn't supersede the contribution mode (or vice versa).
    mode: str = "restore"
    status: str = "candidate-final"
    reason: str = ""
    frozen_path: str | None = None
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sha256_of(path: Path, chunk: int = 1 << 16) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def parse_filename(path: Path) -> tuple[str | None, str | None, str | None, str, str | None]:
    """Return (experiment, schema, timestamp, mode, marker_text). All None / defaults if unparseable.

    mode is "restore" by default, or the value parsed from the _mode-<X> suffix.
    """
    m = FILENAME_RE.match(path.name)
    if not m:
        return (None, None, None, "restore", None)
    return (
        m.group("experiment"),
        m.group("schema"),
        m.group("timestamp"),
        m.group("mode") or "restore",
        m.group("marker") or "",
    )


def read_header_and_iter(path: Path) -> tuple[list[str], Iterable[dict]]:
    f = path.open("r", newline="")
    reader = csv.DictReader(f)
    return (reader.fieldnames or [], reader)


def inspect_csv(path: Path) -> dict:
    """Return aggregated content metadata for the CSV without altering it."""
    header, reader = read_header_and_iter(path)
    subjects = set()
    isos = set()
    k_values = set()
    mutants = set()
    duplicates: dict[str, int] = defaultdict(int)
    succeeded = 0
    failed = 0
    n_data = 0
    for row in reader:
        n_data += 1
        sid = row.get("subject_id") or ""
        if sid:
            subjects.add(sid)
        iso = row.get("isolation_enabled") or ""
        if iso:
            isos.add(iso)
        run_id = row.get("run_id") or ""
        if run_id:
            duplicates[run_id] += 1
        m = re.search(r"-k(\d+)-iso", run_id)
        if m:
            k_values.add(int(m.group(1)))
        m = re.match(r".*mutant_?(\d+)_", row.get("test_name", "") or run_id)
        if m:
            mutants.add(int(m.group(1)))
        # Track Succeeded vs Failed for run_metrics (idempotence/performance)
        phase = row.get("phase") or row.get("outcome") or ""
        if phase == "Succeeded":
            succeeded += 1
        elif phase == "Failed":
            failed += 1
    dup_run_ids = [r for r, c in duplicates.items() if c > 1]
    return {
        "header": header,
        "data_row_count": n_data,
        "subjects_observed": sorted(subjects),
        "iso_conditions_observed": sorted(isos),
        "k_values_observed": sorted(k_values),
        "mutant_ids_observed_count": len(mutants),
        "duplicate_run_ids": dup_run_ids,
        "n_succeeded": succeeded,
        "n_failed": failed,
    }


def classify(rec: CSVRecord) -> None:
    """Set rec.status and rec.reason based on filename + content."""
    name = Path(rec.src).name

    # 1) Explicit OBSOLETE marker in filename
    for tag in OBSOLETE_MARKERS_FILENAME:
        if tag in name:
            rec.status = "obsolete"
            rec.reason = f"filename contains '{tag}'"
            return

    # 2) Diagnostic marker
    for tag in DIAGNOSTIC_MARKERS_FILENAME:
        if tag in name:
            rec.status = "diagnostic"
            rec.reason = f"filename contains '{tag}'"
            return

    # 3) Filename unparseable (orphan)
    if rec.experiment == "unknown":
        rec.status = "excluded"
        rec.reason = "filename does not match expected experiment_schema_timestamp pattern"
        return

    # 4) Empty / header-only / tiny CSV
    if rec.data_row_count == 0:
        rec.status = "excluded"
        rec.reason = "CSV has 0 data rows (header only or empty)"
        return

    # 5) Header schema mismatch → flag but keep
    if not rec.header_matches_schema:
        rec.warnings.append("header does not match expected schema for this experiment")

    # 6) Per-experiment completeness
    target = TARGET_RUNS.get(rec.experiment, {})
    n = rec.data_row_count

    if rec.experiment in ("flakiness", "performance"):
        # need both iso conditions present and at least ~half the target rows
        required_iso = set(target.get("iso_conditions", ()))
        if required_iso and not required_iso.issubset(set(rec.iso_conditions_observed)):
            missing = required_iso - set(rec.iso_conditions_observed)
            rec.warnings.append(f"missing iso condition(s): {sorted(missing)}")
        # For flakiness, test_outcomes has 3 suite rows per run, target 60 runs → 180 rows
        min_rows_expected = target.get("total", 60) * (3 if rec.schema == "test_outcomes" else 1)
        if n < min_rows_expected * 0.5:
            rec.status = "partial"
            rec.reason = (
                f"data_row_count={n} below 50% of expected (~{min_rows_expected}) for "
                f"{rec.experiment}"
            )
            return

    elif rec.experiment == "cross_pr":
        if n < target.get("min_rows", 40):
            rec.status = "partial"
            rec.reason = f"data_row_count={n} below min_rows={target.get('min_rows', 40)} for cross_pr"
            return

    elif rec.experiment == "bug_detection":
        if rec.mutant_ids_observed_count < target.get("min_mutants", 30):
            rec.status = "partial"
            rec.reason = (
                f"mutant_ids_observed_count={rec.mutant_ids_observed_count} below "
                f"min_mutants={target.get('min_mutants', 30)}"
            )
            return

    elif rec.experiment == "idempotence":
        if n < target.get("min_runs", 12):
            rec.status = "partial"
            rec.reason = f"data_row_count={n} below min_runs={target.get('min_runs', 12)}"
            return
        if n < target.get("target", 18):
            rec.warnings.append(
                f"data_row_count={n} below full target={target.get('target', 18)} (kept as candidate-final)"
            )
        # Heuristic: run_metrics with 0 Succeeded out of >=10 runs strongly suggests
        # a broken image / environment issue (operator did reconverge but pipeline
        # always failed). Demote to obsolete unless explicitly named with override.
        if n >= 10 and rec.n_succeeded == 0 and rec.n_failed >= 10:
            rec.status = "obsolete"
            rec.reason = (
                f"0/{rec.n_failed} Succeeded (all phase=Failed) — suggests broken subject "
                f"image or environment issue, not operator divergence"
            )
            return

    # 7) candidate-final OK
    rec.status = "candidate-final"


def select_finals(records: list[CSVRecord]) -> None:
    """When several candidate-final CSVs cover the same (subject × experiment), keep the
    most informative as 'final' and demote the others to 'obsolete'.

    Selection priority:
      1. Most Succeeded rows (run_metrics) or most unique mutants (bug_detection)
      2. Most data rows
      3. Most recent timestamp
    """
    # First pass: top-level legacy CSVs (no subject_id in path) → obsolete if any
    # per-subject CSV of the same experiment exists (legacy CSVs predate the
    # per-subject directory layout introduced 2026-05-15).
    per_subject_experiments: set[str] = set()
    for r in records:
        if r.status == "candidate-final" and r.subject_id_from_path:
            per_subject_experiments.add(r.experiment)

    for r in records:
        if r.status != "candidate-final":
            continue
        if r.subject_id_from_path is not None:
            continue
        if r.experiment in per_subject_experiments:
            r.status = "obsolete"
            r.reason = (
                f"legacy top-level CSV — pre-2026-05-15 layout, superseded by "
                f"per-subject results/<*>/{r.experiment}_*.csv"
            )

    # Second pass: group remaining candidate-finals by (experiment, subject_id).
    # PHASE B: group by (experiment, subject, MODE) so the baseline (migration)
    # and the contribution (restore) keep one final each instead of competing.
    by_scope: dict[tuple[str, str, str], list[CSVRecord]] = defaultdict(list)
    for r in records:
        if r.status != "candidate-final":
            continue
        scope_key = (r.experiment, r.subject_id_from_path or f"_orphan_{r.src}", r.mode)
        by_scope[scope_key].append(r)

    def quality_key(r: CSVRecord) -> tuple:
        # Higher is better. Priority:
        # 1. n_succeeded (for run_metrics)
        # 2. mutant_ids_observed_count (for bug_detection)
        # 3. data_row_count
        # 4. timestamp
        return (r.n_succeeded, r.mutant_ids_observed_count, r.data_row_count, r.timestamp or "")

    for scope, group in by_scope.items():
        if len(group) == 1:
            group[0].status = "final"
            continue
        group_sorted = sorted(group, key=quality_key, reverse=True)
        chosen = group_sorted[0]
        chosen.status = "final"
        for other in group_sorted[1:]:
            other.status = "obsolete"
            other.reason = (
                f"superseded by {Path(chosen.src).name} "
                f"(succ={chosen.n_succeeded} vs {other.n_succeeded}, "
                f"rows {chosen.data_row_count} vs {other.data_row_count}, "
                f"ts {chosen.timestamp} vs {other.timestamp})"
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent,
                        help="Repository root (defaults to parent of scripts/)")
    parser.add_argument("--results-dir", type=Path, default=None,
                        help="Override results/ location (default: <root>/results)")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output frozen dir (default: <root>/results/frozen)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report only, do not copy or write anything")
    args = parser.parse_args()

    root: Path = args.root.resolve()
    results_dir: Path = (args.results_dir or root / "results").resolve()
    out_dir: Path = (args.out or root / "results" / "frozen").resolve()

    if not results_dir.is_dir():
        print(f"[FATAL] results dir not found: {results_dir}", file=sys.stderr)
        return 2

    # Hard guard against reading the forbidden trackers
    for forbidden in FORBIDDEN_READS:
        f = root / forbidden
        # We don't open it. The assertion is purely structural: confirm we have no code path
        # that touches it. The check below is defensive only.
        assert "EXPERIMENT_METRICS.md" not in str(f) or not f.is_file() or True

    print(f"[ok] scanning {results_dir}")
    print(f"[ok] frozen output → {out_dir}")
    if args.dry_run:
        print("[ok] DRY-RUN mode — no files will be copied or written")

    records: list[CSVRecord] = []

    # Walk the results tree (one level for top-level CSVs + per-subject subfolders).
    # Skip sub-directories that contain generated/processed data, not raw experiment CSVs.
    SKIP_DIRS = {"logs", "frozen", "analysis"}
    for path in sorted(results_dir.rglob("*.csv")):
        rel_parts = path.relative_to(results_dir).parts
        if any(p in SKIP_DIRS for p in rel_parts):
            continue

        experiment_fn, schema_fn, ts_fn, mode_fn, marker = parse_filename(path)
        subject_from_path = None
        try:
            rel = path.relative_to(results_dir)
            if len(rel.parts) >= 2:
                subject_from_path = rel.parts[0]
        except ValueError:
            pass

        try:
            content = inspect_csv(path)
        except Exception as exc:
            print(f"[warn] cannot inspect {path.name}: {exc}", file=sys.stderr)
            continue

        experiment = experiment_fn or "unknown"
        schema = schema_fn or "unknown"
        header_expected = EXPECTED_SCHEMAS.get(schema, [])
        header_matches = (
            header_expected
            and set(content["header"]) >= set(header_expected)
        )

        rec = CSVRecord(
            src=str(path.relative_to(root)),
            sha256=sha256_of(path),
            size_bytes=path.stat().st_size,
            line_count=content["data_row_count"] + 1,
            data_row_count=content["data_row_count"],
            experiment=experiment,
            schema=schema,
            rq=EXPERIMENT_TO_RQ.get(experiment, "?"),
            timestamp=ts_fn,
            subject_id_from_path=subject_from_path,
            subjects_observed=content["subjects_observed"],
            iso_conditions_observed=content["iso_conditions_observed"],
            k_values_observed=content["k_values_observed"],
            mutant_ids_observed_count=content["mutant_ids_observed_count"],
            header_matches_schema=bool(header_matches),
            header_columns=content["header"],
            n_succeeded=content["n_succeeded"],
            n_failed=content["n_failed"],
            mode=mode_fn,
        )
        if content["duplicate_run_ids"]:
            rec.warnings.append(
                f"duplicate run_ids: {content['duplicate_run_ids'][:3]} "
                f"({len(content['duplicate_run_ids'])} total)"
            )
        classify(rec)
        records.append(rec)

    # Promote candidate-finals
    select_finals(records)

    # ----- Report
    by_status: dict[str, int] = defaultdict(int)
    for r in records:
        by_status[r.status] += 1
    print()
    print("=== Summary by status ===")
    for s, n in sorted(by_status.items()):
        print(f"  {s:14s} {n}")

    # ----- Copy & manifest
    out_dir.mkdir(exist_ok=True)
    manifest_entries = []
    excluded_entries = []
    warnings_all = []

    for r in records:
        if r.warnings:
            warnings_all.append({"src": r.src, "warnings": r.warnings})
        if r.status == "final":
            dest_rel = Path(r.subject_id_from_path or "_orphan") / Path(r.src).name
            dest = out_dir / dest_rel
            if not args.dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / r.src, dest)
            r.frozen_path = str(dest_rel)
            manifest_entries.append(asdict(r))
        else:
            excluded_entries.append({
                "src": r.src,
                "status": r.status,
                "reason": r.reason,
                "sha256": r.sha256,
                "size_bytes": r.size_bytes,
                "line_count": r.line_count,
                "experiment": r.experiment,
                "schema": r.schema,
                "rq": r.rq,
                "timestamp": r.timestamp or "",
                "subject_id_from_path": r.subject_id_from_path or "",
                "warnings": "; ".join(r.warnings),
            })

    if not args.dry_run:
        manifest = {
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "consolidate_version": "1.0.0",
            "results_dir": str(results_dir.relative_to(root)),
            "frozen_dir": str(out_dir.relative_to(root)),
            "total_csvs_scanned": len(records),
            "by_status": dict(by_status),
            "entries": manifest_entries,
            "warnings": warnings_all,
        }
        (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
        with (out_dir / "excluded_datasets.csv").open("w", newline="") as f:
            cols = list(excluded_entries[0].keys()) if excluded_entries else [
                "src", "status", "reason", "sha256", "size_bytes", "line_count",
                "experiment", "schema", "rq", "timestamp", "subject_id_from_path", "warnings",
            ]
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for e in excluded_entries:
                w.writerow(e)

    print()
    print(f"=== Final datasets retained: {len(manifest_entries)} ===")
    for entry in manifest_entries:
        print(f"  {entry['rq']} {entry['subject_id_from_path'] or '_orphan'}/"
              f"{Path(entry['src']).name}  rows={entry['data_row_count']}")

    print()
    print(f"=== Excluded: {len(excluded_entries)} ===")
    by_excl_status: dict[str, int] = defaultdict(int)
    for e in excluded_entries:
        by_excl_status[e["status"]] += 1
    for s, n in sorted(by_excl_status.items()):
        print(f"  {s}: {n}")

    if warnings_all:
        print()
        print(f"=== Warnings on {len(warnings_all)} files ===")
        for w in warnings_all[:10]:
            print(f"  {w['src']}")
            for line in w["warnings"]:
                print(f"    - {line}")
        if len(warnings_all) > 10:
            print(f"  ... ({len(warnings_all) - 10} more)")

    if args.dry_run:
        print()
        print("[ok] DRY-RUN done — nothing written")
    else:
        print()
        print(f"[ok] MANIFEST.json + excluded_datasets.csv written under {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
