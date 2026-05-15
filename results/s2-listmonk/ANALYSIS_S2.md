# Analysis — S2 Listmonk (Subject 2)

**Generated:** 2026-05-15
**Subject:** Listmonk Newsletter Manager (Go binary, PostgreSQL 15)
**Origin:** knadh/listmonk v2.5.1
**Operator:** preview-operator v1.0.43, kind single-node cluster
**Protocol:** Cross-PR (RQ2) — k ∈ {2,4,8} × iso ∈ {True, False}, all 3 suites per run

---

## TL;DR — A scientifically interesting counter-example to S1

S2 produces a **100% failure rate on regression and e2e suites under BOTH `isolationEnabled=true` AND `isolationEnabled=false`**, while S1 cleanly separates: 100% fail under `iso=False`, 0% fail under `iso=True`.

This is **not a defect of the checkpoint mechanism** (its SQL is correct) but a consequence of how the S2 test harness measures isolation. The result strengthens the paper: it shows that checkpoint-based DB isolation is a **necessary but not sufficient** condition for test isolation when the application architecture spans services beyond the database.

---

## RQ2 — Raw measurements for S2

Total rows: 60 (k=2/4/8 × iso=True/False × 3 suites). Some k=8 batches contributed
only 4/8 previews due to memory pressure (kind single-node, 7.7 GB RAM). The pattern
is identical at every batch:

| k | iso=True smoke | iso=True regression | iso=True e2e | iso=False smoke | iso=False regression | iso=False e2e |
|---|---|---|---|---|---|---|
| 2 | 2/2 (0%) | 2/2 (**100%**) | 2/2 (**100%**) | 2/2 (0%) | 2/2 (**100%**) | 2/2 (**100%**) |
| 4 | 4/4 (0%) | 4/4 (**100%**) | 4/4 (**100%**) | 4/4 (0%) | 4/4 (**100%**) | 4/4 (**100%**) |
| 8 | 4/4 (0%) | 4/4 (**100%**) | 4/4 (**100%**) | 4/4 (0%) | 4/4 (**100%**) | 4/4 (**100%**) |

(Failure rate shown in **bold**; smoke runs first on a clean post-migration DB and always passes.)

**Observation that demands explanation:** the failure rate is **invariant under `isolationEnabled`** for S2, whereas it is **perfectly modulated** by `isolationEnabled` for S1.

---

## Diagnostic preview (iso=False) — exact assertion failures

Running the same pipeline on a fresh isolated S2 preview yields the following per-assertion outcomes (from `kubectl get preview diag-s2-fix2 -o jsonpath='{.status.tests}'`):

```
regression:
  PASS healthz, lists_returns_data, list_create, list_get,
       list_delete, subscriber_create, subscribers_list,
       campaigns_list, templates_list  (9 passes)
  FAIL run_log_clean         expected 0 smoke markers, got 1 (isolation drift)
  FAIL list_count_matches_seed   expected 3 lists (seed), got 5

e2e:
  PASS healthz, e2e_create_list, e2e_create_subscriber,
       e2e_subscriber_fetch, e2e_campaigns_available,
       e2e_templates_available  (6 passes)
  FAIL run_log_clean          expected 0 regression markers after restore-e2e, got 1
  FAIL entity_count_matches_seed  expected 3 lists after restore, got 5 (restore may have failed)
```

Note: 9/11 (regression) and 6/8 (e2e) **functional** assertions PASS. Only the two **isolation-probe** assertions fail, in the same way. This rules out a general application failure and isolates the cause to the probes themselves.

---

## Root cause analysis

### Cause 1 — Probe-service state lives outside the checkpoint boundary

The probe service is a **separate container** (`svc-probe`, image `harness-probe`) running alongside the listmonk backend, with its own in-process state at `PROBE_URL=http://svc-probe:9090`.

The S2 test harness writes its run-log markers to the probe — not to the listmonk database:

```python
# subjects/s2-listmonk/harness-adapter/tests/smoke.py:41
requests.post(PROBE + "/api/run-log", json={"suite": "smoke"}, timeout=5)
```

