# RQ4: bug-detection rates by seed condition and pairwise McNemar. Only S1 is architecturally interpretable; other subjects are noted but not decisive (fault-catalog targets testapp/app.py, not their SUTs).

| Subject | Condition / Test | N mutants | Detected | Rate | Wilson 95% CI / Result |
|---|---|---|---|---|---|
| s1-flask-catalog | static | 50 | 23 | 46% | [33, 60] |
| s1-flask-catalog | llm_fixed | 50 | 23 | 46% | [33, 60] |
| s1-flask-catalog | llm_free | 50 | 23 | 46% | [33, 60] |
| s1-flask-catalog | McNemar static vs llm_fixed | — | n01=0 n10=0 | — | perfect concordance (n01=n10=0) |
| s1-flask-catalog | McNemar static vs llm_free | — | n01=0 n10=0 | — | perfect concordance (n01=n10=0) |
| s1-flask-catalog | McNemar llm_fixed vs llm_free | — | n01=0 n10=0 | — | perfect concordance (n01=n10=0) |
| s2-listmonk | static | 47 | 47 | 100% | [92, 100] |
| s2-listmonk | llm_fixed | 47 | 47 | 100% | [92, 100] |
| s2-listmonk | llm_free | 47 | 47 | 100% | [92, 100] |
| s2-listmonk | McNemar static vs llm_fixed | — | n01=0 n10=0 | — | perfect concordance (n01=n10=0) |
| s2-listmonk | McNemar static vs llm_free | — | n01=0 n10=0 | — | perfect concordance (n01=n10=0) |
| s2-listmonk | McNemar llm_fixed vs llm_free | — | n01=0 n10=0 | — | perfect concordance (n01=n10=0) |
| s3-healthchecks | static | 47 | 0 | 0% | [0, 8] |
| s3-healthchecks | llm_fixed | 47 | 0 | 0% | [0, 8] |
| s3-healthchecks | llm_free | 47 | 0 | 0% | [0, 8] |
| s3-healthchecks | McNemar static vs llm_fixed | — | n01=0 n10=0 | — | perfect concordance (n01=n10=0) |
| s3-healthchecks | McNemar static vs llm_free | — | n01=0 n10=0 | — | perfect concordance (n01=n10=0) |
| s3-healthchecks | McNemar llm_fixed vs llm_free | — | n01=0 n10=0 | — | perfect concordance (n01=n10=0) |
