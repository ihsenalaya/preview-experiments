"""Statistical tests and effect size measures for experiment analysis."""
import numpy as np
from scipy import stats


def mann_whitney_u(a: list | np.ndarray, b: list | np.ndarray) -> dict:
    """Mann-Whitney U test (two-sided). Returns statistic, p-value."""
    u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
    return {"U": u, "p": p, "significant": p < 0.05}


def vargha_delaney_a12(a: list | np.ndarray, b: list | np.ndarray) -> float:
    """
    Vargha-Delaney Â₁₂ effect size.
    Â₁₂ = P(X > Y) + 0.5 * P(X = Y)
    Interpretation: 0.5 = no effect, > 0.71 large, > 0.64 medium, > 0.56 small.
    """
    a, b = np.asarray(a, float), np.asarray(b, float)
    m, n = len(a), len(b)
    wins = sum(1 for x in a for y in b if x > y)
    ties = sum(1 for x in a for y in b if x == y)
    return (wins + 0.5 * ties) / (m * n)


def a12_label(a12: float) -> str:
    if a12 >= 0.71 or a12 <= 0.29:
        return "large"
    if a12 >= 0.64 or a12 <= 0.36:
        return "medium"
    if a12 >= 0.56 or a12 <= 0.44:
        return "small"
    return "negligible"


def fisher_exact(n_success_a: int, n_total_a: int, n_success_b: int, n_total_b: int) -> dict:
    """Fisher's exact test for two binary proportions."""
    table = [
        [n_success_a, n_total_a - n_success_a],
        [n_success_b, n_total_b - n_success_b],
    ]
    odds, p = stats.fisher_exact(table)
    return {"odds_ratio": odds, "p": p, "significant": p < 0.05}


def mcnemar(n_01: int, n_10: int) -> dict:
    """
    McNemar's test for paired binary outcomes.
    n_01: mutant detected by B but not A (static misses, llm detects)
    n_10: mutant detected by A but not B (llm misses, static detects)
    """
    if n_01 + n_10 == 0:
        return {"chi2": 0.0, "p": 1.0, "significant": False}
    chi2 = (abs(n_01 - n_10) - 1) ** 2 / (n_01 + n_10)
    p = 1 - stats.chi2.cdf(chi2, df=1)
    return {"chi2": chi2, "p": p, "significant": p < 0.05}


def summary_stats(x: list | np.ndarray) -> dict:
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    return {
        "n": len(x),
        "mean": float(np.mean(x)),
        "median": float(np.median(x)),
        "std": float(np.std(x, ddof=1)) if len(x) > 1 else 0.0,
        "p5": float(np.percentile(x, 5)),
        "p95": float(np.percentile(x, 95)),
        "min": float(np.min(x)),
        "max": float(np.max(x)),
    }
