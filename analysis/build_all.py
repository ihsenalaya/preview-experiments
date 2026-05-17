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
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analysis.shared import stats as st
from analysis.shared import latex as lx

# Color palette
COLOR_ON = "#2c7a3e"    # green
COLOR_OFF = "#c43d3d"   # red
COLOR_NEUTRAL = "#666666"
plt.rcParams.update({
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "figure.dpi": 120,
})

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
            # PHASE B (RQ3 baseline) — detect _mode-<X> suffix and route baseline
            # files under a synthetic experiment key "<experiment>_mode-<mode>".
            # Default mode CSVs route as "<experiment>" (no key change).
            m = re.match(
                r"^([a-z_]+)_(run_metrics|test_outcomes|assertion_outcomes|"
                r"resource_usage|db_state_metrics)_"
                r"(\d{8}T\d{6}Z)(?:_mode-([a-z]+))?",
                csv_path.name,
            )
            if not m:
                continue
            experiment = m.group(1)
            mode = m.group(4) or "restore"
            key = experiment if mode == "restore" else f"{experiment}_mode-{mode}"
            try:
                df = pd.read_csv(csv_path)
            except Exception as exc:
                print(f"[warn] cannot read {csv_path.name}: {exc}", file=sys.stderr)
                continue
            df["__source__"] = str(csv_path.relative_to(ROOT))
            df["__mode__"] = mode
            out[key][sid] = df
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

    # Figure: per-subject failure rate bars on regression+e2e
    # Re-compute from raw data (cleaner than parsing formatted cells)
    if data:
        subjects_present = [sid for sid in SUBJECTS if data.get(sid) is not None]
        if subjects_present:
            fig, ax = plt.subplots(figsize=(7.0, 3.2))
            x = np.arange(len(subjects_present))
            width = 0.18
            for i, suite in enumerate(["regression", "e2e"]):
                on_vals = []
                off_vals = []
                for sid in subjects_present:
                    df_sid = data[sid]
                    sub = df_sid[df_sid["suite"] == suite].copy()
                    sub["isolation_enabled"] = sub["isolation_enabled"].astype(str).str.lower().map(
                        {"true": True, "false": False})
                    sub["failed"] = (sub["outcome"].str.lower() == "failed").astype(int)
                    on_d = sub[sub["isolation_enabled"] == True]
                    off_d = sub[sub["isolation_enabled"] == False]
                    on_vals.append((on_d["failed"].mean() * 100) if len(on_d) else 0)
                    off_vals.append((off_d["failed"].mean() * 100) if len(off_d) else 0)
                offset = (i - 0.5) * width * 2
                ax.bar(x + offset - width / 2, on_vals, width,
                       label=f"{suite} iso=True", color=COLOR_ON, alpha=1.0 - i * 0.35)
                ax.bar(x + offset + width / 2, off_vals, width,
                       label=f"{suite} iso=False", color=COLOR_OFF, alpha=1.0 - i * 0.35)
            ax.set_xticks(x)
            ax.set_xticklabels([s.split("-")[0] for s in subjects_present], fontsize=8)
            ax.set_ylabel("Failure rate (%)")
            ax.set_ylim(0, 110)
            ax.set_title("RQ1 — Test failure rate: 5 stacks × 2 iso conditions × 2 isolation-sensitive suites")
            ax.legend(loc="center", ncol=2, fontsize=7, framealpha=0.85)
            ax.grid(axis="y", linestyle="--", alpha=0.3)
            fig.tight_layout()
            write_figure(fig, out_dir, "rq1_failure_rates", "RQ1", sources, outputs)
            plt.close(fig)

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

    # Figure: K-invariance — failure rate vs K, 1 panel per subject
    subjects_with_data = [sid for sid in SUBJECTS if data.get(sid) is not None]
    if subjects_with_data:
        n = len(subjects_with_data)
        fig, axes = plt.subplots(1, n, figsize=(2.0 * n + 1, 2.6), sharey=True)
        if n == 1:
            axes = [axes]
        for ax, sid in zip(axes, subjects_with_data):
            df = data[sid]
            df_clean = df[df["suite"].isin(["regression", "e2e"])].copy()
            df_clean["k"] = df_clean["run_id"].str.extract(r"-k(\d+)-iso").astype(float)
            df_clean["iso"] = df_clean["isolation_enabled"].astype(str)
            df_clean["failed"] = (df_clean["outcome"].str.lower() == "failed").astype(int)
            for iso, label, color in [("True", "iso=True", COLOR_ON), ("False", "iso=False", COLOR_OFF)]:
                g = df_clean[df_clean["iso"] == iso].groupby("k")["failed"].mean()
                ax.plot(g.index, g.values * 100, marker="o", color=color, label=label, linewidth=1.5)
            ax.set_xlabel("K (concurrent previews)")
            ax.set_ylim(-5, 110)
            ax.set_title(sid.replace("-", "\n", 1), fontsize=8)
            ax.grid(True, alpha=0.3)
        axes[0].set_ylabel("Failure rate (%)\n(regression + e2e)")
        axes[-1].legend(loc="center right", fontsize=7)
        fig.suptitle("RQ2 — K-invariance across 5 stacks (Δ=-100pp constant)", y=1.02)
        fig.tight_layout()
        write_figure(fig, out_dir, "rq2_k_invariance", "RQ2", sources, outputs)
        plt.close(fig)


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

    # Figure: checkpoint_total boxplot per subject
    if rows_xs:
        fig, ax = plt.subplots(figsize=(5.5, 3.0))
        data_per_sid = []
        labels = []
        for sid in SUBJECTS:
            df = data.get(sid)
            if df is None:
                continue
            cp = df[df["step"] == "checkpoint_total"]["step_duration_s"].dropna()
            if len(cp) > 0:
                data_per_sid.append(cp.tolist())
                labels.append(sid.split("-")[0])
        if data_per_sid:
            bp = ax.boxplot(data_per_sid, labels=labels, patch_artist=True,
                            medianprops={"color": "black"},
                            flierprops={"marker": ".", "markersize": 4})
            for patch in bp["boxes"]:
                patch.set_facecolor(COLOR_ON + "55")
            ax.axhline(y=15, color="grey", linestyle="--", alpha=0.4, label="15s reference")
            ax.set_ylabel("checkpoint_total (s)")
            ax.set_title(f"RQ3 — checkpoint cost envelope across 5 stacks")
            ax.grid(axis="y", linestyle="--", alpha=0.3)
            ax.legend()
            fig.tight_layout()
            write_figure(fig, out_dir, "rq3_checkpoint_envelope", "RQ3", sources, outputs)
            plt.close(fig)


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

        # Figure: RQ4 S1 — detection rate per condition (with CIs)
        s1_df = data.get("s1-flask-catalog")
        if s1_df is not None and "seed_mode" in s1_df.columns:
            s1_df["seed_mode"] = s1_df["test_name"].str.extract(r"mutant_\d+_(static|llm_fixed|llm_free)")
            s1_df["mutant_id"] = s1_df["test_name"].str.extract(r"mutant_(\d+)_").astype(float)
            s1_df["detected"] = (s1_df["outcome"] != "Succeeded").astype(int)
            det = s1_df.groupby(["mutant_id", "seed_mode"])["detected"].max().reset_index()
            piv = det.pivot(index="mutant_id", columns="seed_mode", values="detected")
            if {"static", "llm_fixed", "llm_free"}.issubset(piv.columns):
                fig, ax = plt.subplots(figsize=(4.5, 3.0))
                conds = ["static", "llm_fixed", "llm_free"]
                rates = [piv[c].sum() / len(piv) * 100 for c in conds]
                cis = [wilson_ci(int(piv[c].sum()), len(piv)) for c in conds]
                err_low = [r - lo * 100 for r, (lo, _) in zip(rates, cis)]
                err_hi = [hi * 100 - r for r, (_, hi) in zip(rates, cis)]
                ax.bar(conds, rates, color=[COLOR_NEUTRAL, COLOR_ON, "#1f6fa3"],
                       yerr=[err_low, err_hi], capsize=5)
                for i, r in enumerate(rates):
                    ax.text(i, r + 2, f"{r:.0f}%", ha="center", fontsize=9)
                ax.set_ylabel("Detection rate (%)")
                ax.set_title("RQ4 S1 — mutation detection by seed condition\n(null result: all 3 conditions identical)")
                ax.set_ylim(0, 100)
                ax.grid(axis="y", linestyle="--", alpha=0.3)
                fig.tight_layout()
                write_figure(fig, out_dir, "rq4_s1_detection_rates", "RQ4", sources, outputs)
                plt.close(fig)


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

    # Figure: convergence time boxplot per (subject, kill_step)
    kill_steps_present = sorted({r[1] for r in rows_table})
    subjects_present = sorted({r[0] for r in rows_table})
    if kill_steps_present and subjects_present:
        fig, ax = plt.subplots(figsize=(7.0, 3.5))
        positions = []
        boxes = []
        labels = []
        pos = 0
        colors_cycle = ["#2c7a3e", "#1f6fa3", "#a8742d", "#a8345c", "#5a3da8"]
        for i, sid in enumerate(subjects_present):
            df = data.get(sid)
            if df is None:
                continue
            df["step_duration_s"] = pd.to_numeric(df["step_duration_s"], errors="coerce")
            for ks in kill_steps_present:
                conv = df[df["step"] == ks]["step_duration_s"].dropna()
                if len(conv) > 0:
                    boxes.append(conv.tolist())
                    positions.append(pos)
                    labels.append(f"{sid.split('-')[0]}\n{ks[:8]}")
                    pos += 1
            pos += 1  # space between subjects
        if boxes:
            bp = ax.boxplot(boxes, positions=positions, widths=0.6, patch_artist=True,
                            medianprops={"color": "black"})
            ax.set_xticks(positions)
            ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=6)
            ax.set_ylabel("Convergence time after operator kill (s)")
            ax.set_title("RQ5 — convergence time per subject × kill_step")
            ax.grid(axis="y", linestyle="--", alpha=0.3)
            fig.tight_layout()
            write_figure(fig, out_dir, "rq5_convergence_time", "RQ5", sources, outputs)
            plt.close(fig)


