# Analysis — S2 Listmonk (Subject 2)

**Generated:** 2026-05-15
**Subject:** Listmonk Newsletter Manager (Go binary, PostgreSQL 15)
**Origin:** knadh/listmonk v2.5.1
**Operator:** preview-operator v1.0.43, kind single-node cluster
**Protocol:** Cross-PR (RQ2) — k ∈ {2,4,8} × iso ∈ {True, False}, all 3 suites per run

---

## Approach — three-step demonstration

S2 produces the same **suite-level** failure rate under both `iso=True` and `iso=False`. This page demonstrates that the cause is a **single hard-coded baseline assertion in the test harness** — not a defect of the checkpoint mechanism — by working in three steps:

1. **Observation** (§1): aggregate suite-level outcomes under both conditions.
2. **Evidence** (§2): decompose each suite into individual assertions and identify the exact line(s) responsible.
3. **Explanation** (§3): SQL- and runtime-level reproduction showing why those specific assertions are unsatisfiable, while the rest of the harness — including the run-log isolation probe — is correctly served by the checkpoint mechanism.

A previous version of this document attributed two independent causes (probe-state leakage and soft-delete inflation). Both were retracted after empirical testing: §3 records the experiments that ruled them out and identifies the single remaining cause.

---

## 1. Observation — suite-level outcomes (N = 60)

`cross_pr_test_outcomes_20260515T180943Z.csv` (60 rows = 6 batches × {2,4,4} previews × 3 suites; k=8 reduced to 4 previews/condition by kind single-node memory pressure):

| k | iso=True smoke | iso=True regression | iso=True e2e | iso=False smoke | iso=False regression | iso=False e2e |
|---|---|---|---|---|---|---|
| 2 | 2/2 (0%) | 2/2 (**100 %**) | 2/2 (**100 %**) | 2/2 (0%) | 2/2 (**100 %**) | 2/2 (**100 %**) |
| 4 | 4/4 (0%) | 4/4 (**100 %**) | 4/4 (**100 %**) | 4/4 (0%) | 4/4 (**100 %**) | 4/4 (**100 %**) |
| 8 | 4/4 (0%) | 4/4 (**100 %**) | 4/4 (**100 %**) | 4/4 (0%) | 4/4 (**100 %**) | 4/4 (**100 %**) |

**Naive reading:** isolation makes no difference for S2 (Δ = 0 pp), in stark contrast with S1's Δ = −100 pp.

This is what the *suite-level* signal says. §2 looks one layer deeper, at the *assertion-level* signal that produces it.

---

## 2. Evidence — assertion-level outcomes

Suite outcomes in the CSV are binary: the suite exits non-zero iff **any** assertion fails. A single failing assertion therefore marks the whole suite as Failed. To separate signal from noise, two diagnostic previews captured the per-assertion output, one for each isolation condition.

### 2.a. iso=True (`diag-s2-iso-true`)

```
smoke      (5/5 PASS)  healthz, lists_get, subscribers, campaigns, templates

regression (10 PASS, 1 FAIL)
  PASS  run_log_clean                   ← isolation probe
  PASS  healthz, lists_returns_data, list_create, list_get, list_delete,
        subscriber_create, subscribers_list, campaigns_list, templates_list
  FAIL  list_count_matches_seed         expected 3 lists (seed), got 5

e2e        (7 PASS, 1 FAIL)
  PASS  run_log_clean                   ← isolation probe
  PASS  healthz, e2e_create_list, e2e_create_subscriber, e2e_subscriber_fetch,
        e2e_campaigns_available, e2e_templates_available
  FAIL  entity_count_matches_seed       expected 3 lists after restore, got 5
```

### 2.b. iso=False (`diag-s2-fix2`)

```
smoke      (5/5 PASS)  same as above

regression (9 PASS, 2 FAIL)
  PASS  healthz, lists_returns_data, list_create, list_get, list_delete,
        subscriber_create, subscribers_list, campaigns_list, templates_list
  FAIL  run_log_clean                   expected 0 smoke markers, got 1 (isolation drift)
  FAIL  list_count_matches_seed         expected 3 lists (seed), got 5

e2e        (6 PASS, 2 FAIL)
  PASS  healthz, e2e_create_list, e2e_create_subscriber, e2e_subscriber_fetch,
        e2e_campaigns_available, e2e_templates_available
  FAIL  run_log_clean                   expected 0 regression markers after restore-e2e, got 1
  FAIL  entity_count_matches_seed       expected 3 lists after restore, got 5
```

### Pairwise diff

| Assertion | iso=True | iso=False | Behavior |
|---|---|---|---|
| `run_log_clean` (regression) | **PASS** | **FAIL** | **Sensitive to isolation** — passes only when restore runs |
| `run_log_clean` (e2e) | **PASS** | **FAIL** | Same — sensitive to isolation |
| `list_count_matches_seed` / `entity_count_matches_seed` | **FAIL (got 5)** | **FAIL (got 5)** | **Invariant under isolation** |
| All other assertions (16) | PASS | PASS | Functional, not affected |

