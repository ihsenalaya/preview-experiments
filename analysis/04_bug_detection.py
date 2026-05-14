# ---
# jupyter:
#   jupytext:
#     formats: py:percent,ipynb
# ---

# %% [markdown]
# # RQ4 — LLM-directed seeding detects more bugs than static fixtures

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
files = sorted(RESULTS.glob("bug_detection_test_outcomes_*.csv"))
assert files
df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)

# Derive seed_mode and mutant_id from test_name column (format: mutant_<id>_<mode>)
df["seed_mode"] = df["test_name"].str.extract(r"mutant_\d+_(static|llm)")
df["mutant_id"]  = df["test_name"].str.extract(r"mutant_(\d+)_").astype(float)
df["detected"]   = (df["outcome"].str.lower() == "failed").astype(int)

# %% Detection rate per seed mode
by_mode = df.groupby("seed_mode")["detected"].agg(["sum", "count", "mean"])
print(by_mode)

# %% McNemar test (paired per mutant)
pivoted = df.pivot_table(index="mutant_id", columns="seed_mode", values="detected", aggfunc="max")
pivoted = pivoted.dropna()
n01 = int(((pivoted["static"] == 0) & (pivoted["llm"] == 1)).sum())  # LLM detects, static misses
n10 = int(((pivoted["static"] == 1) & (pivoted["llm"] == 0)).sum())  # static detects, LLM misses
mcn = stats.mcnemar(n01, n10)
print(f"\nMcNemar: n01={n01}  n10={n10}  chi2={mcn['chi2']:.3f}  p={mcn['p']:.4f}")

# %% Figure: detection rate bar chart
fig, ax = plotting.figure(width_in=3.2, height_in=2.6)
rates = by_mode["mean"]
colors = [plotting.ISO_ON_COLOR if m == "llm" else plotting.ISO_OFF_COLOR for m in rates.index]
ax.bar(rates.index, rates.values, color=colors)
ax.set_ylabel("Detection rate")
ax.set_title("RQ4 — Bug detection: LLM vs static")
ax.set_ylim(0, 1.1)
for i, (mode, val) in enumerate(rates.items()):
    ax.text(i, val + 0.02, f"{val:.0%}", ha="center", fontsize=9)
plotting.save(fig, str(FIGURES / "rq4_bug_detection.pdf"))

# %% LaTeX
static_r = by_mode.loc["static", "mean"] if "static" in by_mode.index else float("nan")
llm_r    = by_mode.loc["llm",    "mean"] if "llm"    in by_mode.index else float("nan")
print("\n--- LaTeX ---")
print(latex.table(
    headers=["Seed mode", "Detected", "Total", "Rate", r"McNemar $p$"],
    rows=[
        ["Static",  int(by_mode.loc["static", "sum"]) if "static" in by_mode.index else "—",
         int(by_mode.loc["static", "count"]) if "static" in by_mode.index else "—",
         f"{static_r:.2%}", latex.fmt_p(mcn["p"])],
        ["LLM-diff",int(by_mode.loc["llm", "sum"])  if "llm" in by_mode.index else "—",
         int(by_mode.loc["llm", "count"])  if "llm" in by_mode.index else "—",
         f"{llm_r:.2%}", ""],
    ],
    caption="RQ4: Mutation detection rate — static fixtures vs. LLM-directed seeding.",
    label="tab:rq4-bug-detection",
))
