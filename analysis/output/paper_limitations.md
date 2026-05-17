# paper_limitations.md — limitations à anticiper et à discuter dans le papier

Liste exhaustive des limitations connues. Chaque limitation est classée par
**sévérité** (critical / moderate / minor) et accompagnée d'une **suggestion
de mitigation** (durcissement avant soumission OU acknowledgement explicite
dans le papier).

---

## L1 — Critical : un seul opérateur testé (preview-operator)

| Champ | Valeur |
|---|---|
| Sévérité | **critical** pour ICSE/FSE/ASE Q1 ; moderate pour TSE/EMSE empirical |
| Description | Toutes les claims (RQ1-RQ5) reposent sur un seul opérateur Kubernetes (preview-operator). Aucune comparaison à des baselines existantes : Testcontainers per-test, pg_tmp, schema-per-test, transaction rollback, Database Sandbox, namespace-per-test. |
| Conséquence | Reviewer ICSE/FSE va dire "engineering work, no comparative baseline" — risque rejection. |
| Mitigation possible | (a) Ajouter section Related Work avec **tableau qualitatif** comparant les 5 approches (~1 jour). (b) Implémenter UN baseline operator (migration-reset le plus simple) et mesurer ~2 jours dev + ~1h cluster. (c) Acknowledgment honnête + cite la littérature existante. |
| Recommandation | (a) + (c) pour soumission initiale ; (b) si reviewer demande en R1 |

---

## L2 — Critical : RQ4 limité à 1 sujet sur 5 (architectural mismatch)

| Champ | Valeur |
|---|---|
| Sévérité | **critical** pour le scope global ; minor si RQ4 est présenté comme "additional observation" |
| Description | `fault-catalog.yaml` ne mute que `testapp/app.py` (Flask). S1 est aligné car son SUT = testapp. S2-S5 ont des SUT différents (Go/Django/TS/Java) que la mutation ne touche pas → résultats artefactuels. |
| Conséquence | Le null result RQ4 ne porte que sur 1 sujet → claim moins fort. |
| Mitigation possible | (a) Mute la harness adapter wrapper (Python, présent partout) au lieu du SUT — ~5h, mais teste la robustness du probe pas du SUT — limitation différente. (b) Générer fault-catalog-S{2,3,4,5}.yaml pour chaque SUT, requiert mutation tools par langage (mutmut Python, gomutmut Go, etc.) — ~3-4 jours. (c) Retirer RQ4 du papier et le garder pour un papier suivant. (d) Acknowledgment + S1-only avec scope explicite. |
| Recommandation | (c) ou (d) pour soumission initiale. (b) est over-engineering pour ce papier. |

---

## L3 — Moderate : RQ5 instrumentation insuffisante pour confirmatory claims

| Champ | Valeur |
|---|---|
| Sévérité | **moderate** |
| Description | L'instrumentation actuelle agrège "operator a reconvergé" et "pipeline a réussi" dans une seule colonne `phase`. Les vrais signaux d'idempotence controller-runtime (duplicate_job_count, lost_status_count, final_state_consistent) ne sont pas capturés. |
| Conséquence | RQ5 claims restent "preliminary" — pas de garantie qu'aucun Job dupliqué n'a été créé silencieusement. |
| Évidence du problème | sur S4 et S5 avant les fixes, 0/18 Succeeded → faux signal "operator divergé" — en réalité opérateur convergé mais pipeline failed sur broken-upstream assertion. |
| Mitigation possible | PHASE 8 v2 du plan TSE — collecteur externe qui capture pendant la fenêtre kill→ready : (a) snapshot pré-kill de `kubectl get jobs,configmaps,pods -n <ns>` (b) snapshot post-recovery (c) diff structurel (d) `kubectl get events -n <ns>` filtré sur la fenêtre temporelle. ~2 jours dev + ~2h cluster re-run. |
| Recommandation | Reporter RQ5 comme "preliminary" dans soumission initiale + section "future work in instrumentation". |

---

## L4 — Moderate : pas de mesure réelle de baseline "migration reset"

| Champ | Valeur |
|---|---|
| Sévérité | **moderate** |
| Description | Le chiffre "migration reset = 37.6s" pour comparer à checkpoint (14.6s) est *dérivé théoriquement* : 2 × postgres-migrate (18.8s) mesuré. Aucun operator concurrent n'a été déployé pour mesurer un vrai "migration reset between suites". |
| Conséquence | Le ratio "checkpoint is 2.57× cheaper" est appuyé par une mesure + une estimation. |
| Mitigation possible | Implémenter une variante de l'operator qui re-applique la migration entre suites au lieu de pg_dump/restore. ~2 jours dev. Mesurer sur les 5 sujets. |
| Recommandation | Acknowledgment dans la section "Comparison". Optionnel : faire la mesure baseline si on a une semaine de slack avant soumission. |

---

## L5 — Moderate : 2 stacks à dépendance applicative externe (Listmonk, Umami) auraient pu nécessiter mocks pour isoler

