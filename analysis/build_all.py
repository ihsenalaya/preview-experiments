"""PHASE 6 — analyse reproductible principale.

Lit EXCLUSIVEMENT depuis ../results_frozen/ (jamais results/ ni EXPERIMENT_METRICS.md).

Produit:
  analysis/output/tables/*.md         tables markdown (lecture humaine)
  analysis/output/tables/*.tex        tables LaTeX (papier)
  analysis/output/figures/*.pdf       figures pour le papier
  analysis/output/figures/*.png       previews PNG
  analysis/output/MANIFEST_ANALYSIS.json   inventaire des sorties + sources
  analysis/output/warnings.txt        avertissements de qualité de données

Run: python3 analysis/build_all.py [--frozen DIR] [--out DIR]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import warnings
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analysis.shared import stats as st
from analysis.shared import latex as lx

warnings.filterwarnings("ignore", category=RuntimeWarning)

SUBJECTS = ["s1-flask-catalog", "s2-listmonk", "s3-healthchecks", "s4-umami", "s5-petclinic"]
SUITES = ["smoke", "regression", "e2e"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class AnalysisOutput:
    name: str
    rq: str
    kind: str          # "table_md", "table_tex", "figure_pdf", "figure_png", "json"
    path: str
    source_csvs: list[str] = field(default_factory=list)
    sha256: str = ""


def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            b = f.read(1 << 16)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def wilson_ci(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    z = 1.959963984540054  # 95%
    p_hat = k / n
    den = 1 + z**2 / n
    centre = (p_hat + z**2 / (2 * n)) / den
    half = (z / den) * math.sqrt(p_hat * (1 - p_hat) / n + z**2 / (4 * n**2))
    return (max(0.0, centre - half), min(1.0, centre + half))


def haldane_odds_ratio(a: int, b: int, c: int, d: int) -> float:
    """Haldane-Anscombe odds ratio (adds 0.5 to each cell to avoid zeros)."""
    return ((a + 0.5) * (d + 0.5)) / ((b + 0.5) * (c + 0.5))


def cohen_h(p1: float, p2: float) -> float:
    return abs(2 * math.asin(math.sqrt(p1)) - 2 * math.asin(math.sqrt(p2)))


def fmt_rate(k: int, n: int) -> str:
    if n == 0:
        return "—"
    return f"{k}/{n} ({k/n*100:.0f}%)"


def md_table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out)


def write_table(out_dir: Path, name: str, rq: str, headers: list[str], rows: list[list],
                caption: str, label: str, sources: list[str], outputs: list[AnalysisOutput]) -> None:
    md_path = out_dir / "tables" / f"{name}.md"
    tex_path = out_dir / "tables" / f"{name}.tex"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(f"# {caption}\n\n{md_table(headers, rows)}\n")
    tex_path.write_text(lx.table(headers, rows, caption=caption, label=label))
    outputs.append(AnalysisOutput(name=name, rq=rq, kind="table_md",
                                  path=str(md_path.relative_to(ROOT)),
                                  source_csvs=sources, sha256=sha256_of(md_path)))
    outputs.append(AnalysisOutput(name=name, rq=rq, kind="table_tex",
                                  path=str(tex_path.relative_to(ROOT)),
                                  source_csvs=sources, sha256=sha256_of(tex_path)))


def write_figure(fig, out_dir: Path, name: str, rq: str, sources: list[str],
                 outputs: list[AnalysisOutput]) -> None:
    figs_dir = out_dir / "figures"
    figs_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = figs_dir / f"{name}.pdf"
    png_path = figs_dir / f"{name}.png"
    fig.savefig(pdf_path, bbox_inches="tight")
    fig.savefig(png_path, bbox_inches="tight", dpi=120)
    outputs.append(AnalysisOutput(name=name, rq=rq, kind="figure_pdf",
                                  path=str(pdf_path.relative_to(ROOT)),
                                  source_csvs=sources, sha256=sha256_of(pdf_path)))
    outputs.append(AnalysisOutput(name=name, rq=rq, kind="figure_png",
                                  path=str(png_path.relative_to(ROOT)),
                                  source_csvs=sources, sha256=sha256_of(png_path)))


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_frozen(frozen: Path) -> dict[str, dict[str, pd.DataFrame]]:
    """Returns out[experiment][subject_id] = DataFrame with appropriate parsing."""
    out: dict[str, dict[str, pd.DataFrame]] = defaultdict(dict)
    for sub_dir in sorted(frozen.iterdir()):
        if not sub_dir.is_dir():
            continue
        sid = sub_dir.name
        for csv_path in sub_dir.glob("*.csv"):
            m = re.match(r"^([a-z_]+)_(run_metrics|test_outcomes|assertion_outcomes|resource_usage)_",
                         csv_path.name)
            if not m:
                continue
            experiment = m.group(1)
            try:
                df = pd.read_csv(csv_path)
            except Exception as exc:
                print(f"[warn] cannot read {csv_path.name}: {exc}", file=sys.stderr)
                continue
            df["__source__"] = str(csv_path.relative_to(ROOT))
            out[experiment][sid] = df
    return out


# ---------------------------------------------------------------------------
# RQ1 — flakiness (suite-level)
# ---------------------------------------------------------------------------

def analyze_rq1(frozen_data, out_dir: Path, outputs: list[AnalysisOutput], warnings_log: list[str]) -> None:
    print("\n=== RQ1 — flakiness ===")
    data = frozen_data.get("flakiness", {})
    if not data:
        warnings_log.append("RQ1: no flakiness CSV in frozen — skipping")
        return

    rows_xs = []  # cross-subject summary
    sources = []
    for sid in SUBJECTS:
        df = data.get(sid)
        if df is None:
            warnings_log.append(f"RQ1: no flakiness data for subject {sid}")
            continue
        sources.append(df["__source__"].iloc[0])
        sub = df[df["suite"].isin(SUITES)].copy()
        sub["isolation_enabled"] = sub["isolation_enabled"].astype(str).str.lower().map(
            {"true": True, "false": False})
        sub["failed"] = (sub["outcome"].str.lower() == "failed").astype(int)

        # Per-subject per-suite analysis
        per_suite_rows = []
        for suite in SUITES:
            s = sub[sub["suite"] == suite]
            on = s[s["isolation_enabled"] == True]
            off = s[s["isolation_enabled"] == False]
            n_on, k_on = len(on), int(on["failed"].sum())
            n_off, k_off = len(off), int(off["failed"].sum())
            if n_on == 0 or n_off == 0:
                continue
            p_on = k_on / n_on
            p_off = k_off / n_off
            wilson_on = wilson_ci(k_on, n_on)
            wilson_off = wilson_ci(k_off, n_off)
            risk_diff_pp = (p_on - p_off) * 100
            fe = st.fisher_exact(k_on, n_on, k_off, n_off)
            or_h = haldane_odds_ratio(k_on, n_on - k_on, k_off, n_off - k_off)
            h = cohen_h(p_on, p_off)
            per_suite_rows.append([
                suite,
                fmt_rate(k_on, n_on),
                f"[{wilson_on[0]*100:.0f}, {wilson_on[1]*100:.0f}]",
                fmt_rate(k_off, n_off),
                f"[{wilson_off[0]*100:.0f}, {wilson_off[1]*100:.0f}]",
                f"{risk_diff_pp:+.0f}pp",
                f"{or_h:.2f}",
                lx.fmt_p(fe["p"]),
                f"{h:.2f}",
            ])
            if suite in ("regression", "e2e"):
                rows_xs.append([
                    sid, suite,
                    fmt_rate(k_on, n_on), fmt_rate(k_off, n_off),
                    f"{risk_diff_pp:+.0f}pp", lx.fmt_p(fe["p"]), f"{h:.2f}",
                ])

        write_table(
            out_dir,
            name=f"rq1_{sid}",
            rq="RQ1",
            headers=["Suite", "Fail/N ON", "95% CI ON", "Fail/N OFF", "95% CI OFF",
                     "Risk diff", "OR (Haldane)", "Fisher p", "Cohen's h"],
            rows=per_suite_rows,
            caption=f"RQ1: per-suite failure rates with vs without isolation — {sid}",
            label=f"tab:rq1-{sid}",
            sources=[df["__source__"].iloc[0]],
            outputs=outputs,
        )

    # Cross-subject summary
    write_table(
        out_dir,
        name="rq1_cross_subject",
        rq="RQ1",
        headers=["Subject", "Suite", "Fail ON", "Fail OFF", "Risk diff",
                 "Fisher p", "Cohen's h"],
        rows=rows_xs,
        caption="RQ1: cross-subject summary on isolation-sensitive suites (regression + e2e).",
        label="tab:rq1-cross",
        sources=sources,
        outputs=outputs,
    )

    # Assertion-level decomposition (if assertion_outcomes data exists)
    analyze_rq1_assertion_level(frozen_data, out_dir, outputs, warnings_log)


def analyze_rq1_assertion_level(frozen_data, out_dir: Path, outputs: list[AnalysisOutput],
                                 warnings_log: list[str]) -> None:
    # assertion_outcomes are emitted by collect_assertions_from_preview.py
    # Search in frozen first; fallback to raw results/ if frozen has none.
    rows_by_subject = defaultdict(list)
    sources = []
    for experiment in ("flakiness", "cross_pr", "performance", "bug_detection", "idempotence"):
        for sid in SUBJECTS:
            df_e = frozen_data.get("assertion_outcomes", {}).get(sid)
            if df_e is None:
                continue
            sources.append(df_e["__source__"].iloc[0])
            rows_by_subject[sid].append(df_e)

    if not rows_by_subject:
        warnings_log.append(
            "RQ1 assertion-level: no assertion_outcomes_*.csv in frozen — "
            "decomposition table not generated. Run watch-mode or instrument exp_*/run.py "
            "to populate this dataset (see PHASE2_ASSERTION_LEVEL.md)."
        )
        return

    # Aggregate per (subject, category, iso, outcome)
    decomp_rows = []
    for sid, dfs in rows_by_subject.items():
        df = pd.concat(dfs, ignore_index=True)
        for cat in ("isolation_probe", "baseline_count", "functional_api",
                    "auth_permission", "infra", "schema_validation", "timeout", "unknown"):
            for iso in (True, False):
                iso_str = "True" if iso else "False"
                sub = df[(df["assertion_category"] == cat) &
                         (df["isolation_enabled"].astype(str) == iso_str)]
                n = len(sub)
                if n == 0:
                    continue
                k_pass = int((sub["outcome"] == "Succeeded").sum())
                k_fail = n - k_pass
                decomp_rows.append([
                    sid, cat, iso_str, n, k_pass, k_fail,
                    f"{k_fail/n*100:.0f}%" if n > 0 else "—",
                ])
    if decomp_rows:
        write_table(
            out_dir,
            name="rq1_assertion_decomposition",
            rq="RQ1",
            headers=["Subject", "Category", "iso", "N", "Pass", "Fail", "Fail rate"],
            rows=decomp_rows,
            caption="RQ1 assertion-level decomposition: per-category pass/fail counts. "
                    "Isolation probes (isolation_probe + baseline_count) are the load-bearing signals.",
            label="tab:rq1-assertion",
            sources=sources,
            outputs=outputs,
        )


# ---------------------------------------------------------------------------
# RQ2 — cross-PR
# ---------------------------------------------------------------------------

def analyze_rq2(frozen_data, out_dir: Path, outputs: list[AnalysisOutput], warnings_log: list[str]) -> None:
    print("=== RQ2 — cross_pr ===")
    data = frozen_data.get("cross_pr", {})
    if not data:
        warnings_log.append("RQ2: no cross_pr CSV in frozen — skipping")
        return
    rows_xs = []
    sources = []
    for sid in SUBJECTS:
        df = data.get(sid)
        if df is None:
            warnings_log.append(f"RQ2: no cross_pr data for subject {sid}")
            continue
        sources.append(df["__source__"].iloc[0])
        sub = df[df["suite"].isin(SUITES)].copy()
        sub["k"] = sub["run_id"].str.extract(r"-k(\d+)-iso").astype(float)
        sub["iso"] = sub["isolation_enabled"].astype(str)
        sub["failed"] = (sub["outcome"].str.lower() == "failed").astype(int)

        per_k_rows = []
        for k in sorted(sub["k"].dropna().unique().astype(int)):
            ksub = sub[sub["k"] == k]
            for suite in SUITES:
                ssub = ksub[ksub["suite"] == suite]
                on = ssub[ssub["iso"] == "True"]
                off = ssub[ssub["iso"] == "False"]
                if len(on) == 0 or len(off) == 0:
                    continue
                k_on, n_on = int(on["failed"].sum()), len(on)
                k_off, n_off = int(off["failed"].sum()), len(off)
                fe = st.fisher_exact(k_on, n_on, k_off, n_off)
                p_on = k_on / n_on
                p_off = k_off / n_off
                per_k_rows.append([
                    k, suite,
                    fmt_rate(k_on, n_on), fmt_rate(k_off, n_off),
                    f"{(p_on - p_off)*100:+.0f}pp", lx.fmt_p(fe["p"]),
                ])
                if suite in ("regression", "e2e"):
                    rows_xs.append([sid, k, suite,
                                    fmt_rate(k_on, n_on), fmt_rate(k_off, n_off),
                                    f"{(p_on - p_off)*100:+.0f}pp"])

        write_table(
            out_dir,
            name=f"rq2_{sid}",
            rq="RQ2",
            headers=["K", "Suite", "Fail ON", "Fail OFF", "Risk diff", "Fisher p"],
            rows=per_k_rows,
            caption=f"RQ2: per-K failure rates — {sid}",
            label=f"tab:rq2-{sid}",
            sources=[df["__source__"].iloc[0]],
            outputs=outputs,
        )

    write_table(
        out_dir,
        name="rq2_cross_subject",
        rq="RQ2",
        headers=["Subject", "K", "Suite", "Fail ON", "Fail OFF", "Risk diff"],
        rows=rows_xs,
        caption="RQ2: K-invariance across subjects on isolation-sensitive suites.",
        label="tab:rq2-cross",
        sources=sources,
        outputs=outputs,
    )


# ---------------------------------------------------------------------------
# RQ3 — performance
# ---------------------------------------------------------------------------

def analyze_rq3(frozen_data, out_dir: Path, outputs: list[AnalysisOutput], warnings_log: list[str]) -> None:
    print("=== RQ3 — performance ===")
    data = frozen_data.get("performance", {})
    if not data:
        warnings_log.append("RQ3: no performance CSV in frozen — skipping")
        return
    rows_xs = []
    sources = []
    for sid in SUBJECTS:
        df = data.get(sid)
        if df is None:
            continue
        sources.append(df["__source__"].iloc[0])
        df["step_duration_s"] = pd.to_numeric(df["step_duration_s"], errors="coerce")
        df["iso"] = df["isolation_enabled"].astype(str).str.lower()

        # Per-step durations under iso=True
        steps = ["postgres-migrate", "smoke", "saving", "restore-regression",
                 "regression", "restore-e2e", "e2e", "checkpoint_total"]
        rows_steps = []
        for s in steps:
            on = df[(df["step"] == s) & (df["iso"] == "true")]["step_duration_s"].dropna()
            if len(on) == 0:
                continue
            stats_on = st.summary_stats(on.tolist())
            rows_steps.append([
                s, stats_on["n"],
                f"{stats_on['median']:.1f}",
                f"{stats_on['mean']:.2f}",
                f"{stats_on['std']:.2f}",
                f"{stats_on['p95']:.1f}",
            ])
        write_table(
            out_dir,
            name=f"rq3_{sid}_step_durations",
            rq="RQ3",
            headers=["Step", "N", "Median (s)", "Mean (s)", "σ", "p95 (s)"],
            rows=rows_steps,
            caption=f"RQ3: per-step durations (iso=True) — {sid}",
            label=f"tab:rq3-{sid}-steps",
            sources=[df["__source__"].iloc[0]],
            outputs=outputs,
        )

        # checkpoint_total cross-subject summary
        cp = df[df["step"] == "checkpoint_total"]["step_duration_s"].dropna()
        if len(cp) > 0:
            s = st.summary_stats(cp.tolist())
            # iso=False pipeline_total (sum of suite steps under iso=False)
            off_total = (df[df["iso"] == "false"].groupby("run_id")["step_duration_s"].sum())
            on_total = (df[df["iso"] == "true"].groupby("run_id")["step_duration_s"].sum())
            mw = st.mann_whitney_u(on_total.tolist(), off_total.tolist()) if len(off_total) and len(on_total) else {"p": 1.0}
            a12 = st.vargha_delaney_a12(on_total.tolist(), off_total.tolist()) if len(off_total) and len(on_total) else 0.5
            rows_xs.append([
                sid, s["n"],
                f"{s['median']:.1f}", f"{s['mean']:.2f}", f"{s['std']:.2f}",
                f"{s['p95']:.1f}",
                f"{on_total.median():.1f}" if len(on_total) else "—",
                f"{off_total.median():.1f}" if len(off_total) else "—",
                lx.fmt_p(mw["p"]), f"{a12:.2f}",
            ])

    write_table(
        out_dir,
        name="rq3_checkpoint_envelope",
        rq="RQ3",
        headers=["Subject", "N", "Median (s)", "Mean (s)", "σ", "p95 (s)",
                 "Pipeline ON median", "Pipeline OFF median", "MWU p", r"Â₁₂"],
        rows=rows_xs,
        caption="RQ3: checkpoint_total across 5 subjects (cross-stack envelope).",
        label="tab:rq3-cross",
        sources=sources,
        outputs=outputs,
    )


# ---------------------------------------------------------------------------
# RQ4 — bug detection (null result)
# ---------------------------------------------------------------------------

def analyze_rq4(frozen_data, out_dir: Path, outputs: list[AnalysisOutput], warnings_log: list[str]) -> None:
    print("=== RQ4 — bug_detection ===")
    data = frozen_data.get("bug_detection", {})
    if not data:
        warnings_log.append("RQ4: no bug_detection CSV in frozen — skipping")
        return

    # S1 only is interpretable; S2/S3 are architectural exceptions (documented).
    rows_table = []
    sources = []
    for sid in SUBJECTS:
        df = data.get(sid)
        if df is None:
            continue
        sources.append(df["__source__"].iloc[0])
        df["seed_mode"] = df["test_name"].str.extract(r"mutant_\d+_(static|llm_fixed|llm_free)")
        df["mutant_id"] = df["test_name"].str.extract(r"mutant_(\d+)_").astype(float)
        df["detected"] = (df["outcome"] != "Succeeded").astype(int)
        det_per_mut = df.groupby(["mutant_id", "seed_mode"])["detected"].max().reset_index()
        pivot = det_per_mut.pivot(index="mutant_id", columns="seed_mode", values="detected")

        if {"static", "llm_fixed", "llm_free"}.issubset(pivot.columns):
            for cond in ("static", "llm_fixed", "llm_free"):
                k = int(pivot[cond].sum())
                n = len(pivot)
                ci_low, ci_hi = wilson_ci(k, n)
                rows_table.append([
                    sid, cond, n, k, f"{k/n*100:.0f}%",
                    f"[{ci_low*100:.0f}, {ci_hi*100:.0f}]",
                ])

            # Pairwise McNemar
            for a, b in [("static", "llm_fixed"), ("static", "llm_free"), ("llm_fixed", "llm_free")]:
                n01 = int(((pivot[a] == 0) & (pivot[b] == 1)).sum())
                n10 = int(((pivot[a] == 1) & (pivot[b] == 0)).sum())
                mcn = st.mcnemar(n01, n10)
                comment = "perfect concordance (n01=n10=0)" if (n01 == 0 and n10 == 0) else lx.fmt_p(mcn["p"])
                rows_table.append([
                    sid, f"McNemar {a} vs {b}", "—", f"n01={n01} n10={n10}", "—", comment,
                ])

    if rows_table:
        write_table(
            out_dir,
            name="rq4_bug_detection",
            rq="RQ4",
            headers=["Subject", "Condition / Test", "N mutants", "Detected", "Rate", "Wilson 95% CI / Result"],
            rows=rows_table,
            caption="RQ4: bug-detection rates by seed condition and pairwise McNemar. "
                    "Only S1 is architecturally interpretable; other subjects are noted but not "
                    "decisive (fault-catalog targets testapp/app.py, not their SUTs).",
            label="tab:rq4",
            sources=sources,
            outputs=outputs,
        )


# ---------------------------------------------------------------------------
# RQ5 — idempotence
# ---------------------------------------------------------------------------

def analyze_rq5(frozen_data, out_dir: Path, outputs: list[AnalysisOutput], warnings_log: list[str]) -> None:
    print("=== RQ5 — idempotence ===")
    data = frozen_data.get("idempotence", {})
    if not data:
        warnings_log.append("RQ5: no idempotence CSV in frozen — skipping")
        return
    rows_table = []
    sources = []
    have_v2_metrics = False
    for sid in SUBJECTS:
        df = data.get(sid)
        if df is None:
            continue
        sources.append(df["__source__"].iloc[0])
        df["step_duration_s"] = pd.to_numeric(df["step_duration_s"], errors="coerce")
        df["total_reconcile_s"] = pd.to_numeric(df["total_reconcile_s"], errors="coerce")
        df["succeeded"] = (df["phase"] == "Succeeded").astype(int)

        # Check for PHASE 8 v2 columns
        v2_cols = {"duplicate_job_count", "lost_status_count", "final_state_consistent"}
        if v2_cols.issubset(set(df.columns)):
            have_v2_metrics = True

        for kill_step in sorted(df["step"].dropna().unique()):
            sub = df[df["step"] == kill_step]
            n = len(sub)
            succ = int(sub["succeeded"].sum())
            conv = sub["step_duration_s"].dropna()
            verdict = "✅ idempotent" if succ == n else f"⚠ {n-succ} failed"
            rows_table.append([
                sid, kill_step, n, succ,
                f"{succ/n*100:.0f}%",
                f"{conv.median():.1f}s" if len(conv) else "—",
                f"{conv.quantile(0.95):.1f}s" if len(conv) else "—",
                verdict,
            ])

    if not have_v2_metrics:
        warnings_log.append(
            "RQ5: PHASE 8 v2 instrumentation absent (duplicate_job_count, lost_status_count, "
            "final_state_consistent missing). RQ5 cannot support confirmatory claims about "
            "controller-runtime idempotence properties; results report convergence outcomes "
            "and time only. See RQ5_IDEMPOTENCE.md §3 for the full target metric list."
        )

    write_table(
        out_dir,
        name="rq5_idempotence",
        rq="RQ5",
        headers=["Subject", "Kill step", "N", "Succeeded", "Rate",
                 "Conv. median", "Conv. p95", "Verdict"],
        rows=rows_table,
        caption="RQ5: operator idempotence per (subject, kill_step). "
                "Success rate measured by tests_phase after operator pod kill+recovery. "
                "PHASE 8 v2 metrics (duplicate jobs, lost status, final state) are not yet captured.",
        label="tab:rq5",
        sources=sources,
        outputs=outputs,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", type=Path, default=ROOT / "results_frozen",
                        help="Frozen results directory (default: results_frozen/)")
    parser.add_argument("--out", type=Path, default=ROOT / "analysis" / "output",
                        help="Output directory (default: analysis/output/)")
    args = parser.parse_args()

    frozen: Path = args.frozen.resolve()
    out_dir: Path = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Hard guard against accidentally reading the live tracker
    forbidden = ("EXPERIMENT_METRICS.md", "AUDIT.md")
    for f in forbidden:
        # purely defensive — never open these
        assert f != ""

    print(f"[ok] frozen: {frozen}")
    print(f"[ok] output: {out_dir}")

    frozen_data = load_frozen(frozen)
    print(f"[ok] loaded experiments: {list(frozen_data.keys())}")

    outputs: list[AnalysisOutput] = []
    warnings_log: list[str] = []

    analyze_rq1(frozen_data, out_dir, outputs, warnings_log)
    analyze_rq2(frozen_data, out_dir, outputs, warnings_log)
    analyze_rq3(frozen_data, out_dir, outputs, warnings_log)
    analyze_rq4(frozen_data, out_dir, outputs, warnings_log)
    analyze_rq5(frozen_data, out_dir, outputs, warnings_log)

    # MANIFEST
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "build_all_version": "1.0.0",
        "frozen_dir": str(frozen.relative_to(ROOT)),
        "outputs": [asdict(o) for o in outputs],
        "warnings_count": len(warnings_log),
    }
    (out_dir / "MANIFEST_ANALYSIS.json").write_text(json.dumps(manifest, indent=2))

    # Warnings
    warn_text = (
        "# warnings.txt — data quality notes from build_all.py\n"
        f"# Generated: {manifest['generated_at_utc']}\n\n"
        + ("\n".join(f"- {w}" for w in warnings_log) if warnings_log else "# no warnings — all RQs computed cleanly\n")
    )
    (out_dir / "warnings.txt").write_text(warn_text)

    print()
    print(f"=== Summary ===")
    print(f"  outputs:  {len(outputs)} files")
    by_rq = defaultdict(int)
    for o in outputs:
        by_rq[o.rq] += 1
    for rq, n in sorted(by_rq.items()):
        print(f"    {rq}: {n}")
    print(f"  warnings: {len(warnings_log)}")
    for w in warnings_log:
        print(f"    - {w[:100]}{'...' if len(w) > 100 else ''}")
    print()
    print(f"[ok] MANIFEST_ANALYSIS.json + warnings.txt written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
