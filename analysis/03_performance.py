# ---
# jupyter:
#   jupytext:
#     formats: py:percent,ipynb
# ---

# %% [markdown]
# # RQ3 — Performance overhead of checkpoint isolation

# %%
import pathlib
import pandas as pd
import numpy as np
import sys

sys.path.insert(0, str(pathlib.Path("..").resolve()))
from analysis.shared import stats, plotting, latex

RESULTS = pathlib.Path("../results")
FIGURES = pathlib.Path("figures")
FIGURES.mkdir(exist_ok=True)

# %% Load
files = sorted(RESULTS.glob("performance_run_metrics_*.csv"))
assert files
df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
df["isolation_enabled"] = df["isolation_enabled"].astype(str).str.lower().map(
    {"true": True, "false": False}
)
df["step_duration_s"] = pd.to_numeric(df["step_duration_s"], errors="coerce")
df["total_reconcile_s"] = pd.to_numeric(df["total_reconcile_s"], errors="coerce")

# %% Per-step summary
step_order = ["saving", "smoke", "contract", "restore-regression",
              "regression", "restore-e2e", "e2e", "checkpoint_total"]
step_df = df[df["step"].isin(step_order)].copy()
summary = step_df.groupby(["step", "isolation_enabled"])["step_duration_s"].agg(
    ["mean", "median", "std"]
).round(2)
print(summary)

# %% Overhead calculation
checkpoint_steps = ["saving", "restore-regression", "restore-e2e"]
overhead_df = df[df["step"] == "checkpoint_total"].copy()
overhead_df["overhead_pct"] = overhead_df["requeue_count"].astype(float)
on_overhead = overhead_df[overhead_df["isolation_enabled"] == True]["overhead_pct"].dropna()
print(f"\nOverhead (isolation ON): mean={on_overhead.mean():.1f}%  p95={np.percentile(on_overhead, 95):.1f}%")

# %% Figure: box plot per step
iso_on = df[(df["isolation_enabled"] == True) & df["step"].isin(checkpoint_steps)]
iso_off = df[(df["isolation_enabled"] == False)]

fig, ax = plotting.figure(width_in=5.0, height_in=3.0)
steps_present = [s for s in step_order if s in df["step"].unique() and s != "checkpoint_total"]
data_on  = [df[(df["step"] == s) & (df["isolation_enabled"] == True)]["step_duration_s"].dropna().tolist() for s in steps_present]
data_off = [df[(df["step"] == s) & (df["isolation_enabled"] == False)]["step_duration_s"].dropna().tolist() for s in steps_present]

import matplotlib.pyplot as plt
x = range(len(steps_present))
ax.boxplot(data_on, positions=[i - 0.2 for i in x], widths=0.3,
           patch_artist=True, boxprops={"facecolor": plotting.ISO_ON_COLOR + "88"},
           medianprops={"color": "black"}, flierprops={"marker": "."})
ax.boxplot(data_off, positions=[i + 0.2 for i in x], widths=0.3,
           patch_artist=True, boxprops={"facecolor": plotting.ISO_OFF_COLOR + "88"},
           medianprops={"color": "black"}, flierprops={"marker": "."})
ax.set_xticks(list(x))
ax.set_xticklabels(steps_present, rotation=30, ha="right", fontsize=8)
ax.set_ylabel("Duration (s)")
ax.set_title("RQ3 — Step durations: Isolation ON vs OFF")
from matplotlib.patches import Patch
ax.legend(handles=[
    Patch(facecolor=plotting.ISO_ON_COLOR + "88", label="Isolation ON"),
    Patch(facecolor=plotting.ISO_OFF_COLOR + "88", label="Isolation OFF"),
])
plotting.save(fig, str(FIGURES / "rq3_performance.pdf"))

# %% LaTeX summary table
rows = []
for step in steps_present:
    sub = df[df["step"] == step]
    s_on = stats.summary_stats(sub[sub["isolation_enabled"] == True]["step_duration_s"].dropna())
    s_off = stats.summary_stats(sub[sub["isolation_enabled"] == False]["step_duration_s"].dropna())
    rows.append([
        step,
        f'{s_on["median"]:.1f} ± {s_on["std"]:.1f}',
        f'{s_off["median"]:.1f} ± {s_off["std"]:.1f}',
    ])

print("\n--- LaTeX ---")
print(latex.table(
    headers=["Step", "Duration ON (s, median±σ)", "Duration OFF (s, median±σ)"],
    rows=rows,
    caption=r"RQ3: Per-step durations (N=20). Checkpoint steps appear only in the Isolation ON condition.",
    label="tab:rq3-performance",
))
