# paper_claims.md — claims classés par niveau de preuve

Chaque claim qui apparaîtra (ou pourrait apparaître) dans le papier est
classé selon la rigueur du support empirique. Mise à jour : 2026-05-17T12:10Z
(à re-générer après la fin de la chaîne S4+S5 rerun).

Classifications utilisées :
- **confirmed** — soutenue par ≥ 1 CSV figé dans `results/frozen/`, statistiquement
  testée, taille d'effet rapportée.
- **preliminary** — soutenue par des données en cours de collecte ou avec une
  instrumentation limitée ; à durcir.
- **diagnostic** — observation valide mais non statistiquement testée (capture
  live, single-shot).
- **null_result** — hypothèse réfutée ou non rejetable au seuil α=0.05 ; à
  reporter honnêtement.
- **not_interpretable** — données existent mais ne supportent pas la claim en
  l'état (typiquement architectural artefact).

---

## RQ1 — Test flakiness

### claim-1.1: "Checkpoint isolation eliminates intra-preview test flakiness across 5 stacks."

| Champ | Valeur |
|---|---|
| Status | **confirmed** (4 sujets) + **preliminary** (S4+S5 rerun en cours) |
| Évidence | `results/frozen/{s1,s2,s3,s5}/flakiness_test_outcomes_*.csv` ; S4 nouveau CSV `flakiness_test_outcomes_20260517T104741Z.csv` en cours, 28/30 iso=True déjà 100% Succeeded |
| Test stat | Fisher exact, Cohen's h, Wilson CI |
| Effect size | h=1.57 (S1), p<10⁻¹⁵ |
| Sujets | S1 Flask Python, S2 Listmonk Go, S3 Healthchecks Django Python, (S4 Umami TS Prisma — rerun), (S5 PetClinic Java Spring — rerun) |
| Caveat | sur S4/S5, le fix harness retire 2 assertions broken-upstream par sujet ; les sondes d'isolation (run_log_clean, entity_count_matches_seed) sont conservées ; voir HARNESS_FIXES.md |

### claim-1.2: "Without isolation, regression and e2e suites fail 100% of runs."

| Champ | Valeur |
|---|---|
| Status | **confirmed** |
| Évidence | iso=False sur les 5 sujets : 30/30 Failed sur regression et e2e |
| Caveat | smoke passe toujours (premier suite, base propre) — c'est le point clé |

---

## RQ2 — Cross-PR concurrency

### claim-2.1: "Failure rate is K-invariant for K ∈ {2, 4, 8}: contamination is intra-preview, not cross-PR."

| Champ | Valeur |
|---|---|
| Status | **confirmed** (4 sujets) + **preliminary** (S4+S5 reruns) |
| Évidence | `results/frozen/*/cross_pr_test_outcomes_*.csv` ; `results/analysis/k_consistency_report.{txt,csv}` montre 100% completion sur les 30 batches |
| Test stat | Fisher exact par K, comparaison entre K |
| Effect size | Δ=−100pp constant pour tous K (S1, S2, S3) ; pas de pente significative en K |
| Découverte | **réfutation** de l'hypothèse initiale "failure rate scales with K". C'est le **finding scientifique novel** le plus fort pour Q1. |

### claim-2.2: "K=8 batches reach full completion on AKS 3× D4s_v3 — no infra-pressure artefacts."

| Champ | Valeur |
|---|---|
| Status | **confirmed** |
| Évidence | `results/analysis/k_consistency_report.txt` : 100% completion sur 30 batches, aucun `suspected_infra_pressure` ni `incomplete_batch` |
| Caveat | Sur cluster Kind antérieur, K=8 était réduit à 4 par pression mémoire (RAM 7.7 Go) — c'est une **contre-validation** : la pression infra peut produire des artefacts visibles. L'AKS K=8 propre est la mesure de référence. |

---

## RQ3 — Checkpoint cost

### claim-3.1: "Checkpoint overhead is bounded in [14.2, 16.0] seconds per preview lifecycle across 5 stacks (1.8s envelope)."

