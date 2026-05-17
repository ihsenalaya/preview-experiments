# AUDIT — état du dépôt pour préparation TSE-ready

**Date** : 2026-05-17
**Phase** : 0 (audit initial, pas de modification du code existant)
**Source** : exploration in-situ, sans lecture de tracker live

## 1. Inventaire des résultats

### 1.1 Structure physique

```
results/
├── *.csv                                    # legacy top-level (14-15/05), historiques
├── logs/                                    # logs d'exécution
├── s1-flask-catalog/
│   ├── flakiness_test_outcomes_*.csv
│   ├── cross_pr_test_outcomes_*.csv
│   ├── performance_run_metrics_*.csv
│   ├── idempotence_run_metrics_*.csv
│   └── bug_detection_test_outcomes_*.csv
├── s2-listmonk/
├── s3-healthchecks/
├── s4-umami/
└── s5-petclinic/
```

CSVs émis par `harness/results_writer.py` ; chemin = `results/<subject_id>/<experiment>_<schema>_<timestampUTC>.csv`.

### 1.2 Schémas figés (`harness/results_writer.py`)

| schema | colonnes |
|---|---|
| `run_metrics` | run_id, experiment, subject_id, preview_name, namespace, isolation_enabled, phase, step, step_duration_s, total_reconcile_s, requeue_count, timestamp_utc |
| `test_outcomes` | run_id, experiment, subject_id, preview_name, isolation_enabled, suite, test_name, outcome, db_rows_before, db_rows_after, timestamp_utc |
| `resource_usage` | run_id, experiment, subject_id, preview_name, namespace, timestamp_utc, cpu_millicores, mem_mib (non utilisé jusqu'ici) |

Conséquences :
- les CSVs sont **stables au niveau schéma** entre versions de harness
- `test_outcomes` reporte au niveau suite (`test_name == suite` dans cross_pr), pas au niveau assertion
- `run_metrics` couvre RQ3 (performance) et RQ5 (idempotence) avec les **mêmes colonnes**, ce qui peut prêter à confusion à l'analyse

### 1.3 CSVs explicitement marqués OBSOLETE (suffixe dans le nom)

| Fichier | Sujet | Raison |
|---|---|---|
| `flakiness_test_outcomes_20260516T144205Z.OBSOLETE_SEEDCOUNT3.csv` | S2 | SEED_COUNT=3 hard-coded au lieu de 5 ; assertion `*_matches_seed` faussement échouée. Corrigé en `:v2.5.1-fix2`. |
| `flakiness_test_outcomes_20260516T144225Z.OBSOLETE_broken_assertions.csv` | S4 | `teams_list` + `website_stats` broken-upstream. Corrigé en `:v2.15.1-fix` puis `:v2.15.1-fix2`. |
| `flakiness_test_outcomes_20260516T164554Z.OBSOLETE_readiness_race.csv` | S5 | wrapper.py ouvrait le proxy avant que Spring Boot ne soit prêt → race conditions. Corrigé en `:v3.4.0-fix4`. |
| `performance_run_metrics_20260516T164617Z.OBSOLETE_readiness_race.csv` | S5 | idem. |

### 1.4 CSVs OBSOLETE implicites (à marquer manuellement)

Identifiés par analyse de contenu, **non encore renommés** :

| Fichier | Sujet | Cause | Suite-action proposée |
|---|---|---|---|
| `idempotence_run_metrics_20260517T064531Z.csv` | S3 | crash harness à 14/18 runs (resilient wrappers absents avant fix `3532d83`) | renommer en `.OBSOLETE_harness_crash.csv` |
| `idempotence_run_metrics_20260517T083851Z.csv` | S4 | 18/18 runs avec ancienne image `:v2.15.1-fix` (broken assertions) → 0/18 Succeeded artificiel | renommer en `.OBSOLETE_broken_image.csv` |
| `idempotence_run_metrics_20260517T091308Z.csv` | S5 | 18/18 runs avec ancienne image `:v3.4.0-fix4` (broken assertions) → 0/18 Succeeded artificiel | renommer en `.OBSOLETE_broken_image.csv` |
| `bug_detection_test_outcomes_20260516T172534Z.csv`, `…175847Z.csv`, `…182440Z.csv` | S1 | partial runs avant le run principal `…184358Z.csv` (50/50) | renommer en `.OBSOLETE_partial.csv` |
| `cross_pr_test_outcomes_20260515T190940Z.csv` (S3) | S3 | partial 7 rows, pré-fix | renommer en `.OBSOLETE_partial.csv` |

Le script PHASE 1 doit **les détecter automatiquement** (pas dépendre d'un renommage humain).

### 1.5 CSVs final, paper-ready (par RQ × sujet)

| RQ | S1 | S2 | S3 | S4 | S5 |
|---|---|---|---|---|---|
| RQ1 Flakiness | `flakiness_test_outcomes_20260516T145451Z.csv` (Kind+AKS combiné) | `…184845Z.csv` (post-fix2) | `…144647Z.csv` | 🔄 en cours (rerun avec fix2) | 🔄 à venir (rerun avec fix5) |
| RQ2 Cross-PR K=8 | `cross_pr_test_outcomes_20260516T234202Z.csv` | `…235356Z.csv` | `…000516Z.csv` | 🔄 en cours | 🔄 à venir |
| RQ3 Performance | `performance_run_metrics_20260516T145456Z.csv` | `…154352Z.csv` | `…154357Z.csv` | `…144239Z.csv` | `…195529Z.csv` |
| RQ4 Bug-detection | `bug_detection_test_outcomes_20260516T184358Z.csv` (50/50) | `…225625Z.csv` (47/50, artefact arch.) | `…030029Z.csv` (47/50, artefact arch.) | — | — |
| RQ5 Idempotence | `idempotence_run_metrics_20260517T071425Z.csv` | `…060920Z.csv` | `…080328Z.csv` (re-run propre) | 🔄 `…101529Z.csv` (8/8 Succeeded en cours) | 🔄 à venir |

## 2. Scripts existants

### 2.1 `analysis/` (déjà en place — à étendre, pas à dupliquer)

| Fichier | Lignes | Format | Rôle |
|---|---|---|---|
| `01_flakiness.py` | 74 | jupytext py:percent | RQ1 — failure rate + Fisher + Cohen |
| `02_cross_pr.py` | 79 | jupytext | RQ2 — par K |
| `03_performance.py` | 95 | jupytext | RQ3 — durations + Mann-Whitney |
| `04_bug_detection.py` | 72 | jupytext | RQ4 — McNemar |
| `05_idempotence.py` | 78 | jupytext | RQ5 — convergence/divergence |
| `shared/{stats,plotting,latex}.py` | — | — | helpers communs |
| `requirements.txt` | — | — | scipy 1.13.1, matplotlib 3.9.0, pandas 2.2.2, jupytext 1.16.3 |
| `figures/` | — | — | dossier de sortie |

⚠️ **Important** : ne PAS dupliquer ces scripts. La PHASE 6 du prompt (build_all.py) doit les orchestrer ou les remplacer en gardant la même logique.

### 2.2 Scripts ad-hoc à la racine (à classer / ranger plus tard)

- `_analyze_bug_det.py` `_analyze_cross_pr.py` `_analyze_subject.py` — analyses ponctuelles utilisées pendant le développement
- `_run_one_subject.py` `_run_bug_detection_*.py` `_run_cross_pr_*.py` — runners spécialisés
- `_launch_*.sh` `_diag_*.sh` — orchestrateurs sequence + watchers utilisés cette session

Statut : **fonctionnels** mais devraient migrer sous `scripts/` ou `tools/` pour propreté TSE (Phase 9 doc).

## 3. Tests S1-S5 — assertions

| Sujet | smoke | regression | e2e | Total |
|---|---|---|---|---|
| S1 flask-catalog | 5 | 11 | 8 | 24 |
| S2 listmonk | 5 | 11 | 8 | 24 |
| S3 healthchecks | 3 | 9 | 8 | 20 |
| S4 umami | 4 | 8 | 7 | 19 (après fixes :v2.15.1-fix2) |
| S5 petclinic | 5 | 11 | 7 | 23 (après fixes :v3.4.0-fix5) |

**Pas d'instrumentation assertion-level dans les CSVs actuels** — c'est la cible de PHASE 2. Les sorties par-assertion existent seulement dans `kubectl get preview -o yaml | jq .status.tests.<suite>.output` (texte non structuré, ephémère, supprimé avec le Preview).

## 4. Génération des résultats suite-level

Chaîne (5 expériences identiques en structure) :
1. `exp_<X>/run.py` boucle sur sujets × conditions × runs
2. À chaque run, crée un Preview CR, attend phase terminale
3. Lit `kubectl get preview … -o jsonpath='{.status.tests.<suite>.phase}'`
4. Écrit **1 ligne par suite** dans `RunWriter("test_outcomes", EXPERIMENT)` → `outcome ∈ {Succeeded, Failed}`
5. Supprime le Preview

⚠️ La granularité est **suite-level** : `outcome=Failed` = au moins 1 assertion a fail dans cette suite. **Aucune trace par-assertion ne survit au cycle de vie du Preview** en l'état actuel.

## 5. RQ5 idempotence — code

`exp_idempotence/run.py` :

| Élément | Détail |
|---|---|
| Kill steps configurés | `saving`, `smoke`, `restore-regression`, `regression`, `restore-e2e`, `e2e` (6 steps) |
| Restarts par step | 3 (`n_restarts_per_step` dans config.yaml) |
| **Méthode kill** | `kubectl delete pods -l control-plane=controller-manager --wait=false` |
| **Méthode wait** | `kubectl rollout status deployment/preview-operator --timeout=120s` |
| Métriques actuelles | `phase`, `step` (kill step), `step_duration_s`, `total_reconcile_s`, `requeue_count` (0 or 1) |

**Risques de concurrence** (déjà observés deux fois dans cette session) :
1. Quand `kill_operator_pod` s'exécute, le **webhook validating** devient injoignable pendant le rollout (~10-20s) → tout `kubectl apply Preview` concurrent retourne non-zero exit → `harness/preview_factory.create()` raisait `CalledProcessError` jusqu'au fix `3532d83` (resilient wrappers).
2. `get_tests_step` / `get_phase` ont le même risque, fixés dans le même commit.
3. Conclusion : **RQ5 doit tourner SEUL** (déjà documenté dans `EXPERIMENT_METRICS.md` "Contraintes de parallélisme"). PHASE 7 doit ajouter un **lock fichier** pour rendre la contrainte mécanique.

**Métriques manquantes pour TSE-niveau** :
- `operator_unavailable_sec` (mesure réelle, pas just step_duration_s)
- `webhook_unavailable_sec`
- `duplicate_job_count` (idempotence vraie : pas de Job dupliqué après reprise)
- `lost_status_count` (status.tests.* préservé après reprise)
- `orphaned_resource_count`
- `final_state_consistent` (boolean comparant état pré/post)

→ **PHASE 8 nécessite re-runner toute RQ5** avec instrumentation enrichie. ~2h cluster.

## 6. Inconsistances / risques identifiés

1. **Confusion S2 RQ1 OLD** : le CSV principal `flakiness_test_outcomes_20260516T184845Z.csv` est post-fix2 et passe. Mais le CSV `.OBSOLETE_SEEDCOUNT3.csv` montre Failed à 100%. Si l'analyse mélange les deux, résultat faux. → consolidate doit exclure par suffixe OBSOLETE.
2. **S3 RQ5 partiel** : 14/18 runs avec ancien harness. Newer 18/18 existe (`20260517T080328Z.csv`). Sans détection automatique, l'analyse risque de prendre le plus ancien ou de cumuler.
3. **S4/S5 RQ5 avec image cassée** : tous Failed mais l'operator a en fait convergé. Les CSVs `…083851Z.csv` (S4) et `…091308Z.csv` (S5) doivent être marqués obsolete par le re-run en cours.
4. **K déclaré vs observé** : pas vérifié automatiquement. PHASE 5 doit comparer `n_previews_par_batch` au paramètre K du run.
5. **Pas de validation de doublons run_id** : si deux runs collident sur uuid (extrêmement rare mais possible avec hash 8-char), aucune erreur.
6. **Mix d'images sujet dans un même CSV** : pas détectable depuis le CSV seul (image n'est pas une colonne). Inférable depuis le timestamp + le tag déployé à ce moment.

## 7. Plan de modification (validation requise avant PHASE 1)

### PHASE 1 — `scripts/consolidate_results.py`

#### Fichiers à créer
- `scripts/consolidate_results.py` (nouveau)
- `results/frozen/` (généré, gitignore-friendly)
- `results/frozen/MANIFEST.json` (généré)
- `results/frozen/excluded_datasets.csv` (généré)
- `AUDIT.md` (ce fichier — déjà créé)

#### Fichiers NON modifiés
- Aucun fichier existant. C'est purement additif.

#### Logique du script

```
SCAN /results et /results/<subject>:
  Pour chaque *.csv:
    - calcule SHA-256, line_count, mtime, taille
    - parse le filename → (experiment, schema, timestamp, subject_id, optional_marker)
    - lit le header → vérifie qu'il match le schema attendu (harness/results_writer.py _SCHEMAS)
    - infère le RQ depuis l'experiment :
        flakiness    -> RQ1
        cross_pr     -> RQ2
        performance  -> RQ3
        bug_detection-> RQ4
        idempotence  -> RQ5
    - inspecte le contenu pour:
        - subjects présents (group by subject_id)
        - conditions iso présentes (group by isolation_enabled)
        - K observés (parse run_id pour cross_pr)
        - completeness (vs target N_RUNS_PER_CONDITION = 30 pour flak, 14 pour cross_pr, etc.)
        - presence of OBSOLETE marker in filename (.OBSOLETE_xxx.csv)
        - presence of run_id duplicates

CLASSIFICATION (status):
  - explicit OBSOLETE in filename     -> obsolete
  - filename contains "diag" or "test"-> diagnostic
  - line_count < HEADER + 5           -> partial
  - target N not met                  -> partial
  - bug_detection mutants < 10        -> partial
  - else                              -> final  (or candidate-final)

  Si plusieurs candidate-final pour (subject × experiment) :
    -> garde le plus complet (line_count max) comme final
    -> les autres -> obsolete (raison: superseded by newer/larger)

FROZEN OUTPUT:
  Pour chaque file classified "final":
    - copy to results/frozen/<subject>/<experiment>_<schema>_<timestamp>.csv
    - record entry dans MANIFEST.json

EXCLUSIONS:
  Pour chaque file NOT in final:
    - record dans excluded_datasets.csv : src, status, reason, sha256, line_count

INCONSISTENCIES WARNINGS (printed + saved):
  - conditions iso manquantes
  - sujet manquant pour une expérience
  - K déclaré ≠ K observé
  - colonnes inattendues
  - run_id duplicates
  - timestamp mismatch (ex: 2x final pour même scope)
```

#### Critères d'acceptation PHASE 1
- [ ] `results/frozen/MANIFEST.json` existe, parseable, liste tous les CSVs final
- [ ] `results/frozen/excluded_datasets.csv` existe avec raison pour chaque exclusion
- [ ] Tous les CSVs explicitement OBSOLETE_* sont exclus
- [ ] S3 RQ5 partial 14/18 est exclu (status=partial OU obsolete)
- [ ] S4 RQ5 broken image est exclu (sera marqué après rename ou par règle "0 Succeeded sur 18 = suspect")
- [ ] Aucun CSV original n'est modifié ou supprimé (test : `git status` après run ne montre que les nouveaux fichiers dans `results/frozen/` et `scripts/`)
- [ ] Script idempotent : 2 runs successifs produisent le même MANIFEST (modulo timestamps de run)

#### Risques PHASE 1
| Risque | Mitigation |
|---|---|
| Faux positif "obsolete" (un fichier "final" classé partial) | Logguer warning + permettre override manuel via `.consolidate_override.yaml` (PHASE 1 v2) |
| Le script lit `EXPERIMENT_METRICS.md` par erreur | **interdiction explicite** dans le code (assertion) |
| Le script touche `EXPERIMENT_METRICS.md` ou un CSV | **interdiction explicite** dans le code (assertion path) |
| Détection "broken-image" S4 RQ5 difficile sans heuristique | Renommer manuellement avant run du script (déjà fait pour les 4 OBSOLETE existants) ; règle "0/N Succeeded = warning, pas exclusion auto" |

#### Ordre des commits proposé
1. `feat(audit): add AUDIT.md — phase 0 findings`
2. `feat(scripts): add consolidate_results.py — phase 1 freeze logic`
3. `chore(results): rename implicit-obsolete CSVs with .OBSOLETE_* suffix` (S3 partial, S4/S5 broken image)
4. `chore: run consolidate, commit results/frozen/MANIFEST.json + excluded_datasets.csv` (initial snapshot)

### Phases ultérieures (à valider séparément)

| Phase | Estimation | Notes |
|---|---|---|
| 2 — assertion-level | 2-3 j | requires re-run pour collecter (touche tests harness) |
| 3 — DB-state hash | 2 j | nouveau collecteur read-only postgres |
| 4 — harness fixes | ~0.5 j docs | code déjà appliqué (S2/S4/S5), reste HARNESS_FIXES.md |
| 5 — K-consistency | 0.5 j | analyzer pur, pas de re-run |
| 6 — build_all.py | 3-5 j | grosse pipeline d'analyses + tables + figures |
| 7 — RQ5 lock | 0.5 j | fichier lock + enforcement |
| 8 — RQ5 instrumentation | 1-2 j + 2h cluster | besoin re-run RQ5 avec nouveau collecteur |
| 9 — docs (REPRODUCE, HARNESS_FIXES, DATASET_POLICY, RQ5_IDEMPOTENCE) | 1 j | textuel |
| 10 — paper_claims / limitations / tse_readiness | 0.5 j | synthèse |

**Total restant après PHASE 1** : 11-15 jours pleins avec IA-assist.
