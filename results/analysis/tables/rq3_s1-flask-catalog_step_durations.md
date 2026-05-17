# RQ3: per-step durations (iso=True) — s1-flask-catalog

| Step | N | Median (s) | Mean (s) | σ | p95 (s) |
|---|---|---|---|---|---|
| postgres-migrate | 30 | 19.0 | 18.83 | 0.75 | 20.0 |
| smoke | 30 | 5.0 | 4.80 | 0.61 | 5.0 |
| saving | 30 | 4.0 | 4.23 | 0.63 | 5.0 |
| restore-regression | 30 | 5.0 | 5.20 | 0.41 | 6.0 |
| regression | 29 | 5.0 | 4.72 | 0.45 | 5.0 |
| restore-e2e | 30 | 5.0 | 5.20 | 0.41 | 6.0 |
| e2e | 30 | 14.0 | 14.83 | 1.46 | 17.0 |
| checkpoint_total | 30 | 14.0 | 14.63 | 1.03 | 16.0 |
