# ---
# jupyter:
#   jupytext:
#     formats: py:percent,ipynb
# ---

# %% [markdown]
# # RQ2 — Cross-PR pollution under concurrent load

# %%
import pathlib
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import sys

sys.path.insert(0, str(pathlib.Path("..").resolve()))
from analysis.shared import stats, plotting, latex

RESULTS = pathlib.Path("../results")
FIGURES = pathlib.Path("figures")
FIGURES.mkdir(exist_ok=True)

# %% Load data
files = sorted(RESULTS.glob("cross_pr_test_outcomes_*.csv"))
assert files, f"No results. Run exp_cross_pr/run.py first."
df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
df["isolation_enabled"] = df["isolation_enabled"].astype(str).str.lower().map(
    {"true": True, "false": False}
)
df["k"] = df["run_id"].str.extract(r"concurrent_k(\d+)").astype(float)
df["failed"] = (df["outcome"].str.lower() == "failed").astype(int)

# %% Failure rate by K and isolation
pivot = df.groupby(["k", "isolation_enabled", "suite"])["failed"].mean().reset_index()
print(pivot.pivot_table(index=["k", "suite"], columns="isolation_enabled", values="failed"))

# %% Figure: failure rate vs K
fig, axes = plotting.two_col_figure(height_in=2.8)
fig, axes = plt.subplots(1, 3, figsize=(7.0, 2.6), sharey=True)
for ax, suite in zip(axes, ["smoke", "regression", "e2e"]):
    sub = df[df["suite"] == suite]
    for iso, color, label in [(True, plotting.ISO_ON_COLOR, "Isolation ON"),
                               (False, plotting.ISO_OFF_COLOR, "Isolation OFF")]:
        g = sub[sub["isolation_enabled"] == iso].groupby("k")["failed"].mean()
        ax.plot(g.index, g.values, marker="o", color=color, label=label, linewidth=1.5)
    ax.set_title(suite.capitalize())
    ax.set_xlabel("Concurrent PRs (K)")
    if suite == "smoke":
        ax.set_ylabel("Failure rate")
    ax.legend(fontsize=7)

fig.suptitle("RQ2 — Failure rate vs. concurrent PRs", y=1.02)
fig.tight_layout()
plotting.save(fig, str(FIGURES / "rq2_cross_pr.pdf"))

# %% Statistical test: MWU isolation ON vs OFF aggregated per K
results_table = []
for k in sorted(df["k"].dropna().unique()):
    sub_k = df[df["k"] == k]
    on = sub_k[sub_k["isolation_enabled"] == True]["failed"].tolist()
    off = sub_k[sub_k["isolation_enabled"] == False]["failed"].tolist()
    mw = stats.mann_whitney_u(on, off)
    a12 = stats.vargha_delaney_a12(off, on)
    results_table.append([
        int(k),
        f"{sum(on)/len(on):.2%}",
        f"{sum(off)/len(off):.2%}",
        latex.fmt_p(mw["p"]),
        latex.fmt_a12(a12),
    ])

print("\n--- LaTeX ---")
print(latex.table(
    headers=["K", "Fail rate (ON)", "Fail rate (OFF)", "MWU p", r"$\hat{A}_{12}$"],
    rows=results_table,
    caption="RQ2: Failure rates under K concurrent PRs with and without isolation.",
    label="tab:rq2-cross-pr",
))
