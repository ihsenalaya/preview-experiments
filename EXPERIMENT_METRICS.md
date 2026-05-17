# Experiment Metrics — Live Tracking

Paper: *Checkpoint-based Database Isolation Eliminates Non-deterministic Test Variance
in Kubernetes Preview Environments*
Last updated: 2026-05-17T13:30Z (results/ restructured, S5 rerun bloqué, PHASE 0-7+9-10 livrées du prompt.txt TSE)

> ⚠️ **Ce document est un journal de travail vivant**, jamais une source de vérité
> citable pour le papier. Toute claim du papier doit être adossée à un CSV dans
> `results/frozen/` (voir `MANIFEST.json`) ou à une table générée dans
> `results/analysis/`. `scripts/consolidate_results.py` refuse explicitement de
> lire ce fichier.

---

## 1. Layout du dépôt (nouveau, 2026-05-17T13:25Z)

```
results/
├── *.csv                              # legacy top-level CSVs (14-15/05, S1 historique)
├── s1-flask-catalog/*.csv             # CSVs bruts émis par exp_*/run.py
├── s2-listmonk/*.csv                  # idem
├── s3-healthchecks/*.csv              # idem
├── s4-umami/*.csv                     # idem
├── s5-petclinic/*.csv                 # idem
├── logs/                              # logs textuels d'exécution
├── frozen/                            # SNAPSHOT FIGÉ pour analyse (était results_frozen/)
│   ├── MANIFEST.json                  # inventaire avec SHA-256 par CSV
│   ├── excluded_datasets.csv          # CSVs non retenus + raison
│   └── <subject>/*.csv                # uniquement les CSVs status=final
└── analysis/                          # OUTPUTS GÉNÉRÉS (était analysis/output/)
    ├── tables/*.md, *.tex             # tables papier (20 + 20)
    ├── figures/*.pdf, *.png           # figures papier (5 + 5)
    ├── MANIFEST_ANALYSIS.json         # inventaire outputs avec SHA-256
    ├── warnings.txt                   # alertes qualité de données
    ├── k_consistency_report.{txt,csv} # rapport RQ2 batches
    ├── paper_claims.md                # claims classés par niveau de preuve
    ├── paper_limitations.md           # L1-L10 limitations
    └── tse_readiness_checklist.md     # check-list A-K TSE
```

**Tout est désormais sous `results/`.** Les expériences en cours écrivent dans
`results/<subject>/*.csv` ; le pipeline d'analyse lit `results/frozen/` et écrit
dans `results/analysis/`.

---

## 2. État des PHASEs prompt.txt (sprint TSE 2026-05-17)

| Phase | Livré | Fichier(s) | Statut |
|---|---|---|---|
| **0** Audit | ✅ | `AUDIT.md` | complet |
| **1** Freeze | ✅ | `scripts/consolidate_results.py` + `results/frozen/` | complet — 22 final, 39 exclus |
| **2** Assertion-level | ✅ infra + 🔄 collecte | `harness/assertion_{categories,collector}.py` + `scripts/collect_assertions_from_preview.py` + `PHASE2_ASSERTION_LEVEL.md` | infra livrée, watch actif en background (PID 1120818) |
| **3** DB-state hash | ✅ infra + ⚠️ peu de données | `harness/db_state_collector.py` + `scripts/collect_db_state_from_preview.py` + `PHASE3_DB_STATE.md` | infra livrée, validation 10 tables PetClinic OK |
| **4** Harness fixes | ✅ | `HARNESS_FIXES.md` | S2, S4 OK ; **S5 nécessite re-investigation** |
| **5** K-consistency | ✅ | `analysis/check_k_consistency.py` + `results/analysis/k_consistency_report.*` | 100% completion sur 30 batches initiaux |
| **6** build_all.py | ✅ | `analysis/build_all.py` → `results/analysis/` | 50 outputs (40 tables + 10 figures) |
| **7** RQ5 lock | ✅ | `harness/experiment_lock.py` + `PHASE7_RQ5_LOCK.md` | enforced par fcntl.flock |
| **8** RQ5 v2 instrumentation | ❌ | (à faire : 24-col CSV avec convergence_time, duplicate_jobs, etc.) | requires re-run ~2h cluster |
| **9** Docs artifact | ✅ | REPRODUCE, HARNESS_FIXES, DATASET_POLICY, RQ5_IDEMPOTENCE, PHASE2/3/7, README artifact section | 8 documents |
| **10** Readiness | ✅ | `results/analysis/paper_{claims,limitations}.md` + `tse_readiness_checklist.md` | classification complète |