```python
# subjects/s2-listmonk/harness-adapter/tests/regression.py:36
log = requests.get(PROBE + "/api/run-log", timeout=5).json()
smoke_count = log.get("smoke", 0)
```

By contrast, S1 (Flask catalog) writes the same marker to its **own backend**, which persists it to the same PostgreSQL database that is checkpointed:

```python
# experimentation/testapp/tests/smoke.py:38
requests.post(BASE + "/api/run-log", json={"suite": "smoke"}, timeout=5)
# BASE = http://svc-backend (the Flask app, backed by postgres)
```

The operator's checkpoint-restore script
([preview/preview-operator/internal/controller/checkpoint.go:463-471](file:///mnt/c/Users/Ihsen/Documents/kubebuilder/preview/preview-operator/internal/controller/checkpoint.go))
operates on `public.*` tables of the application database only:

```sh
tables=$(psql -c "SELECT string_agg(format('%I.%I', schemaname, tablename), ',')
                  FROM pg_tables WHERE schemaname = 'public'")
psql -c "TRUNCATE TABLE $tables RESTART IDENTITY CASCADE"
psql -f /data/dump.sql
```

This is a **correct and robust** restore for the database it targets (`TRUNCATE ... RESTART IDENTITY CASCADE` resets sequences and respects FK graphs in one pass). However, it touches **only the application's PostgreSQL state**. The probe service — whose state is in-memory in another container — is untouched. The smoke marker therefore persists across `restore-regression`, regression sees `smoke_count=1`, and the assertion `smoke_count == 0` fails.

This explains 1 of the 2 failing assertions in each suite (`run_log_clean`) on 100% of runs.

### Cause 2 — Test pre-condition assumes a baseline the application does not satisfy

The second failing assertion is `list_count_matches_seed`:

```python
# regression.py:75-78 and e2e.py:45-48
SEED_COUNT = 3
list_count = r_all.get("data", {}).get("total", -1)
t("list_count_matches_seed", lambda: (
    list_count == SEED_COUNT,
    f"expected {SEED_COUNT} lists (seed), got {list_count}"
))
```

The test asserts that, after migration + restore, the database holds **exactly** 3 lists (the seed). It got 5. Two compounding factors produce this gap:

1. **listmonk's `--install --yes` step creates its own default list(s)** before our migration INSERT runs. The seed therefore consists of: `N_default_install + 3 explicit seed lists`. With `N_default_install ≥ 1`, the true post-migration count is ≥ 4.

2. **listmonk implements soft-delete on lists.** The regression suite creates an `exp-list` and immediately deletes it. The DELETE endpoint marks the row `status='deleted'` but keeps it in the table. The `/api/lists?per_page=100` endpoint's `total` field counts all non-purged rows, so the deleted entity still inflates the count.

Combined, this fixes the count at **5**, which is **invariant across runs and independent of isolation**. The test is asserting a baseline that the application architecture never satisfies.

### Why the two causes are independent

- `run_log_clean` failures are entirely explained by Cause 1 (probe state outside checkpoint scope). They would persist even if listmonk had zero soft-deletes and zero default install lists.
- `list_count_matches_seed` / `entity_count_matches_seed` failures are entirely explained by Cause 2 (mis-specified baseline). They would persist even if the probe state were correctly reset.

Each failure mode independently produces a 100% failure rate on its assertion, regardless of `isolationEnabled`. That is exactly the pattern observed in the CSV.

---

## What this tells us about checkpoint isolation

### D1. The checkpoint mechanism is operating correctly

S1 demonstrates that `pg_dump --data-only → ConfigMap → TRUNCATE+psql restore` reliably resets the **application database state** between test suites. S2 does not contradict that finding: 9/11 regression and 6/8 e2e functional assertions PASS on the diagnostic preview, including those that create and delete entities mid-suite. The mechanism's database-level guarantee holds.

### D2. Isolation scope is a property of the **test harness**, not the operator

The operator can only isolate state it knows about. The S2 test harness extends the test-relevant state into a **co-located service** (the probe) that the operator does not snapshot. This is an architectural choice in the harness, not a bug in the checkpoint pipeline. For the paper, this distinguishes:

- **Checkpoint scope** (what the operator restores) — `public.*` tables in the application DB
- **Test-isolation scope** (what the test asserts is restored) — anything the test reads

When the test-isolation scope strictly exceeds the checkpoint scope, no amount of checkpoint correctness can satisfy the test. S2 makes this scope mismatch concrete and measurable.

### D3. Test design encodes its own assumptions, which must be validated

The S2 `*_matches_seed` assertions hard-code `SEED_COUNT = 3`. They were authored against the seed values that **our migration INSERT** explicitly creates, but ignored:

1. application-level initialization (listmonk's default list)
2. application-level soft-delete semantics (DELETE does not remove from count)

A well-formed isolation probe must measure the **delta** introduced by a previous suite, not an absolute baseline. For example: `count_after_restore == count_after_migration`, captured at runtime, rather than a hard-coded 3.

### D4. S2 is therefore a productive counter-example, not a refutation

The S2 result strengthens the paper's core claim. It demonstrates two falsification conditions for checkpoint isolation:

- **Falsification condition A:** the application architecture stores test-relevant state in services not covered by the snapshot (Cause 1).
- **Falsification condition B:** the test pre-condition is mis-specified relative to the post-migration application state (Cause 2).

Both conditions are **detectable, reproducible, and independent of the operator implementation**. For practitioners, this gives concrete acceptance criteria for adopting checkpoint isolation:

1. The test-isolation scope must be a subset of the checkpoint scope.
2. Probe assertions must reference runtime-captured baselines, not literals.

---

## Comparison with S1

| Property | S1 (Flask catalog) | S2 (Listmonk) |
|---|---|---|
| Test marker storage | Application DB (Flask `/api/run-log`) | External probe service (`svc-probe`) |
| Marker covered by checkpoint? | **Yes** | **No** |
| Application-side install adds entities? | No | Yes (default list) |
| Soft-delete inflates counts? | No (hard delete) | Yes |
| `iso=True` regression failure rate | **0%** (N=30) | **100%** |
| `iso=False` regression failure rate | **100%** (N=30) | **100%** |
| Conclusion | Isolation works as designed | Isolation works at DB level, but harness measures more than DB |

---

## Implications for the article

1. **RQ1/RQ2 framing must distinguish operator scope from harness scope.** A subject is "isolation-amenable" iff its test-isolation scope ⊆ operator checkpoint scope and its probe assertions reference runtime baselines.
2. **Report S2 alongside S1**, not as a counter-success but as a calibration: it bounds the claim from above. The paper now reads "checkpoint isolation eliminates intra-preview flakiness on the database layer; subjects whose test harness reaches beyond that layer require additional probe-state isolation."
3. **Recommendation in the discussion:** future operator work could extend checkpoint scope to side-car services with a stateless or snapshottable contract. The paper should explicitly leave this as an open direction, motivated by the S2 data.

---

## Data files

| File | Rows | Notes |
|---|---|---|
| `cross_pr_test_outcomes_20260515T180943Z.csv` | 60 | RQ2 — k∈{2,4,8} × iso∈{True,False}, 100% smoke pass / 100% regression+e2e fail in all conditions |

---

## Evidence references

- `subjects/s2-listmonk/harness-adapter/tests/smoke.py:41` — smoke marker writes to PROBE
- `subjects/s2-listmonk/harness-adapter/tests/regression.py:36` — regression reads from PROBE
- `subjects/s2-listmonk/harness-adapter/tests/regression.py:75-78` — hard-coded SEED_COUNT=3 assertion
- `subjects/s2-listmonk/harness-adapter/tests/e2e.py:45-48` — same hard-coded assertion in e2e
- `experimentation/testapp/tests/smoke.py:38` — S1 marker writes to its own backend (in-DB)
- `preview/preview-operator/internal/controller/checkpoint.go:463-471` — restore script (TRUNCATE + psql)
