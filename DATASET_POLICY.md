# DATASET_POLICY.md — politique de classification et de freeze des données

**Objectif** : définir sans ambiguïté quel CSV entre dans le dataset utilisé par les analyses, quel CSV en est exclu, et pourquoi. Le but est que tout chiffre du papier soit traçable à un CSV figé dans `results_frozen/`, et qu'aucun chiffre ne dépende d'un tracker live (`EXPERIMENT_METRICS.md`, captures kubectl éphémères, console output).

---

## 1. Cycle de vie d'un CSV

```
   [run d'expérience]
          │
          ▼
   results/<subject>/<experiment>_<schema>_<TIMESTAMP>.csv     ← RAW (jamais modifié)
          │
          ▼
   scripts/consolidate_results.py    ← lecture seule
          │
          ├──► classification → {final, obsolete, diagnostic, partial, excluded}
          │
          ▼
   results_frozen/<subject>/<experiment>_<schema>_<TIMESTAMP>.csv   ← FROZEN (copie 1:1)
   results_frozen/MANIFEST.json                                     ← métadonnées
   results_frozen/excluded_datasets.csv                             ← exclus + raison
          │
          ▼
   analysis/  (build_all.py, *.py)   ← lecture exclusive de results_frozen/
          │
          ▼
   tables/, figures/, paper.tex
```

**Règle d'or** : aucune analyse ne lit `results/` ni `EXPERIMENT_METRICS.md`. Tout passe par `results_frozen/`.

---

## 2. Les 5 statuts

### 2.1 `final`

CSV retenu pour les analyses du papier.

**Critères** (tous doivent être satisfaits) :

- Le nom du fichier matche le pattern `<experiment>_<schema>_<YYYYMMDDTHHMMSSZ>.csv`
- Le header CSV match le schéma attendu (`harness/results_writer.py` `_SCHEMAS`)
- `data_row_count > 0`
- Pas de marqueur OBSOLETE/archived/diag dans le filename
- Pour les expériences avec target N : `data_row_count ≥ 50% × target` (PHASE 1 v1 — peut être durci en v2)
- Pour `idempotence` : pas tous les runs en phase Failed (sinon → obsolete-broken-image)
- En cas de plusieurs CSVs candidats pour le même scope (subject × experiment), un seul est retenu (le plus informatif — voir §3)

### 2.2 `obsolete`

CSV qui contient des données réelles mais qui a été superseded ou invalidé.

**Causes possibles** :

| Cause | Détection |
|---|---|
| Marqueur explicite dans le filename (`.OBSOLETE_<reason>.csv`) | substring match |
| Legacy top-level CSV (chemin `results/*.csv`, pas `results/<subject>/...`) avec un per-subject équivalent du même `experiment` existant | détection automatique |
| Idempotence avec **tous les runs en Failed** (≥ 10 runs, `n_succeeded == 0`) — suggère image cassée ou environnement, pas une vraie divergence operator | détection automatique |
| Superseded par un CSV de meilleure qualité pour le même scope | sélection multi-candidats (§3) |

Les CSVs `obsolete` ne sont **jamais supprimés** ; ils restent disponibles dans `results/` pour traçabilité, mais ne sont pas copiés dans `results_frozen/` et n'entrent dans aucune analyse.

### 2.3 `diagnostic`

CSV produit par une expérience de diagnostic, sondage manuel, ou test du harness lui-même.

**Critères** : filename contient `diag`, `DIAG`, `scratch`, ou `SCRATCH`.

Utilité : conserver la trace d'investigations sans polluer le dataset principal.

### 2.4 `partial`

CSV d'une run d'expérience qui s'est arrêtée ou a crashé avant complétion.

**Critères** :

| Expérience | Seuil partial |
|---|---|
| flakiness | `data_row_count < 30 × 0.5 × 3 = 45` (50% du target = 60 runs × 3 suites) |
| performance | idem (50% × 60 runs) |
| cross_pr | `data_row_count < 40` (target ~84 lignes pour K=2,4,8 × iso) |
| bug_detection | `mutant_ids_observed_count < 30` |
| idempotence | `data_row_count < 12` (target 18 = 6 kill_steps × 3 répétitions) |

Les `partial` sont **conservés** dans `results/` mais **pas figés**, sauf si la sélection multi-candidats les promeut (rare — la plupart du temps un final existe).

### 2.5 `excluded`

CSV qui ne peut pas être analysé du tout.

**Critères** :

- Filename ne matche pas le pattern attendu
- Header CSV vide ou parseable mais trivial
- `data_row_count == 0` (header seul)

Documenté dans `excluded_datasets.csv` avec raison ; conservé en `results/` mais ignoré.

---

## 3. Sélection en cas de plusieurs candidats pour le même scope

Lorsque plusieurs CSVs ont `(experiment, subject_id)` identique et sont tous `candidate-final`, on choisit le plus informatif selon l'ordre lexicographique inverse de la clé :