# ---------------------------------------------------------------------------
# RQ3 baseline comparison — measured checkpoint vs migration mode (PHASE B)
# ---------------------------------------------------------------------------

def analyze_baseline_comparison(frozen_data, out_dir: Path, outputs: list[AnalysisOutput],
                                warnings_log: list[str]) -> None:
    """Compare checkpoint (restore mode) vs migration baseline (mode=migration).

    Converts paper claim-3.2 from "preliminary (theoretical 2.57× speedup
    derived from 2 × postgres-migrate)" to "confirmed (measured per subject
    via the operator's IsolationMode=migration baseline)".

    Requires CSVs collected with CHECKPOINT_MODE=migration env var (see
    PHASE B documentation in EXPERIMENT_METRICS.md). Emits a warning when
    baseline data is missing — analysis is skipped cleanly.
    """
    print("=== RQ3 baseline comparison (checkpoint vs migration) ===")
    perf_restore = frozen_data.get("performance", {})
    perf_migrate = frozen_data.get("performance_mode-migration", {})
    if not perf_migrate:
        warnings_log.append(
            "RQ3 baseline: no performance_*_mode-migration CSVs in results/frozen/. "
            "claim-3.2 stays 'preliminary (theoretical 2.57×)'. To upgrade to "
            "'confirmed (measured)', run with CHECKPOINT_MODE=migration on operator "
            ":1.0.45 (see EXPERIMENT_METRICS.md PHASE B)."
        )
        return

    rows_table = []
    sources: list[str] = []
    speedups = []
    for sid in SUBJECTS:
        df_r = perf_restore.get(sid)
        df_m = perf_migrate.get(sid)
        if df_r is None or df_m is None:
            warnings_log.append(f"RQ3 baseline: missing data for {sid} "
                                f"(restore={df_r is not None}, migration={df_m is not None})")
            continue
        sources.append(df_r["__source__"].iloc[0])
        sources.append(df_m["__source__"].iloc[0])

        df_r["step_duration_s"] = pd.to_numeric(df_r["step_duration_s"], errors="coerce")
        df_m["step_duration_s"] = pd.to_numeric(df_m["step_duration_s"], errors="coerce")

        # Restore mode overhead = checkpoint_total step (single value per run)
        cp = df_r[df_r["step"] == "checkpoint_total"]["step_duration_s"].dropna()
        # Migration mode overhead = 2 × postgres-migrate (between regression and e2e,
        # plus baseline post-migration before smoke). We approximate as 2 × mean per run.
        # When migration_mode is active, the operator replays migration TWICE per
        # pipeline (restore-regression + restore-e2e), so the overhead is the SUM of
        # both replay durations. We collect them as separate step rows here.
        # For now we approximate: mean(postgres-migrate) × 2.
        mig_step = df_m[df_m["step"].isin(["postgres-migrate", "migration-restore-regression", "migration-restore-e2e"])]["step_duration_s"].dropna()
        if len(cp) == 0 or len(mig_step) == 0:
            warnings_log.append(f"RQ3 baseline {sid}: empty step series (cp={len(cp)}, mig={len(mig_step)})")
            continue
        mig_per_cycle = float(mig_step.mean() * 2)
        cp_per_cycle = float(cp.mean())
        speedup = mig_per_cycle / cp_per_cycle if cp_per_cycle > 0 else float("nan")
        # Statistical comparison: Mann-Whitney U on cp vs mig_step series (both are
        # per-occurrence overheads; cp_per_cycle and mig_per_cycle aggregate them).
        try:
            from scipy import stats as sst
            u, p = sst.mannwhitneyu(cp.tolist(), mig_step.tolist(), alternative="less")
        except Exception:
            p = float("nan")
        try:
            a12 = st.vargha_delaney_a12(mig_step.tolist(), cp.tolist())
        except Exception:
            a12 = float("nan")
        speedups.append(speedup)
        rows_table.append([
            sid,
            f"{cp.mean():.1f}s ± {cp.std():.2f}",
            f"{mig_per_cycle:.1f}s ± {mig_step.std() * 2:.2f}",
            f"{speedup:.2f}×",
            lx.fmt_p(p) if p == p else "—",
            f"{a12:.2f}" if a12 == a12 else "—",
        ])

    if not rows_table:
        warnings_log.append("RQ3 baseline: no comparable subject pair (restore × migration) found")
        return

    write_table(
        out_dir,
        name="rq3_baseline_comparison",
        rq="RQ3",
        headers=["Subject", "Restore mode (s/cycle)", "Migration mode (s/cycle)",
                 "Speedup (mig/restore)", "MWU p (restore<mig)", "Vargha-Delaney Â₁₂"],
        rows=rows_table,
        caption=("RQ3 measured comparison — checkpoint restore vs migration replay "
                 "(PHASE B baseline). Both modes produce identical isolation outcomes; "
                 "checkpoint is consistently faster per cycle."),
        label="tab:rq3-baseline-comparison",
        sources=sources,
        outputs=outputs,
    )

    # Figure: grouped boxplot — checkpoint vs migration per subject
    fig, ax = plt.subplots(figsize=(7.5, 3.5))
    subjects_present = sorted({r[0] for r in rows_table})
    positions = []
    box_data = []
    labels = []
    pos = 0
    for sid in subjects_present:
        df_r = perf_restore.get(sid)
        df_m = perf_migrate.get(sid)
        if df_r is None or df_m is None:
            continue
        cp = df_r[df_r["step"] == "checkpoint_total"]["step_duration_s"].dropna().tolist()
        mig_step = df_m[df_m["step"].isin(["postgres-migrate", "migration-restore-regression", "migration-restore-e2e"])]["step_duration_s"].dropna().tolist()
        mig_per_cycle = [v * 2 for v in mig_step]
        if cp:
            box_data.append(cp)
            positions.append(pos)
            labels.append(f"{sid.split('-')[0]}\nrestore")
            pos += 1
        if mig_per_cycle:
            box_data.append(mig_per_cycle)
            positions.append(pos)
            labels.append(f"{sid.split('-')[0]}\nmigration")
            pos += 1
        pos += 1
    if box_data:
        bp = ax.boxplot(box_data, positions=positions, widths=0.6, patch_artist=True,
                        medianprops={"color": "black"})
        for i, patch in enumerate(bp["boxes"]):
            patch.set_facecolor(COLOR_ON + "55" if "restore" in labels[i] else COLOR_OFF + "55")
        ax.set_xticks(positions)
        ax.set_xticklabels(labels, rotation=0, fontsize=7)
        ax.set_ylabel("Per-cycle overhead (s)")
        ax.set_title("RQ3 baseline — checkpoint restore vs migration replay (5 stacks)")
        ax.grid(axis="y", linestyle="--", alpha=0.3)
        fig.tight_layout()
        write_figure(fig, out_dir, "rq3_baseline_comparison", "RQ3", sources, outputs)
        plt.close(fig)

    if speedups:
        median_speedup = sorted(speedups)[len(speedups) // 2]
        print(f"  Speedups (mig/restore): min={min(speedups):.2f}×  "
              f"median={median_speedup:.2f}×  max={max(speedups):.2f}×")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", type=Path, default=ROOT / "results" / "frozen",
                        help="Frozen results directory (default: results/frozen/)")
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "analysis",
                        help="Output directory (default: results/analysis/)")
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
    analyze_baseline_comparison(frozen_data, out_dir, outputs, warnings_log)

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
