| Subject | RQ | Condition | Point estimate | 95% bootstrap CI | N |
|---|---|---|---|---|---|
| s1-flask-catalog | RQ1-flakiness | iso=True | 0.0 | [0.000, 0.000] | 30 |
| s1-flask-catalog | RQ1-flakiness | iso=False | 1.0 | [1.000, 1.000] | 30 |
| s2-listmonk | RQ1-flakiness | iso=True | 0.0 | [0.000, 0.000] | 30 |
| s2-listmonk | RQ1-flakiness | iso=False | 1.0 | [1.000, 1.000] | 30 |
| s3-healthchecks | RQ1-flakiness | iso=True | 0.0 | [0.000, 0.000] | 30 |
| s3-healthchecks | RQ1-flakiness | iso=False | 1.0 | [1.000, 1.000] | 30 |
| s4-umami | RQ1-flakiness | iso=True | 0.0 | [0.000, 0.000] | 30 |
| s4-umami | RQ1-flakiness | iso=False | 1.0 | [1.000, 1.000] | 30 |
| s5-petclinic | RQ1-flakiness | iso=True | 1.0 | [1.000, 1.000] | 30 |
| s5-petclinic | RQ1-flakiness | iso=False | 1.0 | [1.000, 1.000] | 30 |
| s1-flask-catalog | RQ3-cycle-time | iso=True | 72.0 | [71.00, 73.00] s | 30 |
| s1-flask-catalog | RQ3-cycle-time | iso=False | 23.0 | [23.00, 23.50] s | 30 |
| s2-listmonk | RQ3-cycle-time | iso=True | 75.5 | [72.00, 77.00] s | 30 |
| s2-listmonk | RQ3-cycle-time | iso=False | 46.0 | [44.50, 46.00] s | 30 |
| s3-healthchecks | RQ3-cycle-time | iso=True | 88.0 | [87.00, 90.00] s | 30 |
| s3-healthchecks | RQ3-cycle-time | iso=False | 42.5 | [41.00, 43.50] s | 30 |
| s4-umami | RQ3-cycle-time | iso=True | 56.0 | [54.00, 60.00] s | 30 |
| s4-umami | RQ3-cycle-time | iso=False | 25.0 | [24.00, 25.50] s | 30 |
| s5-petclinic | RQ3-cycle-time | iso=True | 115.0 | [112.50, 117.50] s | 30 |
| s5-petclinic | RQ3-cycle-time | iso=False | 87.0 | [82.50, 88.00] s | 30 |

*Bootstrap 95% confidence intervals (10,000 resamples, seed=20260517) on median estimates for RQ1 (failure rate) and RQ3 (per-run total cycle time, seconds).*
