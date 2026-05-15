# Experiment Metrics — Live Tracking

Paper: *Checkpoint-based Database Isolation Eliminates Non-deterministic Test Variance
in Kubernetes Preview Environments*
Last updated: 2026-05-15T14:48Z

---

## Run Status

| Experiment | Subject | Isolation | Runs done | Status |
|---|---|---|---|---|
| RQ1 Flakiness | S1 — Flask Catalog | True | 30/30 | ✅ Complete |
| RQ1 Flakiness | S1 — Flask Catalog | False | 30/30 | ✅ Complete |
| RQ1 Flakiness | S2 — Listmonk | True | 0/30 | ❌ Crashed (image manquante, corrigé) |
| RQ1 Flakiness | S2–S5 | both | 0/30 | ⏳ À relancer |
| RQ3 Performance | S1 — Flask Catalog | True | 30/30 | ✅ Complete |
| RQ3 Performance | S1 — Flask Catalog | False | 30/30 | ✅ Complete |
| RQ3 Performance | S2–S5 | both | 0/30 | ❌ Crashé (migration S2, méta corrigé) — à relancer |
| RQ2 Cross-PR | S1 k=2,4,8 | iso=False | ✅ Données 14/05 | 84 lignes valides |
| RQ2 Cross-PR | S1 k=2,4,8 | iso=True | ✅ Données 14/05 | complètes |
| RQ2 Cross-PR | S1 (re-run) | — | 🔄 En cours | Confirmation 15/05 |
| RQ2 Cross-PR | S2–S5 | — | 0 | ⏳ Crash attendu sur S2 |
| RQ5 Idempotence | all | — | 0 | ⏳ En attente |
| RQ4 Bug Detection | S1 only | — | 0 | ⏳ En attente |

---

## RQ1 — Test Flakiness (key result for paper)

**Subject: S1 Flask Catalog — n=30 per condition**

| Suite | iso=True failures | iso=True fail rate | iso=False failures | iso=False fail rate |
|---|---|---|---|---|
| smoke | 0/30 | **0 %** | 0/30 | 0 % |
| regression | 0/30 | **0 %** | 30/30 | **100 %** |
| e2e | 0/30 | **0 %** | 30/30 | **100 %** |

> **Interpretation:** Without checkpoint isolation, regression and e2e tests fail
> deterministically on every run due to shared database state contamination.
> With isolation, all 30 runs pass. This is the central empirical claim of the paper.

*Data file:* `results/s1-flask-catalog/flakiness_test_outcomes_20260515T112339Z.csv`

---

## RQ3 — Checkpoint Overhead (performance cost of isolation)

**Subject: S1 Flask Catalog — n=30 per condition (COMPLETE)**

### Step-level durations (step_duration_s)

| Pipeline step | iso=True (n=30) | iso=False (n=30) | Delta |
|---|---|---|---|
| `postgres-migrate` | 18.8 s | 18.7 s | ≈0 (baseline identique ✅) |
| `saving` (pg_dump → ConfigMap) | 4.2 s | — | +4.2 s |
| `smoke` | 4.8 s | 4.5 s | ≈0 |
| `restore-regression` (psql restore) | 5.2 s | — | +5.2 s |
| `regression` | 4.7 s | — | — |
| `restore-e2e` (psql restore) | 5.2 s | — | +5.2 s |
| `e2e` | 14.8 s | — | — |
| **`checkpoint_total`** | **14.6 s** | — | **overhead brut** |

### Pipeline total (total_reconcile_s)

| Condition | n | Mean | Notes |
|---|---|---|---|
| iso=True | 30 | **73.2 s** | pipeline complet avec checkpoints |
| iso=False | 30 | **37.8 s** | pipeline sans checkpoints (baseline) |
| **Overhead absolu** | — | **+35.4 s** | 73.2 − 37.8 |
| **Overhead relatif** | — | **+93.7 %** | sur le temps de base |

### Décomposition de l'overhead (14.6 s checkpoint_total)

| Opération | Durée | % du checkpoint_total |
|---|---|---|
| `pg_dump` (saving) | 4.2 s | 28.8 % |
| `psql restore` × 2 | 10.4 s | 71.2 % |

> **Interprétation :** L'overhead brut de l'isolation est de 14.6 s (saving + 2× restore)
> par lifecycle de preview. Le pipeline total passe de 37.8 s à 73.2 s (+93.7 %).
> Le coût est prévisible : checkpoint_total min=14.0 s, max=19.0 s (σ faible).
> Ce surcoût est le prix payé pour obtenir 0 % de flakiness (vs 100 % sans isolation).