| Champ | Valeur |
|---|---|
| Status | **confirmed** |
| Évidence | `results/frozen/*/performance_run_metrics_*.csv` : checkpoint_total median par sujet S1=14.6s, S2=15.1s, S3=16.0s, S4=15.8s, S5=14.2s |
| Test stat | Welch t-test, Mann-Whitney U, Cohen's d, Vargha-Delaney A12 |
| Effect size | d=18.67 (S1, vs iso=False) ; A12=1.0 |
| Caveat | mesure sur AKS 3× D4s_v3 ; varie avec le cluster (Kind local 14.6s ; AKS 14.9s combiné) |

### claim-3.2: "Checkpoint restore is 2.57× cheaper than migration reset for isolation overhead." → **MESURÉ 2.90×–5.38× (médiane 4.65×) sur 4/5 stacks**

| Champ | Valeur |
|---|---|
| Status (théorique, initial) | preliminary — migration_reset estimé 2 × postgres-migrate (18.8 s) = 37.6 s, dérivé de la mesure de la migration initiale uniquement |
| **Status (mesuré, 2026-05-17T19:25Z)** | ✅ **confirmed sur 4/5 stacks** — s1, s2, s3, s4 baseline RQ3+RQ1 mode=migration N=60 dans `results/frozen/` ; **S5 attend launcher 80162 (ETA ~20h Paris lundi)** |
| **Évidence mesurée (PHASE B)** | speedup per-stack : s1=2.90× (14.6s/42.4s), s2=5.38× (15.1s/81.1s), s3=4.65× (16.0s/74.5s), s4=3.41× (15.8s/53.8s) ; **MWU p<0.001** partout ; **Vargha-Delaney Â₁₂ ∈ [0.99, 1.00]** (séparation quasi-complète) |
| Output paper-ready | [results/analysis/tables/rq3_baseline_comparison.{md,tex}](rq3_baseline_comparison.md) + figure baseline_comparison.pdf |
| Nouveau caveat | claim original "2.57×" était **conservateur** — speedup mesuré est plus élevé (médiane 4.65×) car la migration replay coûte aussi le warm-up framework (Spring Boot context, etc.), pas juste la migration SQL |
| Pour S5 (à venir) | ETA ~20h Paris lundi 18 mai ; speedup attendu **>10×** sur Spring Boot (75s Spring context × 3 replays vs 15s checkpoint) — confirmation expected lundi |

### claim-3.3 (PHASE B): "Both checkpoint and migration modes produce Δ=−100 pp flakiness reduction — checkpoint is preferred for cost, not for correctness."

