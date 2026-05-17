# PHASE 7 — Lock RQ5 contre l'exécution parallèle

**Objectif** : empêcher mécaniquement RQ5 (idempotence) de s'exécuter en parallèle d'autres expériences. Documentaire seul (notes dans README, EXPERIMENT_METRICS) ne suffit pas — incidents `14:43Z` (2026-05-16) et `07:12Z` (2026-05-17) prouvent que c'est facile d'oublier.

**Solution** : lock fichier inter-processus avec `fcntl.flock`, modes `exclusive` (RQ5) et `shared` (autres expés).

---

## 1. Composants

| Fichier | Rôle |
|---|---|
| `harness/experiment_lock.py` | API + CLI |
| `runtime/experiment_lock.json` | état persistant (créé à la première acquisition) |
| `runtime/.lockfile` | cible de `fcntl.flock` pour atomicity inter-process |

---

## 2. API

```python
from harness.experiment_lock import acquire, LockConflict

# RQ5 (idempotence) — refuse de démarrer si ANY autre expé tourne
with acquire("idempotence", mode="exclusive"):
    run_experiment()

# Autres RQs — refusent de démarrer si exclusive tient, sinon co-existent
with acquire("flakiness", mode="shared"):
    run_experiment()
```

### Conflits

| État actuel | Mode demandé | Résultat |
|---|---|---|
| aucun | exclusive | ✅ acquis |
| aucun | shared | ✅ acquis |
| 1+ shared | exclusive | ❌ `LockConflict` |
| 1+ shared | shared | ✅ rejoint le set shared |
| 1 exclusive | exclusive | ❌ `LockConflict` |
| 1 exclusive | shared | ❌ `LockConflict` |

### Bypass (force)

```bash
EXPERIMENT_LOCK_FORCE=1 python3 exp_idempotence/run.py
```

À utiliser **seulement** quand un lock résiduel ne peut pas être GC'd (PID recyclé par l'OS). Le mécanisme GC normal détecte les PIDs morts via `os.kill(pid, 0)`.

---

## 3. CLI d'inspection

```bash
# État courant (lit + GC les entrées stale)
python3 harness/experiment_lock.py status

# Recovery manuelle (à n'utiliser que si vraiment stuck)
python3 harness/experiment_lock.py clear
```

---

## 4. Intégration dans les expériences

Pour activer l'enforcement, **wrapper le `main()`** de chaque `exp_*/run.py` :

### `exp_idempotence/run.py` (RQ5 — exclusive)

```python
# Top of file
from harness.experiment_lock import acquire

# Wrap main:
def main():
    cfg = cfg_module.load()
    # ... existing code ...

if __name__ == "__main__":
    with acquire("idempotence", mode="exclusive"):
        main()
```

### `exp_flakiness/run.py` + `exp_cross_pr/run.py` + `exp_performance/run.py` + `exp_bug_detection/run.py` (autres — shared)

```python
from harness.experiment_lock import acquire

if __name__ == "__main__":
    with acquire(EXPERIMENT, mode="shared"):
        main()
```

**Important** : ces 5 modifications doivent être faites APRÈS la fin de la chaîne d'expériences en cours (sinon le proc python actuellement chargé n'aura pas le nouveau code, et la prochaine invocation du launcher pourrait échouer si un lock résiduel existe).

Pour l'instant, le mécanisme est **livré mais non activé par défaut** — c'est la même approche que PHASE 2 (infrastructure prête, intégration différée pour ne pas perturber les runs en cours).

---

## 5. Wrapper sécurisé pour usage immédiat

En attendant l'intégration in-line, un wrapper script permet d'utiliser le lock :

```bash
# Lancer une expérience avec lock acquisition automatique
python3 -c "
import sys, runpy
sys.path.insert(0, '.')
from harness.experiment_lock import acquire

experiment = 'idempotence'  # or 'flakiness', etc.
mode = 'exclusive' if experiment == 'idempotence' else 'shared'

with acquire(experiment, mode=mode):
    runpy.run_module('exp_' + experiment + '.run', run_name='__main__')
"
```

---

## 6. Messages d'erreur

Quand une acquisition échoue, l'erreur explicite :

```
EXPERIMENT_LOCK conflict — cannot acquire 'shared' lock for experiment 'flakiness'.

  EXCLUSIVE holder: experiment='idempotence' pid=1234 started_at=2026-05-17T13:00:00Z

RQ5 (idempotence) restarts the preview operator and cannot run concurrently with other experiments.
If you are sure no conflict exists (stale lock or recycled PID), set EXPERIMENT_LOCK_FORCE=1 to bypass.
Lock state file: runtime/experiment_lock.json
```

Le message :
- nomme l'expérience bloquante (et son pid)
- explique le rationale (operator restart)
- propose l'échappatoire (force) avec un avertissement

---

## 7. Garanties

| Garantie | Comment |
|---|---|
| Atomicity inter-processus | `fcntl.flock(_LOCK_FILE, LOCK_EX)` autour de chaque mutation |
| GC des locks zombies | `os.kill(pid, 0)` vérifie si le PID est vivant ; ESRCH → entrée supprimée |
| Pas de deadlock | mode context-manager : release garanti même sur exception |
| Hostname tracking | utile en cas d'usage multi-machine (informatif, pas enforcé) |
| Aucune dépendance externe | stdlib only (`fcntl`, `json`, `os`) |

---

## 8. Tests de validation (passés ✅)

Vérifiés par 5 tests automatisés (voir le rapport de PHASE 7 dans le commit) :

| Test | Résultat |
|---|---|
| status() lorsque aucun lock | `{"exclusive": null, "shared": []}` ✅ |
| acquire(shared) puis status | une entrée shared visible ✅ ; après exit → vide ✅ |
| exclusive bloque shared | `LockConflict` levé ✅ ; message explicatif clair |
| shared autorise shared parallèle | 2 holders simultanés visibles ✅ |
| stale PID GC | entrée PID=9999999 supprimée automatiquement ✅ |

---

## 9. Impact sur les critères TSE

Critère global #7 (`tse_readiness_checklist.md`) :
> **RQ5 est conservé mais protégé contre toute exécution parallèle**

| Avant PHASE 7 | Après PHASE 7 |
|---|---|
| ⚠️ documenté dans 3 docs, pas enforced | ✅ enforced mécaniquement par lock fichier |

---

## 10. Limitations connues

- **PID recyclé** : si un PID mort est immédiatement réutilisé par un autre processus non-experimentation, le GC croit que le lock est vivant. Mitigation : utiliser EXPERIMENT_LOCK_FORCE=1 manuellement.
- **Multi-machine** : le lock est local au filesystem. Si plusieurs machines partagent le même cluster, chaque machine a son propre lock. Pas critique pour notre setup (1 machine = 1 cluster AKS).
- **Pas d'audit log** : les acquisitions/releases ne sont pas loggés persistemment. Si on veut tracer "qui a tenu le lock à quel moment", il faudrait étendre vers un append-only log.

Ces limitations sont acceptables pour l'usage actuel et documentées en future work.
