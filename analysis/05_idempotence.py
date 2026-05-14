# ---
# jupyter:
#   jupytext:
#     formats: py:percent,ipynb
# ---

# %% [markdown]
# # RQ5 — Pipeline idempotence under operator restarts

# %%
import pathlib
import pandas as pd
import sys

sys.path.insert(0, str(pathlib.Path("..").resolve()))
from analysis.shared import stats, plotting, latex

RESULTS = pathlib.Path("../results")
FIGURES = pathlib.Path("figures")
FIGURES.mkdir(exist_ok=True)

# %% Load
files = sorted(RESULTS.glob("idempotence_run_metrics_*.csv"))
assert files
df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
df["step_duration_s"] = pd.to_numeric(df["step_duration_s"], errors="coerce")  # convergence_s
df["diverged"] = df["requeue_count"].astype(float) > 0

# %% Summary
by_step = df.groupby("step").agg(
    n=("run_id", "count"),
    divergences=("diverged", "sum"),
    mean_convergence_s=("step_duration_s", "mean"),
    p95_convergence_s=("step_duration_s", lambda x: x.quantile(0.95)),
).reset_index()
print(by_step)

total_divergences = df["diverged"].sum()
total_runs = len(df)
print(f"\nTotal divergences: {total_divergences}/{total_runs} ({total_divergences/total_runs:.1%})")

# %% Figure: convergence time by kill step
fig, ax = plotting.figure(width_in=4.0, height_in=2.8)
step_order = ["saving", "smoke", "restore-regression", "regression", "restore-e2e", "e2e"]
convergence_by_step = [
    df[df["step"] == s]["step_duration_s"].dropna().tolist()
    for s in step_order if s in df["step"].unique()
]
labels = [s for s in step_order if s in df["step"].unique()]
ax.boxplot(convergence_by_step, labels=labels,
           patch_artist=True,
           boxprops={"facecolor": plotting.PALETTE["blue"] + "88"},
           medianprops={"color": "black"},
           flierprops={"marker": "."})
ax.set_xlabel("Kill step")
ax.set_ylabel("Time to convergence (s)")
ax.set_title("RQ5 — Convergence time after operator restart")
ax.tick_params(axis="x", rotation=30)
plotting.save(fig, str(FIGURES / "rq5_idempotence.pdf"))

# %% LaTeX
rows = []
for _, row in by_step.iterrows():
    rows.append([
        row["step"],
        int(row["n"]),
        int(row["divergences"]),
        f"{row['mean_convergence_s']:.1f}",
        f"{row['p95_convergence_s']:.1f}",
    ])

print("\n--- LaTeX ---")
print(latex.table(
    headers=["Kill step", "N", "Divergences", r"$\bar{t}$ conv. (s)", "p95 conv. (s)"],
    rows=rows,
    caption="RQ5: Convergence time and state divergence after operator pod restart at each pipeline step.",
    label="tab:rq5-idempotence",
))