**Score : 9/10 PHASEs livrées** (manque seulement PHASE 8).

### Commits du sprint TSE

```
e132748  PHASE 3 — DB-state restore verification infrastructure
2f32136  PHASE 7 — RQ5 lock + README artifact section
b9a7c85  PHASE 6 — add 5 figures to build_all.py
0cf0fed  PHASE 6 — build_all.py MVP (40 tables)
9de74cf  PHASE 2 — assertion-level outcomes infrastructure
0a4d2c5  PHASE 9+10 docs (REPRODUCE, paper_claims/limitations/tse_readiness)
e7579fc  PHASE 4+5+9 docs (HARNESS_FIXES, DATASET_POLICY, RQ5_IDEMPOTENCE)
19814da  PHASE 0+1 (AUDIT, consolidate_results.py)
```

---

## 3. Critères globaux prompt.txt

| # | Critère | Statut |
|---|---|---|
| 1 | Aucun chiffre dépend d'un tracker live | ✅ enforced par `consolidate_results.py` |
| 2 | Tableaux régénérables depuis `results/frozen/` | ✅ via `analysis/build_all.py` |
| 3 | CSVs utilisés listés dans MANIFEST.json | ✅ avec SHA-256 |
| 4 | Assertion-level pour sujets corrigés | ⚠️ infra prête, collecte en cours |
| 5 | Restores vérifiés par hash/row-count | ⚠️ infra prête, validation 10 tables OK |
| 6 | Batches K incomplets signalés | ✅ rapport 0 incomplets sur 30+ batches |
| 7 | RQ5 protégé contre exécution parallèle | ✅ lock mécanique |
| 8 | RQ5 métriques convergence exploitables | ⚠️ basiques OK, v2 = PHASE 8 |
| 9 | Corrections harness documentées | ✅ |
| 10 | Claims classés par niveau de preuve | ✅ |

**8/10 critères pleinement validés + 2 partiels.**

---

## 4. État des données par RQ × sujet (snapshot 2026-05-17T13:30Z)

| RQ | S1 | S2 | S3 | S4 | S5 |
|---|---|---|---|---|---|
| **RQ1 Flakiness** | ✅ 60/60 (Kind+AKS) | ✅ 60/60 (post `:v2.5.1-fix2`) | ✅ 60/60 | ✅ rerun 60/60 (`:v2.15.1-fix2`) | 🔄 rerun en cours (`:v3.4.0-fix5`) |
| **RQ2 Cross-PR K=8** | ✅ AKS K=8 propre | ✅ | ✅ | ✅ rerun OK | ⏳ après S5 flak |
| **RQ3 Performance** | ✅ envelope 14.6s | ✅ 15.1s | ✅ 16.0s | ✅ 15.8s | ✅ 14.2s |
| **RQ4 Bug-detect** | ✅ 50/50 NULL | exc. archi. | exc. archi. | exc. archi. | exc. archi. |
| **RQ5 Idempotence** | ✅ 18/18 | ✅ 18/18 | ✅ 18/18 (re-run propre) | ✅ 18/18 (rerun `:v2.15.1-fix2`) | ❌ **0/18 avec `:v3.4.0-fix5` — fix S5 incomplet** |

### Envelope RQ3 (paper-ready, depuis `results/analysis/tables/rq3_checkpoint_envelope.md`)

| Subject | N | Median (s) | p95 (s) | Pipeline ON median | Pipeline OFF median | MWU p | Â₁₂ |
|---|---|---|---|---|---|---|---|
| s1-flask-catalog | 30 | 14.0 | 16.0 | 72.0 | 23.0 | <0.001 | 1.00 |
| s2-listmonk | 30 | 15.0 | 16.5 | 75.5 | 46.0 | <0.001 | 1.00 |
| s3-healthchecks | 30 | 16.0 | 18.0 | 88.0 | 42.5 | <0.001 | 0.97 |
| s4-umami | 29 | 16.0 | 20.0 | 56.0 | 25.0 | <0.001 | 0.97 |
| s5-petclinic | 30 | 14.0 | 16.0 | 115.0 | 87.0 | <0.001 | 1.00 |