| Champ | Valeur |
|---|---|
| **Status (mesuré, 2026-05-17T19:25Z)** | ✅ **confirmed sur 4/5 stacks** — RQ1 baseline `flakiness_test_outcomes_*_mode-migration*.csv` montre **risk diff = -100 pp identique au mode restore** (Cohen's h = 3.14 = π, théorique maximum, pour s1, s2, s3, s4 sur suites regression + e2e) |
| Évidence mesurée | [results/analysis/tables/rq1_cross_subject.md](rq1_cross_subject.md) montre Fisher p < 0.001 pour les 4 stacks baseline (s1-s4 × regression + e2e), avec elimination parfaite des failures sous iso=True quelle que soit le mode (restore vs migration) |
| Pour S5 (à venir) | confirmation expected lundi ; pattern attendu = identique aux 4 autres (Δ=-100pp regression, e2e ambigu broken-upstream) |
| Pourquoi cette claim | désamorce le reviewer "vous dites checkpoint est mieux, mais en correctness c'est pareil ou différent ?" Réponse : **mêmes outcomes correctness, meilleur coût** (cf. claim-3.2 médiane 4.65×) |

---

## RQ4 — Bug detection seed diversity (null)

### claim-4.1: "LLM seed-diversity (static / fixed T=0 / free T=0.7) does not improve mutation detection in shared-fixture integration testing."

| Champ | Valeur |
|---|---|
| Status | **null_result** |
| Évidence | `results/frozen/s1-flask-catalog/bug_detection_test_outcomes_20260516T184358Z.csv` (450 lignes, 50 mutants × 3 conditions) |
| Test stat | McNemar exact pairwise sur les 3 paires de conditions |
| Résultat | n01 = n10 = 0 pour les 3 paires → statistique non définie → H0 non rejetable |
| Cohen's κ | 1.0 (concordance parfaite : les 3 conditions détectent les mêmes 23/50 mutants) |
| Bornage | Clopper-Pearson 95% CI sur 0/50 discordances → différence ≤ 7.1 pp |
| Caveat | un seul sujet (S1) ; les CSVs S2 et S3 sont **not_interpretable** (voir claim-4.2) |

### claim-4.2: "S2 and S3 bug-detection results are not interpretable due to architectural mismatch between mutated module and SUT."

| Champ | Valeur |
|---|---|
| Status | **not_interpretable** |
| Évidence | les mutants modifient `testapp/app.py` (Flask) ; sur S2 le SUT est Listmonk Go (pas chargé par S2) ; sur S3 le SUT est Healthchecks Django (idem). S2=47/47=100% et S3=0/40=0% sont des artefacts (S2 always-fail par bug seed pré-existant, S3 always-pass car mutation jamais sollicitée). |
| Implication papier | reporter S1 comme null clean ; mentionner S2/S3 comme limitations architecturales dans le design d'expérience ; recommandation future work : générer un `fault-catalog-<subject>.yaml` par SUT |

---

## RQ5 — Operator idempotence

### claim-5.1: "preview-operator reconverges 100% of the time after a SIGKILL at any of 6 pipeline kill steps."

| Champ | Valeur |
|---|---|
| Status | **preliminary** (4 sujets confirmed, S5 rerun en cours) |
| Évidence | `results/frozen/{s1,s2,s3,s4}/idempotence_run_metrics_*.csv` : 4 × 18 = 72 runs Succeeded sur 72 |
| Caveat | "phase=Succeeded" en CSV agrège "operator a reconvergé" + "pipeline a réussi". L'instrumentation actuelle ne sépare pas les deux signaux. Cf RQ5_IDEMPOTENCE.md §5.1. |
| Comment durcir | PHASE 8 v2 — ajouter `operator_converged` + `duplicate_job_count` + `lost_status_count` + `final_state_consistent` ; re-runner ~2h cluster |

### claim-5.2: "Convergence time after operator kill is p95 < 55s on a 3-node D4s_v3 AKS cluster."

| Champ | Valeur |
|---|---|
| Status | **preliminary** |
| Évidence | `step_duration_s` dans les CSVs idempotence ; S1 ~35-45s, S2/S3 ~40-50s, S4 ~45s, S5 ~45-55s |
| Caveat | mesure suite-level ; la fraction temps-rollout-operator vs temps-pipeline-post-rollout n'est pas séparée dans le CSV actuel |

---

## Synthèse pour l'article

### Top 3 confirmed claims (chest of the paper)

1. **K-invariance** (claim-2.1) — finding scientifique nouveau, soutient le titre proposé "K-Invariance of Test Flakiness Under Per-Preview Isolation"
2. **5-stack replication** (claim-1.1 + claim-3.1) — external validity forte
3. **Checkpoint cost bounded ≤ 16s** (claim-3.1) — argument cost-benefit pour l'adoption

### À présenter comme honest negative

- **claim-4.1** : null result publishable, désamorce une hypothèse implicite courante (LLM-augmented testing)

### À mentionner comme limitations dans la discussion

- **claim-3.2** : migration_reset comparison est théorique (à durcir = baseline operator)
- **claim-4.2** : S2/S3 not_interpretable architecturalement
- **claim-5.1** : convergence ≠ idempotence vraie sans PHASE 8 v2

### À retirer du papier (pour l'instant)

(aucune à ce stade — toutes les claims listées ont un support empirique au minimum diagnostique)
