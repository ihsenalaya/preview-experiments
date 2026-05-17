"""PHASE 5 — RQ2 K-consistency checker.

Reads only results_frozen/<subject>/cross_pr_test_outcomes_*.csv and reports,
per (subject, K, isolation_enabled), whether the number of distinct previews
observed matches the K declared by the run_id parsing.

Output:
  analysis/output/k_consistency_report.txt   (human-readable summary)
  analysis/output/k_consistency_report.csv   (machine-readable per-batch rows)

Columns of the CSV:
  subject_id, batch_id, isolation_enabled, declared_K, observed_previews,
  missing_previews, completion_rate, incomplete_batch, suspected_infra_pressure, notes
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# run_id format historique :
#   cross_pr-k{K}-iso{True|False}-{batch_id8hex}-{idx}-concurrent_k{K}                 (legacy top-level)
#   cross_pr-{subject_id}-k{K}-iso{True|False}-{batch_id8hex}-{idx}-concurrent_k{K}    (per-subject)
RUN_ID_RE = re.compile(
    r"^cross_pr-(?:(?P<sid>[a-z0-9-]+)-)?k(?P<k>\d+)-iso(?P<iso>True|False)-"
    r"(?P<batch>[0-9a-f]+)-(?P<idx>\d+)-concurrent_k(?P<k2>\d+)$"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", type=Path,
                        default=Path(__file__).resolve().parent.parent / "results_frozen",
                        help="Frozen results directory (default: ../results_frozen)")
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parent / "output",
                        help="Output directory (default: analysis/output)")
    args = parser.parse_args()

    frozen: Path = args.frozen.resolve()
    out: Path = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    if not frozen.is_dir():
        print(f"[FATAL] frozen dir not found: {frozen}", file=sys.stderr)
        return 2

    # Find all cross_pr CSVs under frozen
    csv_files = sorted(frozen.glob("*/cross_pr_test_outcomes_*.csv"))
    if not csv_files:
        print(f"[WARN] no cross_pr CSVs in {frozen}", file=sys.stderr)
        return 1

    print(f"[ok] scanning {len(csv_files)} cross_pr CSVs")

    # Aggregate: per (sid, batch, k_declared, iso) -> set of preview_names
    batches: dict[tuple[str, str, int, str], set[str]] = defaultdict(set)
    batch_to_k_self_reported: dict[tuple[str, str, int, str], set[int]] = defaultdict(set)
    unparsed_count = 0
    total_rows = 0

    for path in csv_files:
        sid_path = path.parent.name
        with path.open("r", newline="") as f:
            for row in csv.DictReader(f):
                total_rows += 1
                run_id = row.get("run_id", "")
                m = RUN_ID_RE.match(run_id)
                if not m:
                    unparsed_count += 1
                    continue
                sid = m.group("sid") or sid_path
                batch = m.group("batch")
                k = int(m.group("k"))
                k2 = int(m.group("k2"))
                iso = m.group("iso")
                preview = row.get("preview_name", "")
                key = (sid, batch, k, iso)
                if preview:
                    batches[key].add(preview)
                batch_to_k_self_reported[key].add(k2)

    print(f"[ok] parsed {total_rows} rows ({unparsed_count} unparsed run_ids)")

    # Build report
    report_rows = []
    text_lines = ["# RQ2 K-consistency report", ""]
    text_lines.append(f"Source: {frozen}")
    text_lines.append(f"Total CSV files scanned: {len(csv_files)}")
    text_lines.append(f"Total rows: {total_rows} ({unparsed_count} unparsed)")
    text_lines.append("")

    # Group by subject
    by_subject: dict[str, list[tuple]] = defaultdict(list)
    for (sid, batch, k, iso), previews in sorted(batches.items()):
        observed = len(previews)
        missing = max(0, k - observed)
        completion = observed / k if k > 0 else 0.0
        incomplete = (observed != k)
        suspected_infra = (k == 8 and observed < k)  # K=8 sous AKS 3 nodes = pression CPU connue
        k2_set = batch_to_k_self_reported.get((sid, batch, k, iso), set())
        notes = ""
        if k2_set != {k}:
            notes = f"k declared={k} but run_id suffix concurrent_k={sorted(k2_set)}"
        report_rows.append({
            "subject_id": sid,
            "batch_id": batch,
            "isolation_enabled": iso,
            "declared_K": k,
            "observed_previews": observed,
            "missing_previews": missing,
            "completion_rate": f"{completion:.2%}",
            "incomplete_batch": incomplete,
            "suspected_infra_pressure": suspected_infra,
            "notes": notes,
        })
        by_subject[sid].append((batch, k, iso, observed, missing, completion, incomplete, suspected_infra, notes))

    # Text report per subject
    for sid in sorted(by_subject.keys()):
        text_lines.append(f"## {sid}")
        text_lines.append("")
        text_lines.append(f"| batch | K decl. | iso | observed | missing | completion | incomplete | infra-pressure | notes |")
        text_lines.append(f"|---|---|---|---|---|---|---|---|---|")
        for (batch, k, iso, obs, miss, comp, inc, infra, notes) in sorted(by_subject[sid]):
            flag_inc = "❌" if inc else "✅"
            flag_infra = "⚠️" if infra else ""
            text_lines.append(
                f"| {batch[:8]} | {k} | {iso} | {obs} | {miss} | {comp:.0%} | {flag_inc} | {flag_infra} | {notes} |"
            )
        text_lines.append("")

    # Summary by (subject, K)
    text_lines.append("## Summary by (subject, K)")
    text_lines.append("")
    text_lines.append("| subject | K | batches | mean completion | min completion | any incomplete? |")
    text_lines.append("|---|---|---|---|---|---|")
    summary: dict[tuple[str, int], list[float]] = defaultdict(list)
    incomp_any: dict[tuple[str, int], bool] = defaultdict(bool)
    for r in report_rows:
        key = (r["subject_id"], r["declared_K"])
        summary[key].append(float(r["completion_rate"].rstrip("%")) / 100)
        if r["incomplete_batch"]:
            incomp_any[key] = True
    for (sid, k), comps in sorted(summary.items()):
        mean_c = sum(comps) / len(comps)
        min_c = min(comps)
        flag = "❌ YES" if incomp_any[(sid, k)] else "✅ no"
        text_lines.append(f"| {sid} | {k} | {len(comps)} | {mean_c:.1%} | {min_c:.1%} | {flag} |")
    text_lines.append("")

    # Aggregate warning suggestions for the paper
    text_lines.append("## Warnings (use these in paper / discussion)")
    text_lines.append("")
    any_warning = False
    for r in report_rows:
        if r["incomplete_batch"] or r["suspected_infra_pressure"]:
            any_warning = True
            text_lines.append(
                f"- Subject **{r['subject_id']}** batch `{r['batch_id'][:8]}` iso={r['isolation_enabled']} "
                f"K={r['declared_K']}: observed {r['observed_previews']}/{r['declared_K']} previews "
                f"({r['completion_rate']} completion). "
                + ("⚠️ Suspected infra pressure at K=8 on 3-node cluster. " if r["suspected_infra_pressure"] else "")
                + (f"Notes: {r['notes']}" if r["notes"] else "")
            )
    if not any_warning:
        text_lines.append("- (none — all batches complete, no infra-pressure warnings)")

    # Write outputs
    txt_path = out / "k_consistency_report.txt"
    csv_path = out / "k_consistency_report.csv"
    txt_path.write_text("\n".join(text_lines))
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(report_rows[0].keys()) if report_rows else [
            "subject_id", "batch_id", "isolation_enabled", "declared_K", "observed_previews",
            "missing_previews", "completion_rate", "incomplete_batch", "suspected_infra_pressure", "notes",
        ])
        w.writeheader()
        for r in report_rows:
            w.writerow(r)

    print(f"[ok] wrote {txt_path}")
    print(f"[ok] wrote {csv_path}")

    # Print summary to stdout
    print()
    print("=== Summary ===")
    for (sid, k), comps in sorted(summary.items()):
        mean_c = sum(comps) / len(comps)
        flag = " [INCOMPLETE]" if incomp_any[(sid, k)] else ""
        print(f"  {sid} K={k}: {len(comps)} batches, mean completion {mean_c:.1%}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