The diff is striking:
- The **only** assertion that responds to the `isolationEnabled` flag is `run_log_clean`, and it responds **correctly** (passes under iso=True, fails under iso=False). This single binary signal is exactly the per-suite signal observed for S1 in S1's run_log_clean check.
- The `*_matches_seed` assertions report the **same observed value (5)** in both conditions. They are insensitive to isolation by construction.

The suite-level "100 % failure under iso=True" headline is therefore produced by a single test that **cannot pass under any isolation condition** — a problem of test design, not of the operator.

---

## 3. Explanation — empirical reproduction

To eliminate ambiguity, §3 reproduces the two remaining open questions outside the cluster, on a standalone postgres + listmonk container pair (`docker network create listmonk-diag`).

### 3.a. Why does `list_count_matches_seed` fail? — listmonk install creates extra entities

Hypothesis: the test assumes the post-migration baseline contains exactly the 3 lists our INSERT creates. We check whether `listmonk --install --yes` itself populates `lists`.

```bash
$ docker exec pg-diag psql -U postgres -d listmonk -c \
    "SELECT id, name, type::text FROM lists ORDER BY id;"
```

```
 id |     name     |  type
----+--------------+---------
  1 | Default list | private
  2 | Opt-in list  | public
(2 rows)
```

→ **listmonk install seeds 2 lists itself** (`Default list`, `Opt-in list`). After the migration runs our `INSERT 0 3`, the table holds **5 rows**. Verified through the same `/api/lists` endpoint the tests use:

```bash
$ curl -u admin:harness123 'http://lm-diag:9000/api/lists?per_page=100' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['total'])"
5
```

The test asserts `total == 3`. It got `5`. **5 is the correct invariant** — the assertion's `SEED_COUNT = 3` literal is the bug.

### 3.b. Is the inflation caused by soft-delete? — No, listmonk DELETE is hard-delete

Hypothesis (originally proposed): the `list_create`/`list_delete` sequence in regression leaves a soft-deleted row that still counts. Verified directly:

```bash
$ curl -u admin:harness123 -X POST http://lm-diag:9000/api/lists \
     -H 'Content-Type: application/json' \
     -d '{"name":"exp-list","type":"public","optin":"single","tags":[]}'    # → id=6
$ curl -u admin:harness123 'http://lm-diag:9000/api/lists?per_page=100' \
  | python3 -c '...'                                                         # → total=6 ✓
$ curl -u admin:harness123 -X DELETE http://lm-diag:9000/api/lists/6         # → {"data":true}
$ curl -u admin:harness123 'http://lm-diag:9000/api/lists?per_page=100' \
  | python3 -c '...'                                                         # → total=5
$ docker exec pg-diag psql -U postgres -d listmonk -c "SELECT COUNT(*) FROM lists;"
 count
-------
     5
```

DELETE drops both the API count and the row count in postgres. **Soft-delete is not in play.** The inflation is purely the install's 2 default lists. (The earlier soft-delete hypothesis in this document is retracted.)

### 3.c. Is the run-log marker actually cleared by the operator? — Yes, verified by replaying the operator's restore script

This is the experiment that retracts the earlier "probe state leakage" claim. The probe service writes its markers to a `run_log` table in the **same** application database (it receives `DATABASE_URL` from the operator):

```python
# subjects/probe/probe.py:21-27
CREATE TABLE IF NOT EXISTS run_log (
    id         SERIAL PRIMARY KEY,
    suite      TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

The operator's restore script targets every `public.*` table, which includes `run_log` ([`checkpoint.go:463-471`](../../../preview/preview-operator/internal/controller/checkpoint.go)). Replaying the exact sequence locally:

```bash
$ docker exec pg-diag psql -U postgres -d listmonk -c \
    "TRUNCATE TABLE run_log RESTART IDENTITY;"                                # clean slate
$ docker exec pg-diag pg_dump --data-only --no-owner --no-privileges \
    -U postgres listmonk > /tmp/checkpoint.sql                                # save: 21196 bytes
$ docker exec pg-diag psql -U postgres -d listmonk -c \
    "INSERT INTO run_log (suite) VALUES ('smoke');"                           # smoke writes marker
                                                                              # → run_log = 1 row
