# RQ1: per-suite failure rates with vs without isolation — s5-petclinic

| Suite | Fail/N ON | 95% CI ON | Fail/N OFF | 95% CI OFF | Risk diff | OR (Haldane) | Fisher p | Cohen's h |
|---|---|---|---|---|---|---|---|---|
| smoke | 0/30 (0%) | [0, 11] | 0/30 (0%) | [0, 11] | +0pp | 1.00 | 1.000 | 0.00 |
| regression | 30/30 (100%) | [89, 100] | 30/30 (100%) | [89, 100] | +0pp | 1.00 | 1.000 | 0.00 |
| e2e | 30/30 (100%) | [89, 100] | 30/30 (100%) | [89, 100] | +0pp | 1.00 | 1.000 | 0.00 |
