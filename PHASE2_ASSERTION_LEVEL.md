# PHASE 2 — assertion-level outcomes

**Objectif** : capturer le résultat de **chaque assertion individuelle** (`t("name", ...)` dans les tests S1-S5) avec sa catégorie, son `expected`/`observed` parsés, et un flag `is_isolation_sensitive`. Sans modifier les CSVs suite-level existants (rétrocompatibilité).

**Pourquoi** : la mesure suite-level seule (smoke/regression/e2e = Succeeded/Failed) peut conflater un vrai échec d'isolation avec une assertion broken-upstream. L'analyse assertion-level dissocie ces deux signaux et constitue la **source de vérité** pour valider/invalider la thèse RQ1.

---

## 1. Architecture

```
test program prints:                  PASS regression run_log_clean
inside the pod ─────────────────►     FAIL regression teams_list: not 200
                                              │
                                              ▼
operator captures into                .status.tests.regression.output:
preview CR YAML                         - "PASS regression run_log_clean"
                                        - "FAIL regression teams_list: not 200"
                                              │
                                              ▼
collector reads via kubectl           harness/assertion_collector.py
get preview -o json                   - parses each line
                                      - categorizes via assertion_categories.py
                                      - extracts expected/observed
                                      - normalizes failure signature
                                              │
                                              ▼
appends to CSV                        results/<subject>/assertion_outcomes_<TS>.csv
                                      schema in harness/results_writer.py
```

**Aucune modification du SUT, du test program, ou de l'operator.** Pas non plus de modification de `exp_*/run.py` (option mais non appliquée par défaut — voir §6).

---

## 2. Composants livrés

| Fichier | Rôle |
|---|---|
| `harness/assertion_categories.py` | mapping `(subject, suite, assertion_id) → category` + regex fallback + normalisation signature |
| `harness/assertion_collector.py` | parser PASS/FAIL lines + build rows + écriture CSV |
| `harness/results_writer.py` (modifié) | ajoute le schéma `assertion_outcomes` |
| `scripts/collect_assertions_from_preview.py` | CLI standalone : `one-shot` + `watch` modes |

---

## 3. Les 8 catégories (figées par prompt.txt)

| Catégorie | Sémantique | Exemples |
|---|---|---|
| `isolation_probe` | sonde d'isolation explicite | `run_log_clean` |
| `baseline_count` | vérifie un count vs baseline post-seed | `*_count_matches_seed`, `entity_count_matches_seed` |
| `functional_api` | opération CRUD/GET sur le SUT | `websites_list`, `owner_create`, `product_detail` |
| `auth_permission` | authentification ou permission | `login`, `token`, `me_endpoint`, `teams_list` |
| `schema_validation` | structure JSON | (pas utilisé encore — réservé) |
| `infra` | readiness / health | `healthz`, `health` |
| `timeout` | timeout réseau / app | (rare — détecté par signature) |
| `unknown` | non catégorisé | suite markers (`smoke`, `regression`, `e2e`) |

**`is_isolation_sensitive`** = True ssi catégorie ∈ {`isolation_probe`, `baseline_count`}.

---

## 4. Schéma `assertion_outcomes`

CSV fichier-par-sujet, append-only, format identique aux autres CSVs harness.

| Colonne | Type | Description |
|---|---|---|
| `experiment_id` | string | nom de l'expérience (`flakiness`, `cross_pr`, …) |
| `subject_id` | string | `s1-flask-catalog`, `s2-listmonk`, … |
| `run_id` | string | id du run d'expérience |
| `preview_name` | string | nom du Preview CR Kubernetes |
| `isolation_enabled` | "True"/"False" | condition iso |
| `strategy` | string | pour RQ4 : `static`/`llm_fixed`/`llm_free` ; vide sinon |
| `suite_name` | string | `smoke`/`regression`/`e2e` |
| `assertion_id` | string | nom de l'assertion (premier arg de `t(...)`) |
| `assertion_category` | string | l'une des 8 catégories |
| `outcome` | string | `Succeeded` (PASS) / `Failed` (FAIL) |
| `expected` | string | valeur attendue extraite du message |
| `observed` | string | valeur observée extraite du message |
| `normalized_failure_signature` | string | signature stable pour regrouper failures similaires |
| `is_isolation_sensitive` | "True"/"False" | flag pour analyse downstream |
| `ts` | ISO 8601 | timestamp de capture |

---

## 5. Utilisation

### 5.1 One-shot — un preview spécifique

```bash
python3 scripts/collect_assertions_from_preview.py one-shot \
    --preview idem-abc12345 \
    --subject s4-umami \
    --run-id idempotence-s4-umami-stepe2e-00-xyz \
    --experiment idempotence \
    --iso True \
    --out results/s4-umami/assertion_outcomes_$(date -u +%Y%m%dT%H%M%SZ).csv
```

