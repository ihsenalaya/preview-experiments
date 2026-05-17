# RQ1: cross-subject summary on isolation-sensitive suites (regression + e2e).

| Subject | Suite | Fail ON | Fail OFF | Risk diff | Fisher p | Cohen's h |
|---|---|---|---|---|---|---|
| s1-flask-catalog | regression | 0/30 (0%) | 30/30 (100%) | -100pp | $<$0.001 | 3.14 |
| s1-flask-catalog | e2e | 0/30 (0%) | 30/30 (100%) | -100pp | $<$0.001 | 3.14 |
| s2-listmonk | regression | 0/30 (0%) | 30/30 (100%) | -100pp | $<$0.001 | 3.14 |
| s2-listmonk | e2e | 0/30 (0%) | 30/30 (100%) | -100pp | $<$0.001 | 3.14 |
| s3-healthchecks | regression | 0/30 (0%) | 30/30 (100%) | -100pp | $<$0.001 | 3.14 |
| s3-healthchecks | e2e | 0/30 (0%) | 30/30 (100%) | -100pp | $<$0.001 | 3.14 |
| s4-umami | regression | 0/30 (0%) | 17/17 (100%) | -100pp | $<$0.001 | 3.14 |
| s4-umami | e2e | 0/30 (0%) | 17/17 (100%) | -100pp | $<$0.001 | 3.14 |
| s5-petclinic | regression | 30/30 (100%) | 30/30 (100%) | +0pp | 1.000 | 0.00 |
| s5-petclinic | e2e | 30/30 (100%) | 30/30 (100%) | +0pp | 1.000 | 0.00 |
