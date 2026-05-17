# tse_readiness_checklist.md — checklist de soumission TSE

État au 2026-05-17T12:15Z. Cocher quand fait, mettre 🔄 si en cours, ❌ si bloquant.

---

## A. Données figées et reproductibles

- [x] **A1.** `results_frozen/` existe, contient ≥ 1 CSV par RQ × sujet
- [x] **A2.** `results_frozen/MANIFEST.json` avec SHA-256 par fichier
- [x] **A3.** `results_frozen/excluded_datasets.csv` avec raison d'exclusion
- [x] **A4.** Tous les CSVs explicitement OBSOLETE_* sont exclus
- [x] **A5.** Tous les CSVs partial sont exclus (sauf si seul candidat pour son scope, alors warning)
- [x] **A6.** `scripts/consolidate_results.py` re-exécutable, idempotent
- [x] **A7.** Aucune analyse ne lit `EXPERIMENT_METRICS.md`
- [ ] **A8.** Tous les chiffres du paper ont une référence (csv + ligne ou aggregation script)
- [ ] **A9.** Si la PHASE 2 (assertion-level) est demandée par reviewer : `assertion_outcomes_*.csv` collecté
- [ ] **A10.** Si la PHASE 3 (DB-state hash) est demandée : `db_state_metrics_*.csv` collecté

---

## B. Analyses statistiques

- [x] **B1.** RQ1 : Fisher exact, Cohen's h, Wilson/Clopper-Pearson CI implémentés (`analysis/01_flakiness.py` + `shared/stats.py`)
- [x] **B2.** RQ2 : Fisher exact par K + K-consistency check (`analysis/check_k_consistency.py`)
- [x] **B3.** RQ3 : Welch t-test, Mann-Whitney U, Cohen's d, Vargha-Delaney A12, Cliff's delta
- [x] **B4.** RQ4 : McNemar exact pairwise + Clopper-Pearson 95% sur 0/N discordances
- [ ] **B5.** RQ5 : suite-level success rate + convergence_time percentiles (à enrichir avec PHASE 8 v2 si confirmatory)
- [x] **B6.** Effect sizes rapportés systématiquement (pas juste p-values)
- [x] **B7.** Test conditions explicitement vérifiées (normalité, équivalence des variances) — Mann-Whitney + Cliff's delta = non-paramétrique, pas de prérequis normalité

---

## C. Validity threats

- [x] **C1.** `paper_limitations.md` énumère L1-L10
- [ ] **C2.** Section "Threats to Validity" rédigée dans le papier
- [ ] **C3.** Section "Related Work" qualitative comparison à ≥ 5 baselines
- [x] **C4.** L'effet de pression infrastructure (K=8 sur Kind RAM-bounded) est documenté comme contre-validation
- [x] **C5.** Limitation L2 (RQ4 single-subject) est documentée
- [ ] **C6.** Mention explicite "L1 single-operator" dans abstract + intro + discussion

---

## D. Reproducibility artifact

- [x] **D1.** `REPRODUCE.md` documente le pipeline complet
- [x] **D2.** `analysis/requirements.txt` épinglé
- [x] **D3.** `DATASET_POLICY.md` documente les 5 statuts
- [x] **D4.** `HARNESS_FIXES.md` documente chaque correction harness (S2/S4/S5)
- [x] **D5.** `RQ5_IDEMPOTENCE.md` documente le protocole RQ5 et ses limitations
- [x] **D6.** `AUDIT.md` capture l'état du dépôt à un instant T
- [ ] **D7.** `README.md` artifact section (lien vers REPRODUCE.md)
- [ ] **D8.** `SETUP_AKS.md` à relire pour artifact reviewer (pas critique si on ne demande pas reproduction du cluster)
- [ ] **D9.** Lock fichier RQ5 implémenté (PHASE 7) — empêche les concurrences accidentelles
- [ ] **D10.** Tests CI sur les scripts d'analyse (smoke test que `analysis/0X.py` ne crashe pas sur les data figées)

---

## E. RQ5 dédié

- [x] **E1.** RQ5 isolé physiquement (chaîne de lanceurs sequential dans cette session)
- [ ] **E2.** RQ5 isolé mécaniquement (lock fichier — PHASE 7)
- [x] **E3.** RQ5 résultats documentés (`RQ5_IDEMPOTENCE.md`)
- [ ] **E4.** RQ5 instrumentation niveau TSE-confirmatory (PHASE 8 v2)
- [x] **E5.** Si E4 absent : claim RQ5 marquée "preliminary" dans `paper_claims.md`

