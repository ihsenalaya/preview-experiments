# PHASE 3 — DB-state restore verification

**Objectif** : preuve **directe** que le mécanisme de checkpoint/restore reproduit l'état DB exactement, en hashant l'état postgres à 9 points clés du pipeline. Sans cela, la correctness du restore est seulement **inférée** via les test outcomes.

**Critère de vérification (prompt.txt)** :
```
post_checkpoint snapshot_hash_global == post_restore_regression snapshot_hash_global
post_checkpoint snapshot_hash_global == post_restore_e2e snapshot_hash_global
```

Si ces deux égalités tiennent sur N runs, on a **prouvé** que le restore reproduit l'état checkpoint au bit près.

---

## 1. Architecture

```
exp_*/run.py (existant, non modifié)
        │
        │  crée Preview, attend transitions de status.tests.step
        ▼
collect_db_state_from_preview.py (nouveau, watch mode)
        │
        │  à chaque transition step → step', appelle:
        ▼
harness/db_state_collector.py
        │
        │  kubectl exec postgres-pod -- psql -c '<SELECT>'
        │  pour chaque table user :
        │    row_count + content_hash MD5
        │  global :
        │    snapshot_hash_global SHA-256
        ▼
results/<sub>/db_state_metrics_<TS>.csv
```

**Read-only de bout en bout** : aucun DDL, aucun DML, aucune modification de l'app SUT, aucune modification du checkpoint/restore de l'operator.

---

## 2. Hash déterministe

Pour chaque table `<schema>.<table>` :

```sql
SELECT md5(coalesce(string_agg((t)::text, E'\n' ORDER BY (t)::text), ''))
FROM "<schema>"."<table>" t
```

Caractéristiques :
- **Déterministe** : `ORDER BY (t)::text` trie la projection textuelle complète du tuple → ordre stable inter-runs
- **Toutes colonnes incluses** : pas d'exclusion par défaut (cf §5)
- **Tables vides** : hash = `md5("")` = `d41d8cd98f00b204e9800998ecf8427e`
- **Encodage** : MD5 (16 bytes, hex 32 chars) pour les tables, SHA-256 pour le global

Global :

```python
combined = "\n".join(sorted(f"{schema}.{table}:{content_hash}" for each table))
snapshot_hash_global = sha256(combined).hexdigest()
```

→ change si **n'importe quelle** table change de contenu.

---

## 3. Les 9 étapes pipeline

Les step labels (prompt.txt) mappent les transitions de l'operator :

| Step PHASE 3 | Trigger | Sémantique |
|---|---|---|
| `post_migration` | operator passe à `saving` | postgres-migrate vient de finir |
| `post_checkpoint` | operator passe à `smoke` | pg_dump done, ConfigMap rempli |
| `post_smoke` | operator passe à `restore-regression` | smoke step done, run_log a marker smoke |
| `pre_restore_regression` | = `post_smoke` (alias) | juste avant TRUNCATE+restore |
| `post_restore_regression` | operator passe à `regression` | TRUNCATE+restore done, run_log devrait être vide |
| `post_regression` | operator passe à `restore-e2e` | regression step done, run_log a marker regression |
| `pre_restore_e2e` | = `post_regression` (alias) | juste avant TRUNCATE+restore |
| `post_restore_e2e` | operator passe à `e2e` | TRUNCATE+restore done |
| `post_e2e` | operator passe à `complete` | pipeline done |

Le watch-mode détecte les transitions via `kubectl get preview -o jsonpath='{.status.tests.step}'` polling et déclenche un snapshot.

---

## 4. CSV schema (`db_state_metrics`)

