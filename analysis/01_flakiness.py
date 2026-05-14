# ---
# jupyter:
#   jupytext:
#     formats: py:percent,ipynb
# ---

# %% [markdown]
# # RQ1 — Does checkpoint isolation reduce test flakiness?

# %%
import pathlib
import pandas as pd
import matplotlib.pyplot as plt
import sys

sys.path.insert(0, str(pathlib.Path("..").resolve()))
from analysis.shared import stats, plotting, latex

RESULTS = pathlib.Path("../results")
FIGURES = pathlib.Path("figures")
FIGURES.mkdir(exist_ok=True)

# %% Load data
files = sorted(RESULTS.glob("flakiness_test_outcomes_*.csv"))
assert files, f"No results found in {RESULTS}. Run exp_flakiness/run.py first."
df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
df["isolation_enabled"] = df["isolation_enabled"].astype(str).str.lower().map(
    {"true": True, "false": False}
)
df = df[df["suite"].isin(["smoke", "regression", "e2e"])]
df["failed"] = (df["outcome"].str.lower() == "failed").astype(int)
print(df.groupby(["isolation_enabled", "suite"])["failed"].agg(["sum", "count", "mean"]))

# %% Per-suite analysis
results_table = []
for suite in ["smoke", "regression", "e2e"]:
    sub = df[df["suite"] == suite]
    on = sub[sub["isolation_enabled"] == True]["failed"].tolist()
    off = sub[sub["isolation_enabled"] == False]["failed"].tolist()

    n_on, n_off = len(on), len(off)
    fail_on = sum(on)
    fail_off = sum(off)
    mw = stats.mann_whitney_u(on, off)
    a12 = stats.vargha_delaney_a12(off, on)  # Â₁₂: OFF > ON = bad direction
    fe = stats.fisher_exact(fail_on, n_on, fail_off, n_off)

    print(f"\n{suite.upper()}: fail_rate ON={fail_on/n_on:.2%} OFF={fail_off/n_off:.2%}")
    print(f"  MWU p={mw['p']:.4f}  Â₁₂={a12:.2f}  Fisher p={fe['p']:.4f}")

    results_table.append([
        suite.capitalize(),
        f"{fail_on}/{n_on} ({fail_on/n_on:.0%})",
        f"{fail_off}/{n_off} ({fail_off/n_off:.0%})",
        latex.fmt_p(mw["p"]),
        latex.fmt_a12(a12),
    ])

# %% Figure: failure rates per suite
fig, ax = plotting.figure(width_in=3.5, height_in=2.8)
suites = ["smoke", "regression", "e2e"]
rates_on = [df[(df["suite"] == s) & (df["isolation_enabled"] == True)]["failed"].mean() for s in suites]
rates_off = [df[(df["suite"] == s) & (df["isolation_enabled"] == False)]["failed"].mean() for s in suites]
plotting.bar_compare(ax, suites, rates_on, rates_off, ylabel="Failure rate", title="RQ1 — Flakiness per suite")
plotting.save(fig, str(FIGURES / "rq1_flakiness_rates.pdf"))

# %% LaTeX table
print("\n--- LaTeX ---")
print(latex.table(
    headers=["Suite", "Failures (ON)", "Failures (OFF)", "MWU p", r"$\hat{A}_{12}$"],
    rows=results_table,
    caption="RQ1: Test failure rates with and without checkpoint isolation (N=30 each).",
    label="tab:rq1-flakiness",
))