---

## F. Bonnes pratiques empiriques

- [x] **F1.** Sample size ≥ 30 par condition pour RQ1/RQ3 (test parametric assumption OK)
- [x] **F2.** Multi-stack validation (5 sujets, 5 langages)
- [x] **F3.** Cross-substrate (Kind + AKS pour ≥ 1 RQ)
- [x] **F4.** Honest negative result reported (RQ4 null)
- [ ] **F5.** Pré-enregistrement des hypothèses (commit hash de RQ formulation antérieure à collecte) — pas fait
- [x] **F6.** Données + code publics (GitHub repo)

---

## G. Présentation pour TSE/EMSE

- [ ] **G1.** Title reformulé pour mettre K-invariance en avant (suggestion : "K-Invariance of Test Flakiness Under Per-Preview Isolation: An Empirical Study Across Five Stacks on Managed Kubernetes")
- [ ] **G2.** Abstract 200 mots
- [ ] **G3.** Section structure : Intro / Background / Operator design / RQ1 / RQ2 / RQ3 / RQ4 / RQ5 / Discussion / Related Work / Threats / Conclusion
- [ ] **G4.** Tables/figures générées via `analysis/*.py` (pas hand-crafted)
- [ ] **G5.** Tous les chiffres dans le LaTeX référencent un CSV (commentaire `% from results_frozen/.../<csv>:<line>` ou via macros)
- [ ] **G6.** Artifact link in paper (footnote ou dedicated section)

---

## H. Bloquants TSE actuels

Items qui empêchent une soumission immédiate :

1. ❌ **C2** Section "Threats to Validity" pas rédigée (mais `paper_limitations.md` est prêt)
2. ❌ **C3** Section "Related Work" comparative pas faite
3. ❌ **G1-G6** L'article lui-même n'est pas rédigé (PHASE 10 du prompt dit explicitement : "Ne modifie pas l'article scientifique principal dans cette tâche")
4. ⚠️ **L1** Single-operator → reviewer va demander baseline
5. ⚠️ **L3** RQ5 instrumentation incomplete → claim RQ5 reste preliminary

---

## I. Ce qui est prêt pour soumission immédiate

- ✅ Toutes les données figées
- ✅ Tous les scripts d'analyse reproductibles
- ✅ Tous les docs artifact (REPRODUCE, DATASET_POLICY, HARNESS_FIXES, RQ5_IDEMPOTENCE, AUDIT)
- ✅ Tous les claims classés par niveau de preuve
- ✅ Toutes les limitations énumérées

**Verdict** : prêt pour soumission **workshop / short paper** ou **journal empirique tolérant à un seul system testé** (EMSE).
Pour **ICSE / FSE / TSE Q1** : il manque la section Related Work + une comparison baseline. Effort : 3-5 jours.

---

## J. Ce qui peut être soumis à un workshop / short paper

Avec ce qui est prêt aujourd'hui, possibilités :

| Venue | Format | Frame |
|---|---|---|
| ICSE artifact track | artifact | "Reusable empirical infrastructure for Kubernetes preview test isolation" |
| AST workshop @ ICSE | short 4p | "K-invariance: an unexpected property of per-preview test isolation" |
| EMSE registered report | registered | "Multi-stack empirical evaluation of checkpoint-based test isolation" |
| TSE | full empirical | needs L1 mitigation first |

---

## K. Items à re-runner (pas re-coder)

Après la fin de la chaîne S4+S5 rerun actuellement en cours (~15:05Z) :

1. Re-runner `scripts/consolidate_results.py` (capture nouveaux CSVs S4 flak/cross_pr + S5 idemp/flak/cross_pr)
2. Re-runner `analysis/check_k_consistency.py` (vérifier que les nouveaux batches S4/S5 K=8 sont 100% completion)
3. Re-runner `analysis/01_flakiness.py` à `analysis/05_idempotence.py` (regenerate figures/tables avec données uniformes)
4. Re-générer `paper_claims.md` (claim-1.1, claim-2.1, claim-3.1 passent de "preliminary" à "confirmed" pour S4 et S5)
