# REPRODUCE.md — comment régénérer toutes les analyses depuis zéro

Ce document explique comment, à partir d'un clone propre du dépôt, **régénérer
toutes les tables et figures du papier** à partir des CSVs figés. Aucune
commande ne dépend d'un cluster, d'un cloud, ou d'un tracker live.

> Pour reproduire les **runs d'expérience** (collecte de nouveaux CSVs), voir
> `SETUP_AKS.md` et `EXPERIMENT_METRICS.md`. Ce document couvre seulement le
> chemin **données figées → tables/figures**.

---

## Prérequis

- Python ≥ 3.10
- `pip install -r analysis/requirements.txt`
  (scipy, pandas, numpy, matplotlib, jupytext, pyyaml)
- ~50 Mo de disque libre

---

## Étape 1 — Vérifier les hashes du dataset figé

```bash
cd /path/to/preview-experiments
python3 - <<'PY'
import hashlib, json
from pathlib import Path
mfst = json.loads(Path("results/frozen/MANIFEST.json").read_text())
print(f"Manifest version: {mfst['consolidate_version']}")
print(f"Generated:        {mfst['generated_at_utc']}")
print(f"Total scanned:    {mfst['total_csvs_scanned']}")
print(f"By status:        {mfst['by_status']}")
print()
print("Verifying SHA-256 of each frozen CSV ...")
ok = bad = 0
for e in mfst["entries"]:
    p = Path("results/frozen") / e["subject_id_from_path"] / Path(e["src"]).name
    actual = hashlib.sha256(p.read_bytes()).hexdigest()
    if actual == e["sha256"]:
        ok += 1
    else:
        bad += 1
        print(f"  MISMATCH: {p}  expected {e['sha256'][:8]}  got {actual[:8]}")
print(f"\n{ok} OK, {bad} MISMATCH")
PY
```

Tous les CSVs doivent avoir un SHA-256 inchangé. Si `MISMATCH` apparaît : le
dataset a été altéré depuis le freeze ; ne pas publier.

---

## Étape 2 — Re-consolider depuis `results/` (optionnel)

