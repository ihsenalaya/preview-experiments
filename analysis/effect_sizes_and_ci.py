"""T1 — TSE-grade statistical hardening (post-hoc effect sizes, bootstrap CI,
variance-equality tests, TOST equivalence for RQ4 non-inferiority).

This is a **standalone** analysis that reads frozen CSVs only (read-only).
It does not modify build_all.py and does not interact with the live pipeline.

Outputs (under results/analysis/tables/):
  T1_effect_sizes.{csv,md,tex}        Cohen's d/h, Cliff's delta, observed power
  T1_bootstrap_ci.{csv,md,tex}        Median + 95% bootstrap CI (10k resamples)
  T1_variance_tests.{csv,md,tex}      Levene / Bartlett + variance-ratio CI (RQ1)
  T1_rq4_noninferiority.{csv,md,tex}  TOST 5pp-margin equivalence (RQ4)

Run:
  python3 analysis/effect_sizes_and_ci.py
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analysis.build_all import SUBJECTS, load_frozen  # noqa: E402

ALPHA = 0.05
BOOT_N = 10_000
SEED = 20260517
RQ4_TOST_MARGIN = 0.05  # equivalence margin: 5 percentage points

rng = np.random.default_rng(SEED)


# ---------------------------------------------------------------------------
# Effect-size primitives
# ---------------------------------------------------------------------------

def cohen_d(x: np.ndarray, y: np.ndarray) -> float:
    nx, ny = len(x), len(y)
    if nx < 2 or ny < 2:
        return float("nan")
    sx2, sy2 = np.var(x, ddof=1), np.var(y, ddof=1)
    pooled = math.sqrt(((nx - 1) * sx2 + (ny - 1) * sy2) / (nx + ny - 2))
    if pooled == 0:
        return float("nan")
    return (np.mean(x) - np.mean(y)) / pooled


def cliffs_delta(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) == 0 or len(y) == 0:
        return float("nan")
    gt = lt = 0
    for xi in x:
        gt += int(np.sum(y < xi))
        lt += int(np.sum(y > xi))
    return (gt - lt) / (len(x) * len(y))


def cohen_h(p1: float, p2: float) -> float:
    p1 = min(max(p1, 1e-12), 1 - 1e-12)
    p2 = min(max(p2, 1e-12), 1 - 1e-12)
    return 2 * (math.asin(math.sqrt(p1)) - math.asin(math.sqrt(p2)))


def observed_power_t(d: float, n1: int, n2: int, alpha: float = ALPHA) -> float:
    """Normal-approximation post-hoc power for two-sample t-test (Cohen)."""
    if n1 < 2 or n2 < 2 or math.isnan(d):
        return float("nan")
    n_eff = (n1 * n2) / (n1 + n2)
    z_alpha = stats.norm.ppf(1 - alpha / 2)
    z_eff = abs(d) * math.sqrt(n_eff)
    return float(stats.norm.cdf(z_eff - z_alpha) + stats.norm.cdf(-z_eff - z_alpha))


def observed_power_h(h: float, n1: int, n2: int, alpha: float = ALPHA) -> float:
    """Cohen's h to two-proportion power via normal approx."""
    return observed_power_t(h, n1, n2, alpha=alpha)


def bootstrap_median_ci(x: np.ndarray, n_boot: int = BOOT_N) -> tuple[float, float, float]:
    if len(x) < 2:
        return (float("nan"),) * 3
    idx = rng.integers(0, len(x), size=(n_boot, len(x)))
    boot = np.median(x[idx], axis=1)
    return float(np.median(x)), float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))


def variance_ratio_ci(x: np.ndarray, y: np.ndarray, n_boot: int = BOOT_N) -> tuple[float, float, float]:
    """Bootstrap CI on var(x)/var(y)."""
    if len(x) < 2 or len(y) < 2:
        return (float("nan"),) * 3
    boot = np.empty(n_boot)
    for i in range(n_boot):
        bx = x[rng.integers(0, len(x), size=len(x))]
        by = y[rng.integers(0, len(y), size=len(y))]
        vy = np.var(by, ddof=1)
        boot[i] = np.var(bx, ddof=1) / vy if vy > 0 else float("inf")
    pt = np.var(x, ddof=1) / np.var(y, ddof=1) if np.var(y, ddof=1) > 0 else float("inf")
    return float(pt), float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))