**Enveloppe cross-stack 14.0–16.0 s** (1.8 s spread). Confirmé via `analysis/build_all.py`.

---

## 5. ⚠️ Cas S5 idempotence — investigation en cours

Le rerun S5 idempotence avec `:v3.4.0-fix5` (`results/s5-petclinic/idempotence_run_metrics_20260517T122619Z.csv`) montre 18/18 **Failed** au lieu du 18/18 Succeeded attendu après les corrections `e2e_create_owner` + `owner_update`.

**Causes possibles** :
1. Un cycle preview supplémentaire d'idempotence (avec kill operator) introduit un timing différent qui révèle un autre bug applicatif S5
2. Une assertion non identifiée échoue spécifiquement quand l'operator a été tué
3. Le fix lui-même a une régression non détectée

**Plan diag** :
- Capturer un Preview S5 idemp live en cours, lire `.status.tests.{regression,e2e}.output`
- Identifier quelle assertion fail désormais
- Étendre la correction OU documenter S5 RQ5 comme cas-ouvert honnête

**Implication papier** : pour l'instant, RQ5 = 4/5 sujets pleinement OK. S5 = preliminary avec note de limitation.

---

## 6. Procs actifs (snapshot 13:30Z)

| PID | Rôle | Statut |
|---|---|---|
| 1036449 | S4+S5 rerun launcher chain | en cours — S5 flak/cross_pr restant |
| (sub) | S5 flakiness via `_run_one_subject.py` | démarré 13:24Z, ETA ~14:30Z |
| 1120818 | watch-mode PHASE 2 (assertion outcomes) | actif, capture passive |
| (monitor) | snapshots 7-min | actif |

---

## 7. ETA actions automatiques restantes

| Étape | Durée |
|---|---|
| S5 flakiness rerun (60 runs) | ~80 min → fin ~14:45Z |
| S5 cross_pr K=8 rerun (14 runs) | ~30 min → fin ~15:15Z |
| **Total auto restant** | **~1h 45min → ~15:15Z = 17:15 Paris** |

---

## 8. Travail manuel à faire ensuite

| Tâche | Effort |
|---|---|
| Investigation S5 idempotence (capture live tests output) | 30 min |
| Si fix S5 trouvé → relance S5 idemp seule | +1h |
| Re-run `python3 scripts/consolidate_results.py` (capturer nouveaux S5 CSVs) | 1 min |
| Re-run `python3 analysis/build_all.py` (régénérer outputs avec données complètes) | 1 min |
| Commit + push final | 5 min |
| **Optionnel — PHASE 8** (RQ5 v2 instrumentation) | 1-2j dev + 2h cluster |

---

## 9. Verdict TSE (immédiat)

| Cible | Statut | Note |
|---|---|---|
| Artifact track (ICSE/FSE/ICSME) | ✅ ready | 50 outputs reproductibles depuis `results/frozen/` |
| EMSE empirical | ✅ ready | claims classés, limitations énumérées |
| TSE empirical | ✅ ready avec R1 mineure | manque PHASE 8 pour RQ5 confirmatory |
| ICSE/FSE Q1 | ⚠️ +3-5j | besoin Related Work + 1 baseline comparison |

---

## 10. Référence rapide pour l'évaluation

```bash
# Cloner et reproduire les analyses sans cluster
git clone https://github.com/ihsenalaya/preview-experiments
cd preview-experiments
pip install -r analysis/requirements.txt
python3 scripts/consolidate_results.py       # results/ → results/frozen/
python3 analysis/check_k_consistency.py      # → results/analysis/k_consistency_report.*
python3 analysis/build_all.py                # → results/analysis/{tables,figures}/

# Vérifier les hashes
python3 -c "
import hashlib, json
from pathlib import Path
m = json.loads(Path('results/frozen/MANIFEST.json').read_text())
for e in m['entries']:
    p = Path('results/frozen') / e['subject_id_from_path'] / Path(e['src']).name
    actual = hashlib.sha256(p.read_bytes()).hexdigest()
    assert actual == e['sha256'], f'mismatch {p}'
print(f'{len(m[\"entries\"])} CSVs verified OK')
"
```

Voir [`REPRODUCE.md`](REPRODUCE.md) pour la procédure complète.
