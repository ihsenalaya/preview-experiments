| Subject | Category | Failed/N (iso=T) | Failed/N (iso=F) | Rate iso=T | Rate iso=F | Risk diff (T-F) | Verdict |
|---|---|---|---|---|---|---|---|
| s1-flask-catalog | isolation_probe | 0/2 | 40/40 | 0.0 | 1.0 | -1.0 | ✓ iso eliminates |
| s1-flask-catalog | baseline_count | 0/1 | 20/20 | 0.0 | 1.0 | -1.0 | ✓ iso eliminates |
| s2-listmonk | isolation_probe | 0/60 | 48/48 | 0.0 | 1.0 | -1.0 | ✓ iso eliminates |
| s2-listmonk | baseline_count | 0/60 | 0/48 | 0.0 | 0.0 | 0.0 |  |
| s3-healthchecks | isolation_probe | 0/30 | 44/44 | 0.0 | 1.0 | -1.0 | ✓ iso eliminates |
| s3-healthchecks | baseline_count | 0/30 | 0/44 | 0.0 | 0.0 | 0.0 |  |
| s5-petclinic | isolation_probe | 0/26 | 46/46 | 0.0 | 1.0 | -1.0 | ✓ iso eliminates |
| s5-petclinic | baseline_count | 0/26 | 0/46 | 0.0 | 0.0 | 0.0 |  |

*Per-(subject, isolation-sensitive category) risk difference. 'iso eliminates' means iso=True drops to 0% failure while iso=False is >50%, i.e. the checkpoint mechanism fully resolves the assertion class.*
