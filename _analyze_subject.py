"""
Compute RQ1 (flakiness) and RQ3 (performance) stats per subject from the CSVs.

Usage:
    python3 _analyze_subject.py s4-umami
    python3 _analyze_subject.py s2-listmonk

Prints ready-to-paste tables in the style of ANALYSIS_S1.md.
"""
import sys
from pathlib import Path

import pandas as pd
from scipy import stats as sstats

SUBJECT = sys.argv[1]
ROOT = Path(__file__).parent / "results" / SUBJECT


def cohen_h(p1: float, p2: float) -> float:
    import math
    phi1 = 2 * math.asin(math.sqrt(p1))
    phi2 = 2 * math.asin(math.sqrt(p2))
    return abs(phi1 - phi2)


def cliffs_delta(a, b):
    a, b = list(a), list(b)
    n_a, n_b = len(a), len(b)
    if n_a == 0 or n_b == 0:
        return None
    gt = sum(1 for x in a for y in b if x > y)
    lt = sum(1 for x in a for y in b if x < y)
    return (gt - lt) / (n_a * n_b)


def rq1_flakiness():
    files = sorted(ROOT.glob("flakiness_test_outcomes_*.csv"))
    if not files:
        return "No flakiness CSV found.\n"
    df = pd.concat([pd.read_csv(f) for f in files if f.stat().st_size > 0], ignore_index=True)
    df = df[df["suite"].isin(["smoke", "regression", "e2e"])]
    out = [f"### RQ1 Flakiness — {SUBJECT}\n"]
    out.append(f"Source files: {', '.join(f.name for f in files)}\n")
    out.append(f"Total rows: {len(df)}\n\n")
    out.append("| Suite | iso=True (fail/total) | iso=False (fail/total) | Δ fail rate | Fisher p | Cohen's h |\n")
    out.append("|---|---|---|---|---|---|\n")
    for suite in ["smoke", "regression", "e2e"]:
        rows = df[df["suite"] == suite]
        on = rows[rows["isolation_enabled"].astype(str) == "True"]
        off = rows[rows["isolation_enabled"].astype(str) == "False"]
        on_fail = (on["outcome"] == "Failed").sum()
        off_fail = (off["outcome"] == "Failed").sum()
        on_n = len(on)
        off_n = len(off)
        p1 = on_fail / on_n if on_n else 0
        p2 = off_fail / off_n if off_n else 0
        delta = (p1 - p2) * 100
        try:
            _, fisher_p = sstats.fisher_exact([[on_fail, on_n - on_fail], [off_fail, off_n - off_fail]], alternative="less")
        except Exception:
            fisher_p = float("nan")
        h = cohen_h(p1, p2) if on_n and off_n else 0
        out.append(f"| {suite} | {on_fail}/{on_n} ({p1*100:.1f}%) | {off_fail}/{off_n} ({p2*100:.1f}%) | {delta:+.0f} pp | {fisher_p:.3g} | {h:.2f} |\n")
    return "".join(out)


def rq3_performance():
    files = sorted(ROOT.glob("performance_run_metrics_*.csv"))
    if not files:
        return "No performance CSV found.\n"
    df = pd.concat([pd.read_csv(f) for f in files if f.stat().st_size > 0], ignore_index=True)
    out = [f"### RQ3 Performance — {SUBJECT}\n"]
    out.append(f"Source files: {', '.join(f.name for f in files)}\n")
    out.append(f"Total rows: {len(df)}\n\n")

    # Step durations
    steps = ["postgres-migrate", "saving", "smoke", "restore-regression", "regression", "restore-e2e", "e2e"]
    out.append("**Per-step duration (s, iso=True)**\n\n")
    out.append("| Step | n | mean | std | median | min | max |\n")
    out.append("|---|---|---|---|---|---|---|\n")
    on = df[df["isolation_enabled"].astype(str) == "True"]
    for s in steps:
        d = on[on["step"] == s]["step_duration_s"].dropna()
        if len(d) > 0:
            out.append(f"| {s} | {len(d)} | {d.mean():.1f} | {d.std():.2f} | {d.median():.1f} | {d.min():.1f} | {d.max():.1f} |\n")

    # Pipeline total
    out.append("\n**Pipeline total `total_reconcile_s`**\n\n")
    on_tot = df[(df["isolation_enabled"].astype(str) == "True")].drop_duplicates("run_id")["total_reconcile_s"].dropna()
    off_tot = df[(df["isolation_enabled"].astype(str) == "False")].drop_duplicates("run_id")["total_reconcile_s"].dropna()
    out.append(f"| Condition | n | mean (s) | std | median | min | max |\n")
    out.append("|---|---|---|---|---|---|---|\n")
    out.append(f"| iso=True | {len(on_tot)} | {on_tot.mean():.1f} | {on_tot.std():.2f} | {on_tot.median():.1f} | {on_tot.min():.1f} | {on_tot.max():.1f} |\n")
    if len(off_tot) > 0:
        out.append(f"| iso=False | {len(off_tot)} | {off_tot.mean():.1f} | {off_tot.std():.2f} | {off_tot.median():.1f} | {off_tot.min():.1f} | {off_tot.max():.1f} |\n")
        out.append(f"| **Overhead** | — | **+{on_tot.mean()-off_tot.mean():+.1f}s ({(on_tot.mean()/off_tot.mean()-1)*100:+.1f}%)** | — | — | — | — |\n")
        try:
            u_stat, mwu_p = sstats.mannwhitneyu(on_tot, off_tot, alternative="two-sided")
            d = cliffs_delta(on_tot, off_tot)
            out.append(f"\nMann-Whitney U = {u_stat:.0f}, p = {mwu_p:.3g}; Cliff's delta = {d:.3f}\n")
        except Exception:
            pass

    # Checkpoint total = saving + restore-regression + restore-e2e (iso=True)
    chk_total = on[on["step"].isin(["saving", "restore-regression", "restore-e2e"])].groupby("run_id")["step_duration_s"].sum()
    if len(chk_total) > 0:
        out.append(f"\n**Checkpoint overhead** (saving + 2× restore, iso=True): mean **{chk_total.mean():.1f}s** ± {chk_total.std():.2f}, median {chk_total.median():.1f}s, n={len(chk_total)}\n")

    return "".join(out)


if __name__ == "__main__":
    print(rq1_flakiness())
    print()
    print(rq3_performance())