```
quality_key(csv) = (n_succeeded, mutant_ids_observed_count, data_row_count, timestamp)
```

Le CSV de quality_key max devient `final` ; les autres deviennent `obsolete` avec raison `"superseded by <chosen> (succ=X vs Y, rows N vs M, ts T vs T')"`.

Cette règle garantit que :

- Pour `idempotence`, le CSV avec le plus de runs Succeeded gagne, même s'il a moins de rows (cas S4 : nouveau rerun 18 Succeeded > ancien 0 Succeeded, même row count)
- Pour `bug_detection`, le CSV avec le plus de mutants distincts gagne (~50/50 > 23/47)
- Pour les autres, le plus complet et le plus récent gagne

---

## 4. Garanties et invariants

### 4.1 Garanties de `consolidate_results.py`

1. **Ne lit jamais** `EXPERIMENT_METRICS.md`, `AUDIT.md`, `CLAUDE.md`, ou tout autre fichier markdown — hard guard dans le code.
2. **Ne modifie jamais** un CSV original dans `results/`.
3. **Ne supprime jamais** un CSV original.
4. **Idempotent** : 2 runs successifs sur la même donnée produisent le même MANIFEST (modulo le `generated_at_utc`).
5. **Détection content-based** : ne s'appuie pas sur des conventions de nommage humaines au-delà du marqueur `.OBSOLETE_*` (qui reste optionnel).

### 4.2 Garanties pour les analyses (`analysis/`, futur `build_all.py`)

1. **Lecture exclusive** de `results_frozen/` — aucun import de `results/` direct.
2. Toute table ou figure produite doit pouvoir nommer son CSV source via le `MANIFEST.json` et son SHA-256.
3. Toute claim chiffrée dans le papier doit citer le CSV figé ; les chiffres dérivés des trackers live (`EXPERIMENT_METRICS.md`) ne sont pas publiables.

### 4.3 Garanties de reproductibilité

Pour vérifier qu'un freeze actuel correspond bien à un état antérieur :

```bash
python3 scripts/consolidate_results.py --dry-run
# Compare le by_status (5 catégories) avec celui du MANIFEST.json précédent
# Les SHA-256 du MANIFEST permettent de vérifier que les CSVs n'ont pas dérivé
```

---

## 5. Cycle d'usage typique

```bash
# Après une re-run d'expérience qui a ajouté de nouveaux CSVs dans results/<sub>/
python3 scripts/consolidate_results.py

# Vérifier ce qui a changé
git diff results_frozen/MANIFEST.json

# Si une promotion final → obsolete est faite (un nouveau CSV supersede un ancien),
# c'est attendu et le rationale est dans l'excluded_datasets.csv

# Re-générer les analyses depuis le frozen propre
python3 analysis/01_flakiness.py
python3 analysis/02_cross_pr.py
# ... (ou future analysis/build_all.py)
```

---

## 6. Cas limites et override manuel

### Cas 1 : Un CSV "should-be-final" est classé partial à tort

**Action** : ne pas modifier le script. Renommer le CSV manuellement en `<basename>.OVERRIDE_FINAL.csv` (le pattern de classification le reverra comme "candidate-final" avec un warning). Documenter le rationale dans `excluded_datasets.csv` à la prochaine consolidation.

(PHASE 1 v2 — pas encore implémenté : ajouter `--override-config FILE` pour gérer ces cas sans toucher au filename.)

### Cas 2 : Un CSV "obsolete" doit être recouvré pour comparaison

**Action** : il reste dans `results/` (jamais supprimé). Référencer son chemin original ; ne pas le copier dans `results_frozen/`.

### Cas 3 : Deux CSVs "final" candidats avec quality_key identique

**Comportement actuel** : tri stable sur timestamp ascendant → le plus ancien est conservé (rare ; en pratique le timestamp les différencie). Documenté en warning.

---

## 7. Versionnage de cette politique

| Version | Changements |
|---|---|
| 1.0.0 (2026-05-17) | version initiale — 5 statuts, sélection quality_key, hard guards, idempotence |

Toute modification de la politique entraîne :

1. Bump de `consolidate_version` dans `consolidate_results.py`
2. Bump de la version dans ce document
3. Re-run de la consolidation
4. Commit avec un message qui résume les changements (et leur impact sur le set de finals)

---

## 8. Référence rapide

| Statut | Compte initial (2026-05-17T11:55Z) | Dans `results_frozen/` ? | Analysé ? |
|---|---|---|---|
| `final` | 22 | ✅ | ✅ |
| `obsolete` | 20 | ❌ | ❌ |
| `partial` | 14 | ❌ | ❌ |
| `excluded` | 5 | ❌ | ❌ |
| `diagnostic` | 0 (aucun pour l'instant) | ❌ | ❌ |
| **Total scanné** | **61** | | |

Voir `results_frozen/MANIFEST.json` pour la liste complète et `results_frozen/excluded_datasets.csv` pour le détail des exclusions.
