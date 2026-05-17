# RQ3: per-step durations (iso=True) — s3-healthchecks

| Step | N | Median (s) | Mean (s) | σ | p95 (s) |
|---|---|---|---|---|---|
| postgres-migrate | 30 | 36.0 | 35.70 | 3.20 | 40.0 |
| smoke | 30 | 5.0 | 5.23 | 0.77 | 6.5 |
| saving | 30 | 4.0 | 4.27 | 0.74 | 5.5 |
| restore-regression | 30 | 6.0 | 5.80 | 0.76 | 7.0 |
| regression | 30 | 5.0 | 4.90 | 0.71 | 6.0 |
| restore-e2e | 30 | 6.0 | 5.97 | 0.76 | 7.0 |
| e2e | 30 | 11.0 | 10.93 | 1.53 | 13.5 |
| checkpoint_total | 30 | 16.0 | 16.03 | 1.19 | 18.0 |
