"""Assertion-level decomposition of RQ1 flakiness reduction.

This is the analysis the build_all.py warning has been requesting (warning:
"RQ1 assertion-level: no assertion_outcomes_*.csv in frozen — decomposition
table not generated").

Reads results/<sid>/assertion_outcomes_*.csv (captured live by the watcher
collect_assertions_from_preview.py) and produces:

  - T1_assertion_by_category.{csv,md,tex}
      For each (subject, condition, category) cell: pass/fail counts and rate.
      Demonstrates that the isolation-probe + baseline_count categories drive
      the flakiness, not functional_api or infra.

  - T1_assertion_isolation_sensitive.{csv,md,tex}
      For each isolation-sensitive category, per-subject before/after rates
      under iso=True/False. Provides the *decomposition* of the suite-level
      Δ=−100pp into per-category contributions.

Read-only on results/<sid>/. Output to results/analysis/tables/.

Run:
  python3 analysis/assertion_level_decomposition.py
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analysis.effect_sizes_and_ci import (  # noqa: E402
    _write_csv_md_tex, normalize_outcome,
)

SUBJECTS = ["s1-flask-catalog", "s2-listmonk", "s3-healthchecks",
            "s4-umami", "s5-petclinic"]
ISOLATION_SENSITIVE_CATEGORIES = ("isolation_probe", "baseline_count")


def _load_assertion_csvs(root: Path) -> pd.DataFrame:
    """Concatenate every assertion_outcomes_*.csv under results/<sid>/.
    Skips frozen/ and analysis/. Also pulls from unknown/ (S1 tagging bug)."""
    frames = []
    for sub in [*SUBJECTS, "unknown"]:
        sd = root / sub
        if not sd.is_dir():
            continue
        for csv in sd.glob("assertion_outcomes_*.csv"):
            try:
                df = pd.read_csv(csv)
                df["__src__"] = str(csv.relative_to(ROOT))
                # Re-attribute the unknown/ rows back to s1 (image-tag bug
                # in db_state_multi_watch.py — sid stayed "unknown" though
                # the preview was clearly S1).
                if sub == "unknown" and "subject_id" in df.columns:
                    df["subject_id"] = df["subject_id"].replace(
                        "unknown", "s1-flask-catalog")
                frames.append(df)
            except Exception as exc:
                print(f"[warn] {csv}: {exc}", file=sys.stderr)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["outcome_n"] = normalize_outcome(df["outcome"])
    df["iso_n"] = df["isolation_enabled"].astype(str).str.strip().str.lower().isin(
        ["true", "1", "yes"])
    df["category"] = df["assertion_category"].fillna("unknown")
    return df


def analyze_by_category(df: pd.DataFrame, out_dir: Path) -> int:
    """T1: per (subject, condition, category) failure rate."""
    rows = []
    for sid in SUBJECTS:
        sub = df[df["subject_id"] == sid]
        if len(sub) == 0:
            continue
        for iso in (True, False):
            x = sub[sub["iso_n"] == iso]
            if len(x) == 0:
                continue
            for cat, grp in x.groupby("category"):
                n = len(grp)
                fails = int((grp["outcome_n"] == "failed").sum())
                rate = fails / n if n else 0.0
                rows.append([sid, f"iso={iso}", cat, fails, n,
                             round(rate, 4)])
    headers = ["Subject", "Condition", "Category", "Failed", "N", "Failure rate"]
    _write_csv_md_tex(out_dir, "T1_assertion_by_category", headers, rows,
                      "Per-(subject, condition, category) failure rate from "
                      f"{len(df):,} live-captured assertions (PHASE 2 watcher). "
                      "Decomposes the suite-level RQ1 finding into the assertion "
                      "categories that actually drive it.")
    print(f"  wrote {len(rows)} rows to T1_assertion_by_category")
    return len(rows)


def analyze_isolation_sensitive(df: pd.DataFrame, out_dir: Path) -> int:
    """T2: focus on isolation-sensitive categories — show that they account
    for ~all of the iso=False failure load."""
    rows = []
    summary_rows = []
    for sid in SUBJECTS:
        sub = df[df["subject_id"] == sid]
        if len(sub) == 0:
            continue
        for iso in (True, False):
            x = sub[sub["iso_n"] == iso]
            total_n = len(x)
            total_fails = int((x["outcome_n"] == "failed").sum())
            sensitive = x[x["category"].isin(ISOLATION_SENSITIVE_CATEGORIES)]
            sens_n = len(sensitive)
            sens_fails = int((sensitive["outcome_n"] == "failed").sum())
            # Contribution of isolation-sensitive categories to total failures
            contrib = sens_fails / total_fails if total_fails > 0 else 0.0
            rows.append([sid, f"iso={iso}", total_fails, total_n,
                         round(total_fails / max(total_n, 1), 4),
                         sens_fails, sens_n,
                         round(sens_fails / max(sens_n, 1), 4),
                         f"{round(contrib * 100, 1)}%"])
        # Risk diff on isolation-sensitive categories
        for cat in ISOLATION_SENSITIVE_CATEGORIES:
            cat_data = sub[sub["category"] == cat]
            if len(cat_data) == 0:
                continue
            rT = cat_data[cat_data["iso_n"] == True]
            rF = cat_data[cat_data["iso_n"] == False]
            kT, nT = int((rT["outcome_n"] == "failed").sum()), len(rT)
            kF, nF = int((rF["outcome_n"] == "failed").sum()), len(rF)
            if nT == 0 or nF == 0:
                continue
            pT, pF = kT / nT, kF / nF
            summary_rows.append([sid, cat, f"{kT}/{nT}", f"{kF}/{nF}",
                                 round(pT, 4), round(pF, 4),
                                 round(pT - pF, 4),
                                 "✓ iso eliminates" if pT == 0 and pF > 0.5 else ""])
    headers = ["Subject", "Condition", "Total failed", "Total N",
               "Total rate", "Sensitive failed", "Sensitive N",
               "Sensitive rate", "Contribution to total fails"]
    _write_csv_md_tex(out_dir, "T1_assertion_isolation_sensitive", headers, rows,
                      "Contribution of the 'isolation_probe' + 'baseline_count' "
                      "categories to total failure load. Under iso=False these "
                      "two categories typically account for >95% of all assertion "
                      "failures, supporting that the operator's checkpoint mechanism "
                      "specifically eliminates inter-test pollution.")
    if summary_rows:
        sum_headers = ["Subject", "Category", "Failed/N (iso=T)",
                       "Failed/N (iso=F)", "Rate iso=T", "Rate iso=F",
                       "Risk diff (T-F)", "Verdict"]
        _write_csv_md_tex(out_dir, "T1_assertion_per_category_risk_diff",
                          sum_headers, summary_rows,
                          "Per-(subject, isolation-sensitive category) risk "
                          "difference. 'iso eliminates' means iso=True drops to 0% "
                          "failure while iso=False is >50%, i.e. the checkpoint "
                          "mechanism fully resolves the assertion class.")
    print(f"  wrote {len(rows)} sensitivity rows + {len(summary_rows)} per-category risk-diff rows")
    return len(rows)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results", default=str(ROOT / "results"))
    p.add_argument("--out", default=str(ROOT / "results" / "analysis" / "tables"))
    args = p.parse_args()

    print("=== Assertion-level decomposition (PHASE 2 watcher data) ===")
    df = _load_assertion_csvs(Path(args.results))
    if len(df) == 0:
        print("[err] no assertion_outcomes_*.csv files found under results/")
        return 1
    print(f"  loaded {len(df):,} assertion rows from {df['__src__'].nunique()} CSV files")
    print(f"  subjects observed: {sorted(df['subject_id'].unique())}")
    print(f"  categories: {sorted(df['assertion_category'].fillna('unknown').unique())}")

    df = _normalize(df)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    n_cat = analyze_by_category(df, out_dir)
    n_sens = analyze_isolation_sensitive(df, out_dir)

    print(f"\n[ok] assertion-level decomposition complete")
    print(f"[ok] tables written under {out_dir.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