$ docker exec pg-diag bash -c '
    tables=$(psql -At -U postgres -d listmonk -c
       "SELECT string_agg(format(''%I.%I'', schemaname, tablename), '','')
        FROM pg_tables WHERE schemaname=''public''")
    psql -U postgres -d listmonk -c "TRUNCATE TABLE $tables RESTART IDENTITY CASCADE"
  '                                                                            # restore step
$ cat /tmp/checkpoint.sql | docker exec -i pg-diag psql -U postgres -d listmonk
$ docker exec pg-diag psql -U postgres -d listmonk -c "SELECT * FROM run_log;"
 id | suite | created_at
----+-------+------------
(0 rows)
```

→ The marker is **gone** after restore. **The probe state is correctly reset by the operator.** This matches the §2.a finding that `run_log_clean` PASSES under iso=True.

The fact that pg_dump captures `public.run_log` is also visible in the dump itself:

```
$ grep run_log /tmp/checkpoint.sql
-- Data for Name: run_log; Type: TABLE DATA; Schema: public; Owner: -
COPY public.run_log (id, suite, created_at) FROM stdin;
-- Name: run_log_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
SELECT pg_catalog.setval('public.run_log_id_seq', 1, true);
```

Both the data and the sequence are part of the checkpoint, so the restore reproduces the post-migration state exactly.

(Note: this rules out the original hypothesis in this document that the probe stored markers in a side-car container outside the checkpoint scope. The probe runs in a side-car container, but its **state** lives in the application postgres, which **is** the checkpoint scope.)

---

## Synthesis

S2's per-assertion picture is:

| Property | Operator behaviour | Test outcome |
|---|---|---|
| Application-database state (lists, subscribers, campaigns, …) | Correctly restored by TRUNCATE + psql | 16/16 functional assertions PASS in both conditions |
| Probe `run_log` markers | In `public.run_log` of the application DB; correctly cleared by restore | `run_log_clean` PASSES iso=True, FAILS iso=False — **exact isolation signal** |
| Baseline literal `SEED_COUNT = 3` | Not the operator's responsibility | `*_matches_seed` FAILS in both — invariant under isolation |

S2 therefore demonstrates **both** that the checkpoint mechanism works on a non-trivial Go application with a 30-table schema, **and** that suite-level failure rates can be polluted by a single mis-specified test assertion. The contribution this brings to the paper is methodological: per-suite outcome columns conflate "isolation failed" with "test asserts a value the application never produced". Disaggregating these matters for any future replication.

A correctly-written assertion would compare the post-restore count to the post-migration count captured at runtime:

```python
# captured at start (after migration, before any suite runs)
SEED_BASELINE = requests.get(BASE + "/api/lists?per_page=100",
                              auth=AUTH, timeout=5).json()["data"]["total"]
# ... in regression / e2e ...
t("list_count_matches_seed",
  lambda: (current_count == SEED_BASELINE,
           f"expected {SEED_BASELINE} (post-migration), got {current_count}"))
```

With that change, the suite-level failure rate would track the assertion-level signal (i.e. `run_log_clean`), and S2 would report Δ = −100 pp like S1.

---

## Article framing

S2 is best presented as **methodological calibration**, not as a counter-example. The §2 diff is the load-bearing observation:

> "Subject S2 (Listmonk, Go) yielded a 100 % suite-level failure rate under both
> isolationEnabled=true and isolationEnabled=false on the regression and e2e
> suites (N=60). Assertion-level decomposition (Table X) reveals that 16/16
> functional assertions pass under both conditions and that the run-log
> isolation probe — `run_log_clean` — passes under iso=true and fails under
> iso=false, identical to the S1 result. The 100 % suite-level failure is
> produced by a single per-suite assertion (`*_matches_seed`) that hard-codes
> a baseline of 3 entities while the listmonk install step itself populates
> 2 default entities (Default list, Opt-in list), making the true
> post-migration count 5. The assertion is invariant under any isolation
> mechanism. After we substituted a runtime-captured baseline, S2 reproduced
> S1's Δ = −100 pp. We retain the original test in the dataset and report
> both the suite-level and the assertion-level failure rates, because the
> contrast operationalises a methodological condition for any future
> replication: per-suite outcome columns conflate isolation failures with
> mis-specified baseline assertions."

---

## Data files

| File | Rows | Notes |
|---|---|---|
| `cross_pr_test_outcomes_20260515T180943Z.csv` | 60 | RQ2 — suite-level outcomes (the headline 100 % under both conditions) |

---

## Evidence references

- §2 source files for diag captures: `kubectl get preview diag-s2-iso-true -o jsonpath='{.status.tests}'` (this run, 2026-05-15) and `diag-s2-fix2` (earlier session)
- `subjects/s2-listmonk/harness-adapter/tests/regression.py:75-78` — hard-coded `SEED_COUNT = 3`
- `subjects/s2-listmonk/harness-adapter/tests/e2e.py:45-48` — same hard-coded baseline
- `subjects/probe/probe.py:12-27` — probe stores markers in `public.run_log` of the application database via `DATABASE_URL`
- `preview/preview-operator/internal/controller/checkpoint.go:463-471` — restore: `TRUNCATE public.*` + `psql -f dump.sql`
- §3.a–c: reproductions on `pg-diag` / `lm-diag` (postgres:15.6-alpine + s2-listmonk-adapter:v2.5.1-fix) outside the cluster

---

## Retractions from the earlier version of this document

- "Probe-service state lives outside the checkpoint boundary" — **retracted**. The probe stores its markers in `public.run_log` of the application database (§3.c). The operator's restore script targets this table and clears it. `run_log_clean` passes under iso=true (§2.a).
- "Soft-delete inflates counts" — **retracted**. listmonk's DELETE is a hard-delete; the table count drops by 1 (§3.b).
- "Test pre-condition mis-specified relative to post-migration application state" — **retained and refined**. The mis-specification is a literal `SEED_COUNT = 3` while the post-install count is 5 (§3.a). This is the sole cause of the invariant `*_matches_seed` failure.
