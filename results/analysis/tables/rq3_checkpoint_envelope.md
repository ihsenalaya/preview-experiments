# RQ3: checkpoint_total across 5 subjects (cross-stack envelope).

| Subject | N | Median (s) | Mean (s) | σ | p95 (s) | Pipeline ON median | Pipeline OFF median | MWU p | Â₁₂ |
|---|---|---|---|---|---|---|---|---|---|
| s1-flask-catalog | 30 | 14.0 | 14.63 | 1.03 | 16.0 | 72.0 | 23.0 | $<$0.001 | 1.00 |
| s2-listmonk | 30 | 15.0 | 15.07 | 1.20 | 16.5 | 75.5 | 46.0 | $<$0.001 | 1.00 |
| s3-healthchecks | 30 | 16.0 | 16.03 | 1.19 | 18.0 | 88.0 | 42.5 | $<$0.001 | 0.97 |
| s4-umami | 29 | 16.0 | 15.79 | 2.44 | 20.0 | 56.0 | 25.0 | $<$0.001 | 0.97 |
| s5-petclinic | 30 | 14.0 | 14.23 | 1.19 | 16.0 | 115.0 | 87.0 | $<$0.001 | 1.00 |
