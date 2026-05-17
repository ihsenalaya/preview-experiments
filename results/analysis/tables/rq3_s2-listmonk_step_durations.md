# RQ3: per-step durations (iso=True) — s2-listmonk

| Step | N | Median (s) | Mean (s) | σ | p95 (s) |
|---|---|---|---|---|---|
| postgres-migrate | 30 | 39.5 | 39.10 | 3.29 | 43.5 |
| smoke | 30 | 5.0 | 4.70 | 0.70 | 5.5 |
| saving | 30 | 4.0 | 4.20 | 0.71 | 5.0 |
| restore-regression | 30 | 5.0 | 5.40 | 0.77 | 6.5 |
| restore-e2e | 30 | 5.0 | 5.47 | 0.94 | 6.0 |
| checkpoint_total | 30 | 15.0 | 15.07 | 1.20 | 16.5 |
