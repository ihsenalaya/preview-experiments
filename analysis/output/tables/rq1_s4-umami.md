# RQ1: per-suite failure rates with vs without isolation — s4-umami

| Suite | Fail/N ON | 95% CI ON | Fail/N OFF | 95% CI OFF | Risk diff | OR (Haldane) | Fisher p | Cohen's h |
|---|---|---|---|---|---|---|---|---|
| smoke | 0/30 (0%) | [0, 11] | 0/17 (0%) | [0, 18] | +0pp | 0.57 | 1.000 | 0.00 |
| regression | 0/30 (0%) | [0, 11] | 17/17 (100%) | [82, 100] | -100pp | 0.00 | $<$0.001 | 3.14 |
| e2e | 0/30 (0%) | [0, 11] | 17/17 (100%) | [82, 100] | -100pp | 0.00 | $<$0.001 | 3.14 |
