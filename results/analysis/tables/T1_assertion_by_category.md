| Subject | Condition | Category | Failed | N | Failure rate |
|---|---|---|---|---|---|
| s1-flask-catalog | iso=True | baseline_count | 0 | 1 | 0.0 |
| s1-flask-catalog | iso=True | functional_api | 0 | 19 | 0.0 |
| s1-flask-catalog | iso=True | infra | 0 | 2 | 0.0 |
| s1-flask-catalog | iso=True | isolation_probe | 0 | 2 | 0.0 |
| s1-flask-catalog | iso=False | baseline_count | 20 | 20 | 1.0 |
| s1-flask-catalog | iso=False | functional_api | 0 | 380 | 0.0 |
| s1-flask-catalog | iso=False | infra | 0 | 40 | 0.0 |
| s1-flask-catalog | iso=False | isolation_probe | 40 | 40 | 1.0 |
| s2-listmonk | iso=True | baseline_count | 0 | 60 | 0.0 |
| s2-listmonk | iso=True | functional_api | 210 | 420 | 0.5 |
| s2-listmonk | iso=True | infra | 0 | 90 | 0.0 |
| s2-listmonk | iso=True | isolation_probe | 0 | 60 | 0.0 |
| s2-listmonk | iso=True | unknown | 60 | 90 | 0.6667 |
| s2-listmonk | iso=False | baseline_count | 0 | 48 | 0.0 |
| s2-listmonk | iso=False | functional_api | 0 | 336 | 0.0 |
| s2-listmonk | iso=False | infra | 0 | 72 | 0.0 |
| s2-listmonk | iso=False | isolation_probe | 48 | 48 | 1.0 |
| s2-listmonk | iso=False | unknown | 0 | 72 | 0.0 |
| s3-healthchecks | iso=True | baseline_count | 0 | 30 | 0.0 |
| s3-healthchecks | iso=True | functional_api | 0 | 150 | 0.0 |
| s3-healthchecks | iso=True | infra | 0 | 45 | 0.0 |
| s3-healthchecks | iso=True | isolation_probe | 0 | 30 | 0.0 |
| s3-healthchecks | iso=True | unknown | 0 | 45 | 0.0 |
| s3-healthchecks | iso=False | baseline_count | 0 | 44 | 0.0 |
| s3-healthchecks | iso=False | functional_api | 0 | 220 | 0.0 |
| s3-healthchecks | iso=False | infra | 0 | 66 | 0.0 |
| s3-healthchecks | iso=False | isolation_probe | 44 | 44 | 1.0 |
| s3-healthchecks | iso=False | unknown | 0 | 66 | 0.0 |
| s4-umami | iso=False | auth_permission | 0 | 76 | 0.0 |
| s4-umami | iso=False | baseline_count | 0 | 38 | 0.0 |
| s4-umami | iso=False | functional_api | 0 | 152 | 0.0 |
| s4-umami | iso=False | infra | 0 | 57 | 0.0 |
| s4-umami | iso=False | isolation_probe | 38 | 38 | 1.0 |
| s5-petclinic | iso=True | baseline_count | 0 | 26 | 0.0 |
| s5-petclinic | iso=True | functional_api | 3 | 197 | 0.0152 |
| s5-petclinic | iso=True | infra | 0 | 39 | 0.0 |
| s5-petclinic | iso=True | isolation_probe | 0 | 26 | 0.0 |
| s5-petclinic | iso=False | baseline_count | 0 | 46 | 0.0 |
| s5-petclinic | iso=False | functional_api | 28 | 373 | 0.0751 |
| s5-petclinic | iso=False | infra | 0 | 69 | 0.0 |
| s5-petclinic | iso=False | isolation_probe | 46 | 46 | 1.0 |

*Per-(subject, condition, category) failure rate from 3,723 live-captured assertions (PHASE 2 watcher). Decomposes the suite-level RQ1 finding into the assertion categories that actually drive it.*
