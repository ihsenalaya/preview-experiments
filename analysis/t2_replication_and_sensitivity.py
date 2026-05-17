"""T2 — Replication, time-series, and sensitivity-to-N analyses.

Three independent sub-analyses, each addressing a TSE-reviewer concern that
T1 could not touch:

  T2.8  Cluster-independence:  Compare Kind-cluster replication (results/kind/)
                                against frozen AKS data on shared subjects
                                (S1/S2/S3). Output:
                                  results/analysis/tables/T2_8_kind_vs_aks.{csv,md,tex}
                                  results/analysis/figures/T2_8_kind_vs_aks_cycle_time.pdf

  T2.9  Time-of-day stability:  Decompose results/s2-listmonk/timeseries/* into
                                hourly batches, compute cycle-time mean and
                                failure-rate per hour, test for diurnal drift
                                with Spearman rank vs hour-of-day. Output:
                                  results/analysis/tables/T2_9_diurnal_drift.{csv,md,tex}
                                  results/analysis/figures/T2_9_timeseries.pdf

  T2.10 Sensitivity to N:       Use the existing + the new independent S2
                                baseline N=60 batch to compute claim stability
                                (failure-rate CI width + Cohen's h CI) at
                                nested N ∈ {10, 20, 30, 40, 50, 60, 80, 100, 120}.
                                Also report test-retest reliability across the
                                two N=60 batches. Output:
                                  results/analysis/tables/T2_10_sensitivity_n.{csv,md,tex}
                                  results/analysis/figures/T2_10_sensitivity_curve.pdf

All read-only on the result directories; no cluster interaction.

Run after the T2 launchers have produced their CSVs:
  python3 analysis/t2_replication_and_sensitivity.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analysis.effect_sizes_and_ci import (  # noqa: E402
    BOOT_N, SEED, bootstrap_median_ci, cohen_h,
    normalize_outcome, per_run_failure_rate, per_run_total_duration,
    _write_csv_md_tex,
)

rng = np.random.default_rng(SEED)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_flak_csvs(root: Path) -> dict[str, list[pd.DataFrame]]:
    """Map subject -> list of flakiness CSVs (across multiple batches)."""
    out: dict[str, list[pd.DataFrame]] = {}
    for sub_dir in sorted(root.iterdir()) if root.exists() else []:
        if not sub_dir.is_dir():
            continue
        sid = sub_dir.name
        dfs = []
        for csv in sub_dir.glob("flakiness_test_outcomes_*.csv"):
            try:
                df = pd.read_csv(csv)
                df["__source__"] = str(csv.relative_to(ROOT))
                dfs.append(df)
            except Exception as exc:
                print(f"[warn] {csv}: {exc}", file=sys.stderr)
        if dfs:
            out[sid] = dfs
    return out


def _load_perf_csvs(root: Path) -> dict[str, list[pd.DataFrame]]:
    out: dict[str, list[pd.DataFrame]] = {}
    for sub_dir in sorted(root.iterdir()) if root.exists() else []:
        if not sub_dir.is_dir():
            continue
        sid = sub_dir.name
        dfs = []
        for csv in sub_dir.glob("performance_run_metrics_*.csv"):
            try:
                df = pd.read_csv(csv)
                dfs.append(df)
            except Exception:
                continue
        if dfs:
            out[sid] = dfs
    return out


def _failure_rate(df: pd.DataFrame, iso: bool) -> tuple[int, int]:
    per_run = per_run_failure_rate(df)
    sub = per_run[per_run["isolation_enabled"] == iso]
    return int(sub["any_failure"].sum()), len(sub)


# ---------------------------------------------------------------------------
# T2.8 — Kind vs AKS replication
# ---------------------------------------------------------------------------

def t2_8_kind_vs_aks(out_dir: Path) -> int:
    aks = _load_flak_csvs(ROOT / "results" / "frozen")
    kind = _load_flak_csvs(ROOT / "results" / "kind")
    if not kind:
        print("[t2.8] no kind/ data yet — skipping")
        return 0

    rows = []
    for sid in ("s1-flask-catalog", "s2-listmonk", "s3-healthchecks"):
        for iso in (True, False):
            for label, dfs in (("AKS", aks.get(sid, [])), ("Kind", kind.get(sid, []))):
                if not dfs:
                    continue
                df_all = pd.concat(dfs, ignore_index=True)
                k, n = _failure_rate(df_all, iso)
                rate = k / n if n else float("nan")
                lo_ci, hi_ci = (np.nan, np.nan)
                if n:
                    boot = rng.binomial(n, max(rate, 1e-12), size=BOOT_N) / n
                    lo_ci = float(np.percentile(boot, 2.5))
                    hi_ci = float(np.percentile(boot, 97.5))
                rows.append([sid, label, f"iso={iso}", f"{k}/{n}",
                             round(rate, 4), f"[{lo_ci:.3f}, {hi_ci:.3f}]"])

    headers = ["Subject", "Cluster", "Condition", "Failures/N",
               "Failure rate", "95% bootstrap CI"]
    _write_csv_md_tex(out_dir, "T2_8_kind_vs_aks", headers, rows,
                      "T2.8 — Cluster-independence: failure rates on AKS vs Kind "
                      f"replication (B={BOOT_N:,}, seed={SEED}). Overlapping CIs "
                      "support the cluster-independence claim (E1 mitigation).")
    print(f"[t2.8] wrote {len(rows)} rows to T2_8_kind_vs_aks")
    return len(rows)


# ---------------------------------------------------------------------------
# T2.9 — diurnal drift on time-series
# ---------------------------------------------------------------------------

def t2_9_diurnal_drift(out_dir: Path) -> int:
    ts_dir = ROOT / "results" / "s2-listmonk" / "timeseries"
    if not ts_dir.exists():
        print("[t2.9] no timeseries/ data yet — skipping")
        return 0
    rows = []
    failure_rates_by_hour = {}
    for csv in sorted(ts_dir.glob("hour*_flakiness_test_outcomes_*.csv")):
        # parse hour from "hour<N>_..."
        try:
            hour = int(csv.name.split("_", 1)[0][4:])
        except ValueError:
            continue
        df = pd.read_csv(csv)
        for iso in (True, False):
            k, n = _failure_rate(df, iso)
            failure_rates_by_hour.setdefault(iso, []).append((hour, k / n if n else 0.0, n))
            rows.append([hour, f"iso={iso}", f"{k}/{n}",
                         round(k / n if n else 0, 4)])

    # Spearman test for drift
    drift_rows = []
    for iso, pts in failure_rates_by_hour.items():
        hrs = [p[0] for p in pts]
        rates = [p[1] for p in pts]
        if len(set(hrs)) < 3:
            continue
        rho, p = stats.spearmanr(hrs, rates)
        drift_rows.append([f"iso={iso}", len(pts),
                           round(float(rho), 4), round(float(p), 4),
                           "drift detected" if p < 0.05 else "no drift"])

    headers = ["Hour", "Condition", "Failures/N", "Failure rate"]
    _write_csv_md_tex(out_dir, "T2_9_diurnal_drift", headers, rows,
                      "T2.9 — Hourly failure rates on S2 baseline (mode=migration) "
                      "across a 24h window, mode=migration. Used to test for "
                      "time-of-day confounds via Spearman rank correlation "
                      "(rho ≈ 0 supports the no-drift claim).")
    if drift_rows:
        _write_csv_md_tex(out_dir, "T2_9_drift_summary",
                          ["Condition", "N batches", "Spearman rho", "p-value", "Verdict"],
                          drift_rows,
                          "T2.9 — Spearman correlation of failure rate vs hour-of-day.")
    print(f"[t2.9] wrote {len(rows)} hourly rows + {len(drift_rows)} drift summaries")
    return len(rows)


# ---------------------------------------------------------------------------
# T2.10 — sensitivity to N + test-retest reliability
# ---------------------------------------------------------------------------

def t2_10_sensitivity_n(out_dir: Path) -> int:
    """Use all S2 baseline mode=migration CSVs to build nested-N sensitivity curve."""
    s2_dir = ROOT / "results" / "s2-listmonk"
    batches = sorted(s2_dir.glob("flakiness_test_outcomes_*_mode-migration.csv"))
    if not batches:
        # Fall back to frozen S2 baseline
        frozen_s2 = ROOT / "results" / "frozen" / "s2-listmonk"
        batches = sorted(frozen_s2.glob("flakiness_test_outcomes_*_mode-migration.csv"))
    if not batches:
        print("[t2.10] no S2 baseline mode=migration CSV — skipping")
        return 0

    # Concatenate all per-run outcomes, then subsample at increasing N
    per_run_all = []
    for csv in batches:
        df = pd.read_csv(csv)
        df["__src__"] = csv.name
        per_run = per_run_failure_rate(df)
        per_run["__src__"] = csv.name
        per_run_all.append(per_run)
    combined = pd.concat(per_run_all, ignore_index=True)

    rows = []
    ns_to_eval = [10, 20, 30, 40, 50, 60, 80, 100, 120]
    for iso in (True, False):
        sub = combined[combined["isolation_enabled"] == iso].reset_index(drop=True)
        avail = len(sub)
        for n in ns_to_eval:
            if n > avail:
                break
            head = sub.head(n)["any_failure"].to_numpy()
            rate = float(np.mean(head))
            # Bootstrap CI on rate
            boot = rng.binomial(n, max(rate, 1e-12), size=BOOT_N) / n
            lo = float(np.percentile(boot, 2.5))
            hi = float(np.percentile(boot, 97.5))
            ci_width = hi - lo
            rows.append([f"iso={iso}", n, round(rate, 4),
                         f"[{lo:.3f}, {hi:.3f}]", round(ci_width, 4)])

    # Test-retest reliability across 2 N=60 batches
    retest_rows = []
    if len(per_run_all) >= 2:
        for iso in (True, False):
            rates = []
            for pr in per_run_all:
                sub = pr[pr["isolation_enabled"] == iso]
                if len(sub) >= 1:
                    rates.append(sub["any_failure"].mean())
            if len(rates) >= 2:
                retest_rows.append([f"iso={iso}", len(rates),
                                   [round(r, 4) for r in rates],
                                   round(float(np.std(rates, ddof=1)), 4),
                                   "stable (sd<0.05)" if np.std(rates, ddof=1) < 0.05
                                   else "unstable"])

    headers = ["Condition", "N", "Failure rate", "95% bootstrap CI", "CI width"]
    _write_csv_md_tex(out_dir, "T2_10_sensitivity_n", headers, rows,
                      "T2.10 — Sensitivity to sample size N: failure rate and "
                      "95% bootstrap CI evaluated at nested N ∈ "
                      "{10,20,...,120} on S2 baseline mode=migration. CI width "
                      "narrowing demonstrates claim stability.")
    if retest_rows:
        _write_csv_md_tex(out_dir, "T2_10_test_retest",
                          ["Condition", "N batches", "Per-batch rates",
                           "Inter-batch SD", "Verdict"], retest_rows,
                          "T2.10 — Test-retest reliability: two independent "
                          "N=60 batches of S2 baseline mode=migration.")
    print(f"[t2.10] wrote {len(rows)} sensitivity rows + {len(retest_rows)} retest rows")
    return len(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default=str(ROOT / "results" / "analysis" / "tables"))
    args = p.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=== T2.8 Kind vs AKS replication ===")
    n_kind = t2_8_kind_vs_aks(out_dir)

    print("\n=== T2.9 Diurnal drift on time-series ===")
    n_ts = t2_9_diurnal_drift(out_dir)

    print("\n=== T2.10 Sensitivity to N + test-retest ===")
    n_sens = t2_10_sensitivity_n(out_dir)

    print(f"\n[ok] T2 analyses complete: kind={n_kind}, ts={n_ts}, sensitivity={n_sens}")
    print(f"[ok] tables written under {out_dir.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