| Colonne | Type | Description |
|---|---|---|
| `run_id` | string | id du run d'expérience |
| `subject_id` | string | s1-flask-catalog etc. |
| `preview_name` | string | nom du Preview CR |
| `isolation_enabled` | True/False | condition iso (toujours True pour RQ5) |
| `step` | string | un des 9 labels ci-dessus |
| `schema_name` | string | nom schéma postgres (ou `*` pour summary row) |
| `table_name` | string | nom table (ou `*` pour summary row) |
| `row_count` | int | nombre de lignes dans la table |
| `content_hash` | string | MD5 hex 32 chars (vide pour summary row) |
| `excluded_columns` | string | csv des colonnes exclues du hash (vide par défaut) |
| `snapshot_hash_global` | string | SHA-256 hex 64 chars (égal pour toutes les lignes d'un même snapshot) |
| `ts` | ISO 8601 | timestamp du snapshot |

Une snapshot complète d'un step = (N tables × 1 ligne) + (1 ligne summary `*/*`).

---

## 5. Colonnes volatiles à exclure

**v1 (actuel)** : aucune exclusion. Le hash inclut TOUTES les colonnes. Si une table contient des timestamps `updated_at` qui sont **régénérés par l'app au démarrage** (pas re-créés par restore), le hash post_restore ne matchera pas post_checkpoint.

**v2 (à venir si besoin)** : table d'exclusions par (subject, table) :

```python
DEFAULT_EXCLUDED_COLUMNS: dict[tuple[str, str], list[str]] = {
    ("hcdb", "django_session"): ["expire_date"],  # session refresh
    ("appdb", "auth_token"): ["last_used_at"],    # token touch
    # etc.
}
```

Avec exclusion, le hash devient :

```sql
SELECT md5(string_agg(row(col1, col2, ...).except(excluded_cols)::text, '\n' ORDER BY ...)) ...
```

Pour l'instant on émet le hash complet et on observe : si un mismatch apparaît, on l'investigue avant de l'ajouter aux exclusions.

---

## 6. Utilisation

### One-shot — snapshot ponctuel

```bash
python3 scripts/collect_db_state_from_preview.py one-shot \
  --preview idem-abc12345 \
  --subject s4-umami \
  --run-id myrun \
  --step post_checkpoint \
  --iso True \
  --out results/s4-umami/db_state_metrics_$(date -u +%Y%m%dT%H%M%SZ).csv
```

### Watch — capture automatique des 9 transitions

```bash
python3 scripts/collect_db_state_from_preview.py watch \
  --preview idem-abc12345 \
  --subject s4-umami \
  --run-id myrun \
  --iso True \
  --out results/s4-umami/db_state_metrics_$(date -u +%Y%m%dT%H%M%SZ).csv \
  --max-seconds 240 --poll-every 3
```

Le watch s'arrête automatiquement quand `post_e2e` est capturé ou que le preview atteint `complete`.

### Verify — vérification post-collecte

```bash
python3 scripts/collect_db_state_from_preview.py verify --csv db_state_metrics_*.csv
```

Sortie :
```
=== Verifying restore invariants across 18 runs ===
  PASS run-abc  restore_verified (post_restore_regression post_restore_e2e)
  PASS run-def  restore_verified (post_restore_regression post_restore_e2e)
  FAIL run-ghi
        OK: post_checkpoint == post_restore_regression
        DIRTY: post_checkpoint == post_restore_e2e

=== Summary: 17 pass, 1 fail, 0 skip ===
```

---

## 7. Validation initiale

Test live sur preview S5 PetClinic (`idem-40beab08`) à `post_smoke` :

```
10 tables snapshotted; snapshot_hash_global=7ec25eb8c659...
```

Détail :

| Table | row_count | content_hash (12c) |
|---|---|---|
| owners | 10 | baf1f793ca32… |
| pets | 13 | da17ae5b8f11… |
| roles | 3 | f891efeb32a6… |
| run_log | 0 | d41d8cd98f00… |
| specialties | 3 | 7c4cb3350a3… |
| types | 6 | 736971696c20… |
| users | 1 | 1f2bc999bf42… |
| vet_specialties | 5 | 26028c74ce1f… |
| vets | 6 | e76a03fd03ae… |
| visits | 4 | 18fecccea718… |

→ Total 51 rows, snapshot_hash_global `7ec25eb8c659...`. Si je relance le même collecteur sur le même Preview au même moment, j'obtiendrai le même hash bit-pour-bit.

---

## 8. Intégration future dans `exp_*/run.py`

Pour collecter automatiquement à chaque run d'expérience (au lieu du watch ad-hoc) :

```python
# Top of exp_idempotence/run.py
from harness.db_state_collector import discover_postgres_in_namespace, snapshot, iter_rows_to_csv

# In run_once(), after factory.create() and before factory.delete():
def _snapshot_step(step_label):
    try:
        tgt = discover_postgres_in_namespace(factory.runtime_namespace(pr_number))
        rows = snapshot(tgt=tgt, run_id=run_id, subject_id=subject_id,
                        preview_name=name, isolation_enabled=True, step=step_label)
        iter_rows_to_csv(rows, f"results/{subject_id}/db_state_metrics_{ts_session}.csv")
    except Exception as exc:
        print(f"[warn] db_state snapshot failed at {step_label}: {exc}")

# Called at the right transitions inside the polling loop.
```

**Cette intégration n'est PAS faite par défaut** pour ne pas perturber les expériences en cours. Voir `REPRODUCE.md` pour le diff exact à appliquer quand l'expé est arrêtée.

---

## 9. Garanties

| Garantie | Comment |
|---|---|
| Read-only | seul SELECT est appelé via psql ; pas de DDL/DML |
| Pas de modif app | kubectl exec dans le postgres pod, jamais dans le pod SUT |
| Déterministe | ORDER BY (t)::text trie le tuple complet en représentation texte |
| Idempotent | 2 snapshots successifs sur le même DB inchangé → hash identique |
| Independance schéma | enumeration via pg_tables, supporte n'importe quelle structure SUT |
| Tolérance partial | si une table échoue (lock, permission), warning + continue ; row_count=-1 |

---

## 10. Limites connues (v1)

| Limite | Impact | Mitigation |
|---|---|---|
| Pas d'exclusion de colonnes volatiles | hash diffère si SUT touche un timestamp post-restore | v2 (sur demande, après observation des premiers mismatches) |
| Hash text-cast | tuples avec binaires (bytea) auront un cast `\\x...` non déterministe ? | OK pour les SUTs actuels (pas de bytea critique) |
| Polling 3s pour watch | peut rater une transition très rapide (rare avec nos pipelines ~30s) | augmenter poll_every ; intégrer in-line dans exp_*/run.py |
| Pas d'intégration auto exp_*/run.py | requiert lancement manuel via watch-mode | acceptable pour MVP ; intégration documentée |
| Cluster-local seulement | si plusieurs pods postgres existent (HA) on prend le 1er | nos previews ont 1 seul pod postgres |

---

## 11. Référence rapide

- Module : `harness/db_state_collector.py`
- CLI : `scripts/collect_db_state_from_preview.py`
- Schema CSV : `db_state_metrics` dans `harness/results_writer.py` `_SCHEMAS`
- Doc : ce fichier
- Verify : `python3 scripts/collect_db_state_from_preview.py verify --csv path.csv`