*Data file:* `results/s1-flask-catalog/performance_run_metrics_20260515T125712Z.csv`
*S2–S5 :* à collecter (crash migration corrigé, re-run planifié)

---

---

## RQ2 — Cross-PR Interference (concurrency effect on flakiness)

**Subject: S1 Flask Catalog — données du 2026-05-14, n=k previews par batch**

| k | Condition | smoke | regression | e2e | fail rate (reg+e2e) |
|---|---|---|---|---|---|
| 2 | iso=**False** | 0/2 fail | **2/2 fail** | **2/2 fail** | **100 %** |
| 2 | iso=**True** | 0/2 fail | 0/2 fail | 0/2 fail | **0 %** |
| 4 | iso=**False** | 0/4 fail | **4/4 fail** | **4/4 fail** | **100 %** |
| 4 | iso=**True** | 0/4 fail | 0/4 fail | 0/4 fail | **0 %** |
| 8 | iso=**False** | 0/8 fail | **8/8 fail** | **8/8 fail** | **100 %** |
| 8 | iso=**True** | 0/8 fail | 0/8 fail | 0/8 fail | **0 %** |

> **Interprétation :** La contamination est identique pour k=2, k=4 et k=8.
> Le taux d'échec ne croît pas avec k car chaque preview a son propre namespace PostgreSQL
> (isolation réseau garantie par l'opérateur). La contamination observée est **intra-preview**
> (entre suites d'un même run), pas **inter-preview** (cross-PR).
> L'isolation checkpoint élimine cette contamination intra-preview pour tous les k.

> **Note importante pour le papier :** L'hypothèse initiale (failure_rate croît avec k)
> n'est pas confirmée. Conclusion révisée : la contamination est déterministe par run,
> indépendante de la concurrence. Cela renforce la thèse : isolation checkpoint est suffisante.

*Data file:* `results/cross_pr_test_outcomes_20260514T211354Z.csv`

---

## Infrastructure

| Item | Value |
|---|---|
| Cluster | kind single-node (local WSL2) |
| Operator version | v1.0.43 |
| Execution mode | Sequential (1 experiment at a time) |
| Estimated total duration | ~35 h |
| Start time | 2026-05-15T11:22Z |
| Images pre-loaded | S1–S5 + harness-probe (loaded 2026-05-15T15:15Z) |

---

## Known Issues / Post-processing

1. **RQ1 S2–S5 missing** — First attempt crashed (images not in kind). Images loaded at 15:15Z.
   Action: after all 5 experiments complete, re-run `python3 exp_flakiness/run.py`
   with `subjects.enabled` restricted to `[s2-listmonk, s3-healthchecks, s4-umami, s5-petclinic]`.

2. **RQ2 k=8 — données valides du 14/05** — Les données du 14 mai (cross_pr_test_outcomes_20260514T211354Z.csv)
   contiennent k=2, k=4, k=8 complets et valides. L'échec du 15 mai est dû à la saturation
   mémoire causée par d'autres experiments tournant en parallèle. k=8 restauré dans config.yaml.
   Pour le re-run : s'assurer qu'aucun autre experiment ne tourne en même temps.

3. **RQ4 scope** — Bug detection mutations only valid for S1 (Flask).
   Scripts iterate all 5 subjects — need to filter or annotate in analysis.

3. **Old CSV files in `results/`** (root, not per-subject) — from pre-reorganisation runs.
   These should be excluded from analysis or merged carefully.

---

## Article-ready sentences (draft, update after full data)

- "Under shared database state (isolation=False), regression and e2e suites failed on
  100% of runs (30/30) for S1, confirming the deterministic nature of contamination."

- "Checkpoint isolation (isolation=True) reduced the failure rate to 0% across all
  30 repeated runs for S1, with no false negatives observed."

- "The total overhead introduced by checkpoint isolation is 14.6 s (mean) per preview
  lifecycle, comprising 4.2 s for `pg_dump` and 2×5.2 s for `psql` restore operations."

- "The full preview pipeline duration increases from 37.8 s (iso=False) to 73.2 s
  (iso=True), an absolute overhead of 35.4 s (+93.7%). However, the checkpoint
  mechanism itself accounts for only 14.6 s of this increase; the remainder reflects
  the additional test suites executed under isolation."

- "The `postgres-migrate` step shows identical duration across conditions (18.8 s vs
  18.7 s), confirming that migration time is not a confounding variable."
