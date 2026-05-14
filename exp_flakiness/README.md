# RQ1 — Flakiness experiment

**Hypothesis**: checkpoint isolation (IsolationEnabled=true) reduces test suite failure rate
and variance compared to no isolation (IsolationEnabled=false).

## What is measured

- `outcome` per suite (smoke, regression, e2e) across N=30 runs each condition
- DB row count at end of seed phase (should be constant; deviation = non-determinism)
- Step duration from K8s Job startTime/completionTime

## Isolation OFF semantics

When `spec.database.isolationEnabled=false`:
- The `saving` step is skipped (no checkpoint created).
- The `restore-regression` and `restore-e2e` steps are skipped.
- The regression suite runs on whatever DB state was left by smoke tests.
- This matches the behaviour of a shared staging environment without cleanup.

## Running

```bash
cd experimentation/
python exp_flakiness/run.py
```

Override N:
```bash
EXP_EXPERIMENTS_FLAKINESS_N_RUNS=5 python exp_flakiness/run.py
```

## Expected output

`results/flakiness_test_outcomes_<timestamp>.csv`

## Statistical analysis

See `analysis/01_flakiness.ipynb`:
- Mann-Whitney U on failure counts (isolation ON vs OFF)
- Vargha-Delaney Â₁₂ effect size
- Fisher's exact test on binary pass/fail per suite