def tost_two_proportions(k1: int, n1: int, k2: int, n2: int, eps: float
                         ) -> tuple[float, float, bool]:
    """TOST for difference of proportions p1 - p2, equivalence margin ±eps.
    Returns (p_lower, p_upper, equivalent_at_alpha)."""
    p1, p2 = k1 / n1, k2 / n2
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    if se == 0:
        equiv = -eps < (p1 - p2) < eps
        return (0.0 if equiv else 1.0, 0.0 if equiv else 1.0, equiv)
    z_low = ((p1 - p2) - (-eps)) / se   # H0a: diff ≤ -eps
    z_up = ((p1 - p2) - eps) / se       # H0b: diff ≥ +eps
    p_low = 1 - stats.norm.cdf(z_low)
    p_up = stats.norm.cdf(z_up)
    return float(p_low), float(p_up), bool(max(p_low, p_up) < ALPHA)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_outcome(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower()


def per_run_total_duration(df_perf: pd.DataFrame) -> pd.DataFrame:
    """Sum step_duration_s per run_id, keep iso label."""
    keep = df_perf[df_perf["step"].isin(
        ["smoke", "regression", "e2e", "checkpoint_total", "postgres-migrate",
         "restore-regression", "restore-e2e", "saving"])].copy()
    total = (keep.groupby(["run_id", "isolation_enabled"])["step_duration_s"]
             .sum().reset_index())
    return total


def per_run_failure_rate(df_flak: pd.DataFrame) -> pd.DataFrame:
    """Return run-level failure indicator (1 if any test failed) per iso."""
    df = df_flak.copy()
    df["outcome_norm"] = normalize_outcome(df["outcome"])
    grp = df.groupby(["run_id", "isolation_enabled"])["outcome_norm"].apply(
        lambda s: int((s == "failed").any())
    ).reset_index().rename(columns={"outcome_norm": "any_failure"})
    return grp


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------

def analyze_rq1(frozen: dict, out_dir: Path) -> tuple[list, list, list]:
    """Effect sizes + bootstrap + variance test for flakiness."""
    flak = frozen.get("flakiness", {})
    rows_eff, rows_var, rows_ci = [], [], []
    for sid in SUBJECTS:
        df = flak.get(sid)
        if df is None or len(df) == 0:
            continue
        per_run = per_run_failure_rate(df)
        iso_T = per_run[per_run["isolation_enabled"] == True]["any_failure"].to_numpy()
        iso_F = per_run[per_run["isolation_enabled"] == False]["any_failure"].to_numpy()
        if len(iso_T) < 2 or len(iso_F) < 2:
            continue
        pT, pF = iso_T.mean(), iso_F.mean()
        h = cohen_h(pT, pF)
        power = observed_power_h(h, len(iso_T), len(iso_F))
        delta = cliffs_delta(iso_T.astype(float), iso_F.astype(float))
        rows_eff.append([sid, "RQ1-flakiness", len(iso_T), len(iso_F),
                         round(pT, 4), round(pF, 4),
                         round(h, 4), round(delta, 4), round(power, 4)])

        # Variance equality (the "zero variance" claim)
        try:
            stat_lev, p_lev = stats.levene(iso_T, iso_F, center="median")
        except Exception:
            stat_lev, p_lev = float("nan"), float("nan")
        try:
            stat_bart, p_bart = stats.bartlett(iso_T, iso_F)
        except Exception:
            stat_bart, p_bart = float("nan"), float("nan")
        vr, vr_lo, vr_hi = variance_ratio_ci(iso_T, iso_F)
        rows_var.append([sid, "flakiness", round(np.var(iso_T, ddof=1), 6),
                         round(np.var(iso_F, ddof=1), 6),
                         round(vr, 4) if np.isfinite(vr) else "inf",
                         f"[{vr_lo:.3f}, {vr_hi:.3f}]" if np.isfinite(vr_lo) else "n/a",
                         f"{stat_lev:.3f}/{p_lev:.4f}" if not math.isnan(stat_lev) else "n/a",
                         f"{stat_bart:.3f}/{p_bart:.4f}" if not math.isnan(stat_bart) else "n/a"])

        # Bootstrap CI on failure rate
        med_T, lo_T, hi_T = bootstrap_median_ci(iso_T.astype(float))
        med_F, lo_F, hi_F = bootstrap_median_ci(iso_F.astype(float))
        rows_ci.append([sid, "RQ1-flakiness", "iso=True", round(pT, 4),
                        f"[{lo_T:.3f}, {hi_T:.3f}]", len(iso_T)])
        rows_ci.append([sid, "RQ1-flakiness", "iso=False", round(pF, 4),
                        f"[{lo_F:.3f}, {hi_F:.3f}]", len(iso_F)])
    return rows_eff, rows_var, rows_ci


def analyze_rq3(frozen: dict, out_dir: Path) -> tuple[list, list]:
    """Effect sizes + bootstrap on cycle-time distributions."""
    perf = frozen.get("performance", {})
    rows_eff, rows_ci = [], []
    for sid in SUBJECTS:
        df = perf.get(sid)
        if df is None or len(df) == 0:
            continue
        tot = per_run_total_duration(df)
        iso_T = tot[tot["isolation_enabled"] == True]["step_duration_s"].to_numpy()
        iso_F = tot[tot["isolation_enabled"] == False]["step_duration_s"].to_numpy()
        if len(iso_T) < 2 or len(iso_F) < 2:
            continue
        d = cohen_d(iso_T, iso_F)
        delta = cliffs_delta(iso_T, iso_F)
        power = observed_power_t(d, len(iso_T), len(iso_F))
        rows_eff.append([sid, "RQ3-cycle-time", len(iso_T), len(iso_F),
                         round(float(np.mean(iso_T)), 2), round(float(np.mean(iso_F)), 2),
                         round(d, 4), round(delta, 4), round(power, 4)])
        m_T, lo_T, hi_T = bootstrap_median_ci(iso_T)
        m_F, lo_F, hi_F = bootstrap_median_ci(iso_F)
        rows_ci.append([sid, "RQ3-cycle-time", "iso=True", round(m_T, 2),
                        f"[{lo_T:.2f}, {hi_T:.2f}] s", len(iso_T)])
        rows_ci.append([sid, "RQ3-cycle-time", "iso=False", round(m_F, 2),
                        f"[{lo_F:.2f}, {hi_F:.2f}] s", len(iso_F)])
    return rows_eff, rows_ci


def analyze_rq4_tost(frozen: dict, out_dir: Path) -> list:
    """TOST equivalence test for bug-detection rate iso=True vs iso=False.
    Argues that isolation does NOT impair detection capacity (non-inferiority)."""
    bd = frozen.get("bug_detection", {})
    rows = []
    for sid in SUBJECTS:
        df = bd.get(sid)
        if df is None or len(df) == 0:
            continue
        # Normalize iso (some files have lowercase strings)
        df = df.copy()
        df["iso_norm"] = df["isolation_enabled"].astype(str).str.strip().str.lower().isin(
            ["true", "1", "yes"])
        df["outcome_norm"] = normalize_outcome(df["outcome"])
        # Detected = test Failed on mutant (failure on injected fault is "detection")
        df["detected"] = (df["outcome_norm"] == "failed").astype(int)
        grp = df.groupby("iso_norm")["detected"].agg(["sum", "count"])
        if True not in grp.index or False not in grp.index:
            # Only one iso condition present (e.g. S1 only seeded True)
            present = "T" if True in grp.index else "F"
            k = int(grp["sum"].iloc[0]); n = int(grp["count"].iloc[0])
            rows.append([sid, f"only iso={present}", k, n,
                         round(k / max(n, 1), 4), "n/a", "n/a", "n/a",
                         "insufficient (need both iso conditions)"])
            continue
        kT, nT = int(grp.loc[True, "sum"]), int(grp.loc[True, "count"])
        kF, nF = int(grp.loc[False, "sum"]), int(grp.loc[False, "count"])
        p_lo, p_up, equiv = tost_two_proportions(kT, nT, kF, nF, RQ4_TOST_MARGIN)
        rows.append([sid, "both", f"{kT}/{nT}", f"{kF}/{nF}",
                     round(kT / nT, 4), round(kF / nF, 4),
                     round(p_lo, 4), round(p_up, 4),
                     "EQUIVALENT (±5pp)" if equiv else "non-equivalent"])
    return rows


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def _write_csv_md_tex(out_dir: Path, name: str, headers: list, rows: list,
                      caption: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    # CSV
    csv_path = out_dir / f"{name}.csv"
    with csv_path.open("w") as f:
        f.write(",".join(headers) + "\n")
        for r in rows:
            f.write(",".join(str(x).replace(",", ";") for x in r) + "\n")
    # MD
    md = ["| " + " | ".join(headers) + " |",
          "|" + "|".join(["---"] * len(headers)) + "|"]
    md += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    md.append(f"\n*{caption}*")
    (out_dir / f"{name}.md").write_text("\n".join(md) + "\n")
    # TeX
    col_spec = "l" * len(headers)
    tex = [r"\begin{table}[t]", r"\centering",
           f"\\caption{{{caption}}}",
           f"\\label{{tab:{name}}}",
           f"\\begin{{tabular}}{{{col_spec}}}", r"\hline",
           " & ".join(_tex_escape(h) for h in headers) + r" \\", r"\hline"]
    for r in rows:
        tex.append(" & ".join(_tex_escape(str(x)) for x in r) + r" \\")
    tex += [r"\hline", r"\end{tabular}", r"\end{table}"]
    (out_dir / f"{name}.tex").write_text("\n".join(tex) + "\n")


def _tex_escape(s: str) -> str:
    return (s.replace("_", r"\_").replace("%", r"\%").replace("&", r"\&")
             .replace("$", r"\$").replace("#", r"\#"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--frozen", default=str(ROOT / "results" / "frozen"))
    p.add_argument("--out", default=str(ROOT / "results" / "analysis" / "tables"))
    args = p.parse_args()

    frozen = load_frozen(Path(args.frozen))
    out_dir = Path(args.out)

    print("=== T1.1+T1.2 RQ1 (effect sizes + variance tests + bootstrap CI) ===")
    rq1_eff, rq1_var, rq1_ci = analyze_rq1(frozen, out_dir)
    print(f"  {len(rq1_eff)} subjects analyzed for RQ1")

    print("=== T1.1 RQ3 (effect sizes + bootstrap CI cycle-time) ===")
    rq3_eff, rq3_ci = analyze_rq3(frozen, out_dir)
    print(f"  {len(rq3_eff)} subjects analyzed for RQ3")

    print("=== T1.5 RQ4 (TOST non-inferiority, margin=5pp) ===")
    rq4_rows = analyze_rq4_tost(frozen, out_dir)
    print(f"  {len(rq4_rows)} subjects analyzed for RQ4")

    # Combine effect-size tables across RQs
    eff_headers = ["Subject", "Metric", "N (iso=T)", "N (iso=F)",
                   "Mean iso=T", "Mean iso=F", "Effect size (d/h)",
                   "Cliff's δ", "Observed power (α=0.05)"]
    _write_csv_md_tex(out_dir, "T1_effect_sizes", eff_headers, rq1_eff + rq3_eff,
                      "Post-hoc effect sizes and observed power for RQ1 (flakiness, "
                      "Cohen's h) and RQ3 (cycle-time, Cohen's d). Cliff's delta is "
                      "the rank-based non-parametric alternative; observed power is "
                      "computed via normal approximation at alpha=0.05.")

    var_headers = ["Subject", "Experiment", "Var(iso=T)", "Var(iso=F)",
                   "Var ratio T/F", "95% CI (bootstrap)", "Levene stat/p",
                   "Bartlett stat/p"]
    _write_csv_md_tex(out_dir, "T1_variance_tests", var_headers, rq1_var,
                      "Variance-equality tests for the RQ1 'zero-variance under "
                      "isolation' claim. Var(iso=T)≈0 with Levene p<<0.05 supports "
                      "the elimination claim; bootstrap CI on variance ratio "
                      "quantifies the asymmetry.")

    ci_headers = ["Subject", "RQ", "Condition", "Point estimate",
                  "95% bootstrap CI", "N"]
    _write_csv_md_tex(out_dir, "T1_bootstrap_ci", ci_headers, rq1_ci + rq3_ci,
                      f"Bootstrap 95% confidence intervals ({BOOT_N:,} resamples, "
                      f"seed={SEED}) on median estimates for RQ1 (failure rate) "
                      "and RQ3 (per-run total cycle time, seconds).")

    rq4_headers = ["Subject", "Iso coverage", "Detected/N (iso=T)",
                   "Detected/N (iso=F)", "Rate iso=T", "Rate iso=F",
                   "TOST p-low", "TOST p-up", "Verdict (margin=5pp)"]
    _write_csv_md_tex(out_dir, "T1_rq4_noninferiority", rq4_headers, rq4_rows,
                      "RQ4 reframed as non-inferiority: TOST equivalence test "
                      "(margin = 5 percentage points) on bug-detection rate "
                      "iso=True vs iso=False. EQUIVALENT means isolation does not "
                      "harm detection capacity at the 5pp tolerance.")

    print(f"\n[ok] T1 tables written to {out_dir.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
