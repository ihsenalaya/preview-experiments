"""RQ4 bug_detection — per-subject detection-rate analysis with McNemar pairwise."""
import sys
import re
from pathlib import Path
import pandas as pd
from scipy import stats as sstats

SUBJECT = sys.argv[1]
csv_dir = Path(__file__).parent / "results" / SUBJECT
files = sorted(csv_dir.glob("bug_detection_test_outcomes_2026051*.csv"))
files = [f for f in files if f.stat().st_size > 200]  # skip stubs

if not files:
    print(f"No bug_det data for {SUBJECT}")
    sys.exit(1)

# Pick the largest CSV (most complete)
csv = max(files, key=lambda f: f.stat().st_size)
df = pd.read_csv(csv)
df = df[df["suite"].isin(["smoke", "regression", "e2e"])]

# Extract mutant id and condition from test_name (format mutant_N_CONDITION)
def parse_mc(t):
    m = re.match(r"mutant_(\d+)_(static|llm_fixed|llm_free)$", str(t))
    return (int(m.group(1)), m.group(2)) if m else (None, None)

df["mutant"], df["condition"] = zip(*df["test_name"].map(parse_mc))
df = df.dropna(subset=["mutant", "condition"])
df["mutant"] = df["mutant"].astype(int)
# Detection = at least one suite reports outcome != Succeeded for this (mutant, condition)
df["failed"] = (df["outcome"] != "Succeeded").astype(int)
detect = df.groupby(["mutant", "condition"])["failed"].max().reset_index()

# Pivot to wide: rows = mutants, cols = conditions, values = 0/1 detected
pivot = detect.pivot(index="mutant", columns="condition", values="failed").fillna(0).astype(int)

print(f"=== RQ4 bug_detection — {SUBJECT} ===")
print(f"Source: {csv.name}")
print(f"Mutants observed: {len(pivot)} (target = 50)")
print(f"Conditions present: {sorted(pivot.columns.tolist())}\n")

for c in pivot.columns:
    n_det = pivot[c].sum()
    n = len(pivot)
    print(f"  {c:11s}  detection {n_det}/{n} ({n_det/n*100:.1f} %)")
print()

# McNemar tests on the 3 pairs
pairs = [
    ("static", "llm_fixed"),
    ("static", "llm_free"),
    ("llm_fixed", "llm_free"),
]
print("=== McNemar pairwise (discordant pairs) ===")
for a, b in pairs:
    if a not in pivot.columns or b not in pivot.columns:
        print(f"  {a:11s} vs {b:11s}: skip (missing condition)")
        continue
    # Discordant cells: a=0/b=1 (n01) and a=1/b=0 (n10)
    n01 = int(((pivot[a] == 0) & (pivot[b] == 1)).sum())
    n10 = int(((pivot[a] == 1) & (pivot[b] == 0)).sum())
    # McNemar exact (binomial) when small N
    total_disc = n01 + n10
    if total_disc == 0:
        print(f"  {a:11s} vs {b:11s}: 0 discordant pairs (perfect concordance) — no test")
        continue
    p_val = 2 * min(sstats.binom.cdf(min(n01, n10), total_disc, 0.5), 1 - sstats.binom.cdf(min(n01, n10) - 1, total_disc, 0.5))
    p_val = min(p_val, 1.0)
    direction = "→" if n01 > n10 else "←"
    print(f"  {a:11s} vs {b:11s}: n01={n01:2d}  n10={n10:2d}  total_disc={total_disc:2d}  exact p={p_val:.3g}  ({direction} {b if n01>n10 else a} detects more)")