### 5.2 Watch-mode — capture opportuniste

Boucle en arrière-plan ; détecte les Previews qui ont atteint un état terminal (les 3 suites en `Succeeded` ou `Failed`), capture leur output, supprime les doublons (par UID). Idéal pour récolter des données pendant qu'une expérience en cours tourne.

```bash
nohup python3 scripts/collect_assertions_from_preview.py watch \
    --out-dir results/ \
    --max-seconds 14400 \
    --poll-every 8 \
    > logs/assertion-watch-$(date -u +%Y%m%dT%H%M%SZ).log 2>&1 &
```

Le mode watch infère `experiment` depuis le préfixe du nom du Preview (`fl-`, `cp-`, `pf-`, `bd-`, `idem-`) et `subject_id` depuis l'image SUT (présence de `s4-umami` etc dans `spec.image`).

### 5.3 Intégration dans exp_*/run.py (optionnel, non appliquée par défaut)

Pour capturer **systématiquement** assertion-level lors des futures runs (sans dépendre de watch), insérer dans `exp_<X>/run.py` juste avant `factory.delete(name)` :

```python
from harness.assertion_collector import collect_from_live_preview, iter_rows_to_csv

rows = collect_from_live_preview(
    name=name,
    subject_id=subject_id,
    run_id=run_id,
    isolation_enabled=isolation_enabled,
    experiment=EXPERIMENT,
)
iter_rows_to_csv(rows, f"results/{subject_id}/assertion_outcomes_{ts_session}.csv")
```

Cette modification est **non appliquée** dans cette PHASE pour ne pas casser la chaîne d'expérience en cours. Voir REPRODUCE.md pour le diff à appliquer quand on relance les expériences.

---

## 6. Distinction suite-level vs assertion-level

| Aspect | suite-level (`test_outcomes_*.csv`) | assertion-level (`assertion_outcomes_*.csv`) |
|---|---|---|
| Granularité | 1 ligne par (preview, suite) | 1 ligne par (preview, suite, assertion) |
| Outcome | `Succeeded` si TOUTES les assertions passent ; `Failed` sinon | par assertion |
| Catégorie | aucune | parmi 8 catégories |
| Sondes d'isolation | implicites (noyées dans le suite) | explicites (`isolation_probe`, `baseline_count`) |
| Confusion possible | "100% Failed" peut masquer un fix-broken-upstream | discrimine clairement |
| Source de vérité pour la thèse | non | **oui** |

**Conséquence pour le papier** : RQ1 (flakiness) doit reporter :

1. la mesure **suite-level** (rétro-compatibilité avec les analyses existantes), ET
2. la **décomposition assertion-level** : taux de succès `isolation_probe` ; tableau "suite-level failure root-cause category".

Voir `paper_claims.md` claim-1.1 + L2 (S4/S5 cas ouverts résolus en partie grâce à des captures live equivalentes à PHASE 2).

---

## 7. État de la collecte (snapshot 2026-05-17T12:30Z)

| Source | État |
|---|---|
| Infrastructure | ✅ livrée et testée |
| Watch-mode | 🔄 actif (PID 1120818, poll 8s, max 4h) |
| Données existantes | 1 sample test (`results/_test_assertion/`) + captures à venir via watch-mode |
| Re-run dédié pour collecte exhaustive | non décidé (~6h cluster si 5 sujets RQ1) |

---

## 8. Garanties

1. **Read-only** : aucune modification du Preview CR, du SUT, ou des CSVs existants
2. **Idempotent** : multiple captures du même Preview produisent des rows identiques (déduplication par UID dans watch-mode)
3. **Categorization stable** : le mapping `assertion_categories.py` est versionné en code, pas hardcodé dans les CSVs
4. **Compatible analyses existantes** : les scripts `analysis/0X.py` qui lisent `test_outcomes_*.csv` ne sont pas touchés ; les nouvelles analyses peuvent lire `assertion_outcomes_*.csv` en plus

---

## 9. Suites recommandées

- **PHASE 6** (build_all.py) doit lire les deux schémas et produire :
  - Table "suite-level failure rate par sujet/condition" (existant)
  - Table "assertion-level isolation_probe success rate par sujet/condition" (nouveau)
  - Table "suite-level failure root-cause decomposition" (nouveau ; chaque suite-Failed → category breakdown)

- **PHASE 8** (RQ5 v2) peut bénéficier de PHASE 2 : capturer assertion-level lors de chaque idempotence run permet de discriminer "operator failed to converge" (assertions ne s'exécutent pas du tout) vs "tests failed but operator converged" (toutes les assertions s'exécutent mais certaines fail).

- **L'intégration in-line dans `exp_*/run.py`** rendra PHASE 2 automatique pour tous les futurs runs sans dépendre du watch-mode externe.
