"""Analyze cross_pr CSV — per (K, isolation) outcomes for a given subject."""
import sys
import re
from pathlib import Path
import pandas as pd
from scipy import stats as sstats

SUBJECT = sys.argv[1]
ROOT = Path(__file__).parent / "results" / SUBJECT


def cohen_h(p1, p2):
    import math
    return abs(2 * math.asin(math.sqrt(p1)) - 2 * math.asin(math.sqrt(p2)))


def find_latest_aks_csv():
    files = sorted(ROOT.glob("cross_pr_test_outcomes_2026051[67]*.csv"))
    # Pick the largest (most rows = most complete) from the AKS run timestamp range
    cands = [f for f in files if f.stat().st_size > 1000]
    return cands[-1] if cands else None


csv = find_latest_aks_csv()
if not csv:
    print(f"No AKS cross_pr CSV for {SUBJECT}")
    sys.exit(1)

df = pd.read_csv(csv)
df = df[df["suite"].isin(["smoke", "regression", "e2e"])]


def parse_k(run_id):
    m = re.search(r"-k(\d+)-iso", str(run_id))
    return int(m.group(1)) if m else None


df["k"] = df["run_id"].map(parse_k)
df["iso"] = df["isolation_enabled"].astype(str)
df["failed"] = (df["outcome"] == "Failed").astype(int)

print(f"=== RQ2 cross_pr (AKS, K=8 proper) — {SUBJECT} ===")
print(f"Source: {csv.name}")
print(f"Rows: {len(df)}\n")

for k in sorted(df["k"].dropna().unique().astype(int)):
    sub_k = df[df["k"] == k]
    on = sub_k[sub_k["iso"] == "True"]
    off = sub_k[sub_k["iso"] == "False"]
    print(f"--- K={k} ---")
    for suite in ["smoke", "regression", "e2e"]:
        on_s = on[on["suite"] == suite]
        off_s = off[off["suite"] == suite]
        on_f, on_n = on_s["failed"].sum(), len(on_s)
        off_f, off_n = off_s["failed"].sum(), len(off_s)
        p1 = on_f / on_n if on_n else 0.0
        p2 = off_f / off_n if off_n else 0.0
        delta_pp = (p1 - p2) * 100
        try:
            _, p_val = sstats.fisher_exact(
                [[on_f, on_n - on_f], [off_f, off_n - off_f]], alternative="less"
            )
        except Exception:
            p_val = float("nan")
        h = cohen_h(p1, p2)
        print(f"  {suite:10s}  iso=T {on_f}/{on_n} ({p1*100:>5.1f}%)  iso=F {off_f}/{off_n} ({p2*100:>5.1f}%)  Δ={delta_pp:+.0f}pp  Fisher p={p_val:.2e}  h={h:.2f}")
    print()
