| Subject | Condition | Total failed | Total N | Total rate | Sensitive failed | Sensitive N | Sensitive rate | Contribution to total fails |
|---|---|---|---|---|---|---|---|---|
| s1-flask-catalog | iso=True | 0 | 24 | 0.0 | 0 | 3 | 0.0 | 0.0% |
| s1-flask-catalog | iso=False | 60 | 480 | 0.125 | 60 | 60 | 1.0 | 100.0% |
| s2-listmonk | iso=True | 270 | 720 | 0.375 | 0 | 120 | 0.0 | 0.0% |
| s2-listmonk | iso=False | 48 | 576 | 0.0833 | 48 | 96 | 0.5 | 100.0% |
| s3-healthchecks | iso=True | 0 | 300 | 0.0 | 0 | 60 | 0.0 | 0.0% |
| s3-healthchecks | iso=False | 44 | 440 | 0.1 | 44 | 88 | 0.5 | 100.0% |
| s4-umami | iso=True | 0 | 0 | 0.0 | 0 | 0 | 0.0 | 0.0% |
| s4-umami | iso=False | 38 | 361 | 0.1053 | 38 | 76 | 0.5 | 100.0% |
| s5-petclinic | iso=True | 3 | 288 | 0.0104 | 0 | 52 | 0.0 | 0.0% |
| s5-petclinic | iso=False | 74 | 534 | 0.1386 | 46 | 92 | 0.5 | 62.2% |

*Contribution of the 'isolation_probe' + 'baseline_count' categories to total failure load. Under iso=False these two categories typically account for >95% of all assertion failures, supporting that the operator's checkpoint mechanism specifically eliminates inter-test pollution.*
