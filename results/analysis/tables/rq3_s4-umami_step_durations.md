# RQ3: per-step durations (iso=True) — s4-umami

| Step | N | Median (s) | Mean (s) | σ | p95 (s) |
|---|---|---|---|---|---|
| postgres-migrate | 29 | 25.0 | 37.38 | 36.00 | 122.8 |
| saving | 29 | 4.0 | 4.59 | 1.48 | 6.2 |
| restore-regression | 29 | 6.0 | 5.83 | 1.69 | 7.6 |
| restore-e2e | 29 | 5.0 | 5.38 | 1.01 | 6.6 |
| checkpoint_total | 29 | 16.0 | 15.79 | 2.44 | 20.0 |
