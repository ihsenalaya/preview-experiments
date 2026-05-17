# RQ5_IDEMPOTENCE.md — protocole, métriques, et interprétation

**Question de recherche RQ5** : *Quand l'opérateur preview-operator est tué pendant un step arbitraire du pipeline de test, est-ce qu'il converge vers le même état final que sans interruption, en un temps raisonnable, sans créer de ressources orphelines ?*

C'est une question d'**idempotence** au sens K8s controller-runtime (la reconciliation doit être idempotente) et de **convergence** sous panne (le rolling restart d'un Deployment doit être transparent du point de vue du Preview en cours).

---

## 1. Pourquoi RQ5 est séparée des autres expériences

### 1.1 Contrainte technique : RQ5 tue le pod de l'opérateur

L'expérience consiste à `kubectl delete pods -l control-plane=controller-manager` à des moments choisis du cycle de vie d'un Preview. Pendant le rollout (~10-20s), le **webhook validating admission** de l'operator est injoignable. Tout `kubectl apply preview` concurrent retourne non-zero.

**Conséquence** : si une autre expérience (`flakiness`, `cross_pr`, `performance`, `bug_detection`) tourne en parallèle, elle subit des crashes harness (`CalledProcessError` ou équivalent) qui contaminent ses CSVs.

### 1.2 Incident historique

L'incident `14:43Z` (2026-05-16) a documenté ce comportement : RQ5 a tué le pod operator à un moment où `flakiness-S3` et `performance-S3` tournaient en parallèle ; les deux ont crashé sur `kubectl apply Preview` retournant non-zero exit. Les CSVs S3 partiels (~1.6 KB chacun) ont dû être supprimés et l'expérience relancée.

Un second incident (`07:12Z`, 2026-05-17) a montré que même la boucle de polling interne de l'idempotence (`get_tests_step`) pouvait crasher si le webhook devenait transitoirement injoignable. Fix harness `3532d83` a ajouté des wrappers résilients (`get_tests_step` + `get_phase` retournent `""` après 5 retries avec backoff 2s au lieu de raise).

### 1.3 Règle dure

> **RQ5 doit tourner SEULE.** Aucune autre expérience ne doit créer ou interroger des Previews pendant qu'une run RQ5 est en cours.

PHASE 7 du plan TSE implémente cette règle via un fichier lock (`.experiment_lock`).

---

## 2. Protocole expérimental

### 2.1 Configuration

| Paramètre | Valeur | Source |
|---|---|---|
| `kill_steps` | `saving`, `smoke`, `restore-regression`, `regression`, `restore-e2e`, `e2e` (6 steps) | `config.yaml` `experiments.idempotence.kill_steps` |
| `n_restarts_per_step` | 3 | `config.yaml` `experiments.idempotence.n_restarts_per_step` |
| `timeout_minutes` | 30 (par run) | `config.yaml` |
| Sujets | 5 (S1, S2, S3, S4, S5) | `config.yaml` `subjects.enabled` |
| **Total runs par sujet** | **18** = 6 × 3 | |
| **Total runs sur 5 sujets** | **90** | |

### 2.2 Boucle (`exp_idempotence/run.py`)

Pour chaque sujet × chaque kill_step × chaque répétition :

1. **Create** un Preview CR avec `isolation_enabled: true` ; nom unique `idem-<8hex>`
2. **Poll** `kubectl get preview ... -o jsonpath='{.status.tests.step}'` jusqu'à voir `step == kill_step`
3. **Kill** : `kubectl delete pods -n preview-operator-system -l control-plane=controller-manager --wait=false`
4. **Wait restart** : `kubectl rollout status deployment/preview-operator --timeout=120s`
5. **Wait convergence** : `factory.wait_until_phase(target=[Running, Failed], timeout=30min)` puis `factory.wait_until_tests_done(timeout=30min)`
6. **Record** une ligne dans `idempotence_run_metrics_<TS>.csv` avec :
   - `phase` (final tests phase : `Succeeded` ou `Failed`)
   - `step` (le kill_step)
   - `step_duration_s` (temps du convergence après kill — temps écoulé entre la fin du wait_operator_ready et la fin du wait_until_tests_done)
   - `total_reconcile_s` (temps du rollout operator — kill jusqu'à pod Ready)
   - `requeue_count` (0 si direct ; 1 si l'operator a dû faire un retry)
7. **Delete** le Preview (cleanup)

### 2.3 Hypothèse testée

> **H0** : pour chaque kill_step, le taux de Succeeded sur 3 répétitions est de 3/3 (100%), et `step_duration_s` reste stable (p95 < 60s sur AKS 3× D4s_v3).

**Réfutation** : un kill_step avec ≥ 1 Failed run sur 3 invaliderait l'idempotence pour ce step.

---

## 3. Métriques actuellement capturées (`idempotence_run_metrics_*.csv`)

Schéma identique à RQ3 performance (`harness/results_writer.py` `run_metrics`) :

| Colonne | Type | Sémantique RQ5 |
|---|---|---|
| `run_id` | string | id unique `idempotence-<sub>-step<step>-<rep>-<6hex>` |
| `experiment` | "idempotence" | |
| `subject_id` | string | `s1-flask-catalog` etc. |
| `preview_name` | string | nom du Preview CR créé pour ce run |
| `namespace` | string | namespace runtime calculé du PR number |
| `isolation_enabled` | "true" (toujours) | RQ5 ne teste que iso=True |
| `phase` | "Succeeded" or "Failed" | **outcome final des tests après convergence** |
| `step` | kill_step | quel step a été interrompu |
| `step_duration_s` | float | temps de convergence après kill (sec) |
| `total_reconcile_s` | float | temps du rollout operator (sec) |
| `requeue_count` | 0 ou 1 | 1 si tests_phase=Failed |
| `timestamp_utc` | ISO 8601 | début du run |

**Limitations actuelles** (cibles de PHASE 8) :

- Pas de mesure séparée de `operator_unavailable_sec` vs `webhook_unavailable_sec`
- Pas de `duplicate_job_count` (vérification qu'aucun Job de checkpoint/restore n'a été dupliqué après reprise)
- Pas de `lost_status_count` (vérification que `.status.tests.*` est préservé)
- Pas de `orphaned_resource_count` (ConfigMaps, Jobs, Pods restants après suppression du Preview)
- Pas de `final_state_consistent` (boolean comparant l'état pré-kill et l'état post-recovery)

---

## 4. Critères d'acceptation pour le papier

### 4.1 Données quantitatives minimales (PHASE 8 v1 — actuel)

Avec les métriques courantes (suite-level phase, step_duration_s, total_reconcile_s), on peut affirmer :

- **Taux de Succeeded** par (sujet, kill_step) — démontre que l'operator reconverge
- **Médiane / p95 de step_duration_s** — démontre la vitesse de convergence
- **Médiane / p95 de total_reconcile_s** — démontre la vitesse de rollout

### 4.2 Données quantitatives pour TSE-confirmatory (PHASE 8 v2 — cible)

Pour une publication TSE solide il faudrait en plus :

- `final_state_consistent`: bool — capturé via `kubectl get preview ... -o yaml` après convergence et comparé à un snapshot pré-kill
- `duplicate_job_count`: int — `kubectl get jobs -n <ns> --field-selector status.successful=1 | grep checkpoint` ne doit pas montrer de duplicates
- `lost_status_count`: int — comparaison `.status.tests` pré/post-kill
- `operator_unavailable_sec`, `webhook_unavailable_sec` — à mesurer via probe externe pendant le kill

Si ces métriques sont absentes :

> "RQ5 cannot support confirmatory claims about controller-runtime idempotence properties because the current instrumentation only captures suite-level convergence outcomes. We report the success rate and convergence time as preliminary evidence; a confirmatory follow-up would require lightweight external probes for webhook and job-duplication monitoring."

---

## 5. État actuel des résultats (2026-05-17)

| Sujet | Kill steps × repetitions | Total Succeeded | CSV final |
|---|---|---|---|
| **S1 Flask** | 6 × 3 = 18 | **18 / 18** | `idempotence_run_metrics_20260517T071425Z.csv` |
| **S2 Listmonk** | 6 × 3 = 18 | **18 / 18** | `idempotence_run_metrics_20260517T060920Z.csv` |
| **S3 Healthchecks** | 6 × 3 = 18 | **18 / 18** | `idempotence_run_metrics_20260517T080328Z.csv` (re-run propre après crash harness précédent) |
| **S4 Umami** | 6 × 3 = 18 | **18 / 18** (rerun avec `:v2.15.1-fix2`) | `idempotence_run_metrics_20260517T101529Z.csv` |
| **S5 PetClinic** | 6 × 3 = 18 | (rerun chaîné après S4, pas encore terminé au moment de ce doc) | à venir avec `:v3.4.0-fix5` |

**Total préliminaire** (sans S5 rerun encore) : 72 / 72 runs Succeeded sur 4 sujets × 6 kill_steps × 3 répétitions.

### 5.1 Distinction critique : "phase=Failed" en CSV ≠ "operator a divergé"

Lors des premières runs S4 et S5 avec **images d'application cassées** (`:v2.15.1-fix` et `:v3.4.0-fix4`), tous les 18 runs ont enregistré `phase=Failed`. Mais cela **ne signifie PAS que l'operator a divergé** : l'operator a bien reconverge à chaque fois (Preview atteint Running, tests jobs créés sans duplication). Ce qui a failed, c'est le pipeline applicatif (test assertion `teams_list` ou `owner_update` broken-upstream).

`scripts/consolidate_results.py` détecte automatiquement ce cas : un CSV idempotence avec ≥ 10 runs et `n_succeeded == 0` est classé `obsolete` avec raison `"0/N Succeeded (all phase=Failed) — suggests broken subject image or environment issue, not operator divergence"`. Les CSVs ré-runs avec les images fixées remplacent les obsoletes.

**Note importante** : à proprement parler, l'instrumentation actuelle confond "tests passent" et "operator a reconvergé". PHASE 8 v2 doit séparer les deux signaux (`operator_converged: bool` indépendant de `pipeline_succeeded: bool`).

---

## 6. Comment lancer RQ5 seule

### Méthode recommandée

```bash
# Vérifier qu'aucune autre expérience ne tourne
ps -ef | grep -E "exp_(flakiness|cross_pr|performance|bug_detection)" | grep -v grep
# Doit être vide.

# Vérifier que le cluster est propre
kubectl get previews -A --no-headers | wc -l   # doit être 0 ou très bas

# Lancer l'idempotence
cd /mnt/c/Users/Ihsen/Documents/kubebuilder/experimentation
python3 -u exp_idempotence/run.py > logs/idempotence-$(date -u +%Y%m%dT%H%M%SZ).log 2>&1 &
echo "RQ5 PID=$!"
```

### Méthode avec scope réduit (un sujet seul)

```bash
# Pour ne lancer RQ5 que sur S4 par exemple :
SUBJECT=s4-umami EXPERIMENT=idempotence python3 -u _run_one_subject.py
```

### Méthode unsafe (à éviter)

❌ **Ne jamais** lancer `exp_idempotence/run.py` pendant que `flakiness`, `cross_pr`, `performance`, ou `bug_detection` tournent — risque crash documenté.

PHASE 7 du plan TSE va implémenter un lock fichier (`.experiment_lock`) avec enforcement dans le code (fail-fast au démarrage si lock présent ou si d'autres procs python exp_* sont actifs).

---

## 7. Risques expérimentaux

| Risque | Détection | Mitigation actuelle | Mitigation cible |
|---|---|---|---|
| **Webhook indisponible pendant rollout** crash autres expés | `CalledProcessError` dans logs harness | resilient wrappers (fix `3532d83`) | RQ5 lock (PHASE 7) |
| **Image SUT cassée** confond le signal "operator failed" et "test failed" | 0/N Succeeded pendant que operator pod est Ready | `consolidate_results.py` détecte et marque obsolete | PHASE 8 v2 : séparer `operator_converged` et `pipeline_succeeded` |
| **Memory pressure** sur le cluster cause OOM pendant convergence | events `OOMKilled` dans le namespace | none (assumption : cluster sain) | PHASE 8 v2 : capturer events Kubernetes pendant la fenêtre kill→ready |
| **Timeout 30min** dépassé sur S5 (PetClinic Spring Boot lent à démarrer) | `TimeoutError` dans log | `wait_until_phase` retourne après timeout, run marqué Failed | PHASE 8 v2 : timeout configurable par sujet |
| **Doublons de Job ConfigMap** post-recovery (vraie violation idempotence) | non détecté actuellement (PAS dans la métrique) | aucune | PHASE 8 v2 : `duplicate_job_count` capturé après chaque kill |

---

## 8. Comment interpréter les résultats

### 8.1 Lecture verdict (par cellule sujet × kill_step)

| `succeeded` / 3 | Interprétation | Action |
|---|---|---|
| 3 / 3 | **Idempotence confirmée** pour ce step sur ce sujet | Aucune ; reporter |
| 2 / 3 | **Flaky** ; investiguer la run Failed (logs operator, events ns) | Tentative reproduction ; si récurrent, marker comme limitation |
| 1 / 3 ou 0 / 3 | **Idempotence violée** pour ce step OU instrumentation insuffisante | Critique : capturer trace operator/events, déterminer si vraie divergence ou autre cause |

### 8.2 Lecture vitesse de convergence

`step_duration_s` mesure le temps entre la fin du rollout operator et la fin du pipeline post-kill. Sur AKS 3× D4s_v3 avec les sujets actuels :

| Sujet | step_duration_s p50 / p95 attendu | Note |
|---|---|---|
| S1 Flask | ~35-45s / ~50s | testapp léger |
| S2 Listmonk | ~35-45s / ~50s | Go binaire rapide |
| S3 Healthchecks | ~40-50s / ~55s | Django startup ~5s overhead |
| S4 Umami | ~40-50s / ~55s | Next.js startup ~5-8s overhead |
| S5 PetClinic | ~45-55s / ~65s | Spring Boot startup ~15s overhead |

Tout dépassement systématique du p95 doit déclencher une investigation (probe pod OOM, scheduler issues, image pull lent).

---

## 9. Place de RQ5 dans le papier

### 9.1 Pour ICSE/FSE

RQ5 est **secondaire** par rapport à RQ1+RQ2+RQ3 (le cœur thèse "checkpoint isolation eliminates flakiness"). Recommandation : section "Operator reliability" en 0.5 page, table récapitulative, citation des données comme "preliminary engineering-grade evidence".

### 9.2 Pour TSE/EMSE (journaux empiriques)

RQ5 peut être un **vrai pilier** si l'instrumentation PHASE 8 v2 est complète (final_state_consistent, duplicate_jobs, lost_status). Sinon, le présenter comme "preliminary" et discuter la limitation en honest negative.

### 9.3 Pour un workshop sur K8s operators

RQ5 + PHASE 8 v2 + comparaison avec d'autres operators (cert-manager, etc.) constituerait un short paper autonome de 4-6 pages.

---

## 10. Références

- `exp_idempotence/run.py` — code de l'expérience
- `harness/preview_factory.py` — wrappers résilients (`get_tests_step`, `get_phase`)
- `harness/results_writer.py` — schéma CSV `run_metrics`
- `results_frozen/s*/idempotence_run_metrics_*.csv` — données figées
- `EXPERIMENT_METRICS.md` "Contraintes de parallélisme" — règle de non-parallélisation
- `HARNESS_FIXES.md` — pourquoi les CSVs avec images `:v2.15.1-fix` et `:v3.4.0-fix4` sont marqués obsolete (broken-image, pas vrai operator failure)
- `AUDIT.md` §5 — détail du code RQ5 actuel et métriques manquantes