Si vous avez ajouté de nouveaux CSVs dans `results/` (ex : après une re-run
d'expérience), regénérez le freeze :

```bash
python3 scripts/consolidate_results.py
git diff results/frozen/MANIFEST.json    # vérifier les changements
```

Le script est **idempotent** : 2 runs sur la même donnée produisent un
MANIFEST identique modulo le champ `generated_at_utc`.

Voir `DATASET_POLICY.md` pour la sémantique des 5 statuts (final / obsolete /
diagnostic / partial / excluded) et les règles de sélection multi-candidats.

---

## Étape 3 — Vérifier la cohérence K (RQ2)

```bash
python3 analysis/check_k_consistency.py
cat results/analysis/k_consistency_report.txt
```

Sortie attendue : tous les batches K=2, K=4, K=8 × 5 sujets × 2 iso = 30 batches
complets (100% completion). Tout warning d'`incomplete_batch` doit être
mentionné comme limitation dans le papier.

---

## Étape 4 — Régénérer les analyses RQ par RQ

```bash
# RQ1 — Test flakiness
python3 analysis/01_flakiness.py

# RQ2 — Cross-PR
python3 analysis/02_cross_pr.py

# RQ3 — Performance overhead
python3 analysis/03_performance.py

# RQ4 — Bug detection (null result on S1)
python3 analysis/04_bug_detection.py

# RQ5 — Idempotence (only after PHASE 8 instrumentation lands —
# current scripts use suite-level phase only)
python3 analysis/05_idempotence.py
```

Chaque script lit **exclusivement** depuis `results/frozen/` et produit ses
sorties sous `results/analysis/figures/` (PDF/PNG) et `results/analysis/` (tables).

> Les analyses utilisent jupytext (format `py:percent`) — chaque script est
> exécutable en CLI **et** ouvrable comme notebook Jupyter via
> `jupytext --to notebook analysis/01_flakiness.py`.

---

## Étape 5 — Exécuter RQ5 seule (collecte de nouvelles données)

⚠️ **RQ5 ne doit JAMAIS tourner en parallèle d'autres expériences.** Le pod
operator est tué par cette expérience, ce qui fait crasher tout `kubectl
apply preview` concurrent.

```bash
# 1. Vérifier qu'aucune autre expérience ne tourne
ps -ef | grep -E "exp_(flakiness|cross_pr|performance|bug_detection)" | grep -v grep
# (doit être vide)

# 2. Vérifier que le cluster est propre
kubectl get previews -A --no-headers | wc -l
# (doit être 0 ou très bas)

# 3. Lancer RQ5
cd /path/to/preview-experiments
TS=$(date -u +%Y%m%dT%H%M%SZ)
python3 -u exp_idempotence/run.py > logs/idempotence-${TS}.log 2>&1 &
echo "RQ5 PID=$!"
```

PHASE 7 du plan TSE va ajouter un lock fichier (`.experiment_lock`) qui
empêche l'exécution parallèle même si on oublie de vérifier manuellement.

Voir `RQ5_IDEMPOTENCE.md` pour le protocole détaillé.

---

## Étape 6 — Reproduire de bout en bout

Pour quelqu'un qui clone le dépôt et veut "tout faire" sans toucher au cluster :

```bash
git clone https://github.com/ihsenalaya/preview-experiments
cd preview-experiments
pip install -r analysis/requirements.txt

# Vérifier l'intégrité des données figées
python3 -c "
import hashlib, json
from pathlib import Path
m = json.loads(Path('results/frozen/MANIFEST.json').read_text())
for e in m['entries']:
    p = Path('results/frozen') / e['subject_id_from_path'] / Path(e['src']).name
    assert hashlib.sha256(p.read_bytes()).hexdigest() == e['sha256'], e['src']
print('All hashes OK')
"

# Reproduire toutes les analyses
python3 analysis/check_k_consistency.py
python3 analysis/01_flakiness.py
python3 analysis/02_cross_pr.py
python3 analysis/03_performance.py
python3 analysis/04_bug_detection.py
python3 analysis/05_idempotence.py

ls results/analysis/figures/ results/analysis/
```

---

## Pourquoi ce flow

- **Pas de live tracker dans les analyses** : `EXPERIMENT_METRICS.md` est un journal
  de travail, pas une source de vérité figeable. Les analyses doivent rester
  reproductibles même si ce fichier disparaît.
- **Freezeable** : `results/frozen/MANIFEST.json` capture l'état exact (SHA-256)
  des CSVs au moment du freeze. Toute modification du dataset est détectée.
- **Idempotent** : re-runner les analyses sur le même freeze produit les mêmes
  tables/figures, modulo timestamps.
- **Séparation collecte vs analyse** : la collecte (`exp_*/run.py`) requiert un
  cluster ; l'analyse (`analysis/*.py`) ne requiert que les CSVs figés. Un
  reviewer peut reproduire les chiffres du papier sans accès cluster.

---

## Annexe — chemins importants

| Chemin | Contenu |
|---|---|
| `results/` | données brutes per-subject (jamais modifiées par les scripts d'analyse) |
| `results/frozen/` | snapshot figé pour analyse — produit par `scripts/consolidate_results.py` |
| `results/frozen/MANIFEST.json` | inventaire avec SHA-256, line counts, subjects, conditions, K |
| `results/frozen/excluded_datasets.csv` | CSVs non retenus + raison |
| `analysis/01..05_*.py` | analyses per-RQ (jupytext) |
| `analysis/check_k_consistency.py` | vérification batches RQ2 |
| `analysis/shared/` | helpers stats/plotting/latex |
| `results/analysis/` | tables markdown + CSV générés |
| `results/analysis/figures/` | figures PDF/PNG générées |
| `AUDIT.md` | inventaire PHASE 0 |
| `DATASET_POLICY.md` | règles de classification des CSVs |
| `HARNESS_FIXES.md` | corrections de tests S2/S4/S5 avec rationale |
| `RQ5_IDEMPOTENCE.md` | protocole RQ5 + limitations |
| `EXPERIMENT_METRICS.md` | tracker live (NE PAS utiliser pour les chiffres du papier) |
| `SETUP_AKS.md` | setup cluster + dépendances (pour collecter de nouvelles données) |