| Champ | Valeur |
|---|---|
| Sévérité | **moderate** |
| Description | S2 Listmonk fait des requêtes à des services externes pour certains tests (newsletter sending serait l'usage typique). Nous n'avons pas couvert ce chemin ; nos tests S2 sont API-only sur les lists/subscribers. Idem S4 Umami : `e2e_send_event` simule un page-view local mais sans tracking script JS réel. |
| Conséquence | La couverture est subset-of-real-usage. Le claim "isolation marche sur ces stacks" doit être nuancé : "isolation marche sur les chemins API testés". |
| Mitigation possible | Étendre les tests avec des assertions sur le tracking pipeline (S4) ou l'envoi de newsletter (S2). ~1-2 jours par sujet + risque flaky-test. |
| Recommandation | Acknowledgment honnête. Pas critique pour la thèse principale (isolation DB). |

---

## L6 — Moderate : un seul moteur DB (PostgreSQL 15.6)

| Champ | Valeur |
|---|---|
| Sévérité | **moderate** |
| Description | Toutes les expériences utilisent PostgreSQL 15.6. L'operator restore script utilise `pg_dump` + `psql`. Pas de test avec MySQL, MariaDB, SQLite. |
| Conséquence | Les claims sur "checkpoint isolation across stacks" porte sur "stacks SUT" mais "monoculture DB". |
| Mitigation possible | Ajouter au moins un sujet avec MySQL (ex : WordPress). ~1 semaine dev + setup. |
| Recommandation | Acknowledgment + future work. Le mécanisme conceptuel (`DUMP+RESTORE` entre suites) est généralisable, mais pas démontré empiriquement sur d'autres moteurs. |

---

## L7 — Minor : cluster unique (AKS 3× D4s_v3)

| Champ | Valeur |
|---|---|
| Sévérité | **minor** |
| Description | Toutes les mesures sont sur le même cluster. Les valeurs absolues (checkpoint cost 14.6s) varieraient sur un cluster plus puissant ou plus lent. |
| Conséquence | Le claim "envelope [14.2, 16.0]s" est cluster-dependent. |
| Mitigation possible | Re-run RQ3 sur un second cluster (Kind local + EKS / GKE). Coût modéré. |
| Recommandation | Sub-section "Cross-substrate validation" déjà couverte partiellement (Kind 14.6s + AKS 14.9s combiné). Étendre à un 3e substrat est bonus. |

---

## L8 — Minor : pas de répliquation multi-jour (variance temporelle)

| Champ | Valeur |
|---|---|
| Sévérité | **minor** |
| Description | Toutes les runs ont été faites sur 2-3 jours consécutifs (14-17/05). Pas de mesure de variance multi-semaines (effets cluster, mises à jour Azure, etc.). |
| Mitigation possible | Re-runner les RQ après 2 semaines. |
| Recommandation | Acknowledgment ; pas critique. |

---

## L9 — Minor : configuration operator non hyperparam-explorée

| Champ | Valeur |
|---|---|
| Sévérité | **minor** |
| Description | preview-operator a des paramètres (timeouts, parallelism limits, image pull policies). Aucune sensitivity analysis. |
| Mitigation possible | Mini sweep sur 1-2 paramètres clés. |
| Recommandation | Acknowledgment ; pas critique pour la thèse principale. |

---

## L10 — Minor : harness Python (vs autre langage)

| Champ | Valeur |
|---|---|
| Sévérité | **minor** |
| Description | Les tests sont écrits en Python pour les 5 sujets (même pour les SUT non-Python). Ce choix simplifie le harness mais peut influencer le profil de timing. |
| Mitigation | N/A — choix méthodologique. |
| Recommandation | Acknowledgment court dans la section méthode. |

---

## Synthèse — limitations à mettre dans le papier

### Section "Threats to Validity"

| Sévérité | Limitation | Mitigation in-paper |
|---|---|---|
| Critical | L1 single-operator | Related Work section + qualitative comparison table |
| Critical | L2 RQ4 1-subject | Explicit scope statement + S2/S3/S4/S5 reported as architectural exception |
| Moderate | L3 RQ5 instrumentation | Section "Operator reliability — preliminary evidence" + future work |
| Moderate | L4 migration_reset theoretical | "Theoretical comparison" label, not "measured baseline" |
| Moderate | L5 stacks coverage subset | Acknowledgment, "API-level isolation, not full app behavior" |
| Moderate | L6 PostgreSQL only | Acknowledgment, "mechanism generalizable but not empirically demonstrated" |
| Minor | L7-L10 | One paragraph in "Threats to External Validity" |

### Section "Future Work"

- baseline operator implementations (migration reset, transaction rollback)
- per-SUT mutation catalogs for RQ4
- PHASE 8 v2 RQ5 instrumentation (duplicate_job_count, lost_status_count, etc.)
- multi-DB extension (MySQL, MariaDB)
- multi-cluster + multi-week replication
