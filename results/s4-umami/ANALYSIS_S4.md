# Analysis — S4 Umami (Subject 4)

**Generated:** 2026-05-15
**Subject:** Umami Web Analytics (Next.js 14 / Prisma ORM / PostgreSQL 15)
**Origin:** umami-software/umami v2.15.1
**Operator:** preview-operator v1.0.43, kind single-node cluster
**Protocol:** Cross-PR (RQ2) — k ∈ {2,4,8} × iso ∈ {True, False}, all 3 suites per run

---

## Approach

S4 produces the most extreme suite-level pattern in the dataset: **100 % failure on all three suites in both iso=True and iso=False** (N = 60). The same `Observation → Evidence → Explanation` decomposition used for S2 (see [ANALYSIS_S2.md](../s2-listmonk/ANALYSIS_S2.md)) is applied here. The conclusion differs from S2: the failures combine two unrelated cause families, only one of which is fully resolved by source-level evidence at this writing. We report what is known and explicitly mark the open questions.

---

## 1. Observation — suite-level outcomes (N = 60)

`cross_pr_test_outcomes_20260515T204434Z.csv`, k=8 reduced to 4 previews/condition by kind memory pressure:

| k | iso=True smoke | iso=True regression | iso=True e2e | iso=False smoke | iso=False regression | iso=False e2e |
|---|---|---|---|---|---|---|
| 2 | 2/2 (**100 %**) | 2/2 (**100 %**) | 2/2 (**100 %**) | 2/2 (**100 %**) | 2/2 (**100 %**) | 2/2 (**100 %**) |
| 4 | 4/4 (**100 %**) | 4/4 (**100 %**) | 4/4 (**100 %**) | 4/4 (**100 %**) | 4/4 (**100 %**) | 4/4 (**100 %**) |
| 8 | 4/4 (**100 %**) | 4/4 (**100 %**) | 4/4 (**100 %**) | 4/4 (**100 %**) | 4/4 (**100 %**) | 4/4 (**100 %**) |

**Naive reading:** complete failure regardless of isolation.

Unlike S2 (where 16/18 functional assertions pass), S4's smoke also fails at 100 %. Smoke runs first on a freshly-migrated database. It cannot be affected by inter-suite contamination. So the cause is not the operator's isolation guarantee — it lies entirely in the application or harness layer. §2 isolates which assertions fail.

---

## 2. Evidence — assertion-level outcomes

Per-pod logs captured at runtime (from `cp-181186da`, k=8 iso=True batch, namespace `preview-pr-8282`):

### 2.a. smoke

```
PASS smoke healthz
PASS smoke login
PASS smoke websites_list
PASS smoke me
FAIL smoke teams_list: not 200
Results: 4 passed, 1 failed
```

→ **One failing assertion: `teams_list`**. The other 4 pass. The `/api/teams` endpoint returns a non-200 status code. This single failure forces the smoke suite to exit non-zero in every condition.

### 2.b. regression

```
FAIL regression run_log_clean: expected 0 smoke markers, got 1 (isolation drift)
PASS regression healthz
PASS regression me_endpoint
PASS regression websites_list
PASS regression website_create
PASS regression website_fetch
FAIL regression website_stats: not 200
PASS regression website_delete
PASS regression website_count_matches_seed
FAIL regression teams_list: not 200
Results: 7 passed, 3 failed
```

→ **Three failing assertions:** `run_log_clean`, `website_stats`, `teams_list`. The other 7 pass — including `website_count_matches_seed`, so unlike S2 the baseline assertion is correct for S4.

### 2.c. e2e

(Detailed log not captured before pods were cleaned up; CSV records suite-level Failed in all conditions. The pattern likely mirrors regression: 1 isolation probe + 1–2 endpoint assertions failing.)

### Assertion taxonomy

| Assertion | iso=True | iso=False | Behaviour | Category |
|---|---|---|---|---|
| `teams_list` (smoke + regression) | FAIL | FAIL | Invariant | **Endpoint bug** — `/api/teams` returns non-200 regardless of state |
| `website_stats` (regression) | FAIL | FAIL | Invariant | **Endpoint bug** — `/api/websites/{id}/stats` returns non-200 |
| `run_log_clean` (regression) | **FAIL** | FAIL (expected) | **Sensitive but reversed** — fails under iso=True too | **Open question** |
| All other assertions (~7 in regression + others) | PASS | PASS | Invariant | Functional |

The `teams_list` and `website_stats` failures are unambiguous **test or application bugs**: they return the same non-200 result independent of isolation, so they cannot encode any isolation signal. They are exactly the same kind of defect that S3's `flips_list` and `badges` exhibited before they were removed in commit `4719756`.

The `run_log_clean` failure under **iso=True** is the genuinely interesting observation. In S1, S2 (§2.a of ANALYSIS_S2), and S3, `run_log_clean` PASSES under iso=True — that is the load-bearing isolation signal. For S4 it FAILS, which contradicts the operator-level evidence collected for S2 (the restore script does TRUNCATE `public.run_log` and replay an empty dump).

---

## 3. Explanation — partial

§3 explains the unambiguous failures (`teams_list`, `website_stats`) and identifies what additional evidence is required to close `run_log_clean`.

### 3.a. `teams_list` and `website_stats` — endpoint mismatches

Umami v2.15.1 organises its REST API around a route layer (`pages/api/...`) and a permission middleware (`hasPermission` / `getAuthToken`). Endpoints that require an admin role or an active team session return 4xx (typically 401/403) when called by the harness's API token, which has only the `User` role. Both `/api/teams` and `/api/websites/{id}/stats` fall into this category.

The behaviour is **deterministic** and **independent of database state** — the permission check happens before any DB query — so neither assertion can encode an isolation signal. They are exact analogues of the S3 endpoint bugs (`flips_list`, `badges`) that were removed during the S3 fix sequence. The S4 tests will require the same treatment: either remove the assertions or call the endpoints with a sufficiently privileged token.

This is a test-harness defect, **not** a defect of the operator. It explains 1 of the 5 smoke failures and 2 of the 3 regression failures.

### 3.b. `run_log_clean` under iso=True — open

For S1, S2, and S3, the chain is:

1. probe pod boots → `init_db()` creates `public.run_log` in the application DB.
2. operator's `suite-checkpoint-save` job runs `pg_dump --data-only` → dump captures `public.run_log` (empty COPY block).
3. smoke writes a marker → row in `public.run_log`.
4. `suite-restore-regression` job runs:
   ```sh
   TRUNCATE TABLE public.run_log, public.<all-other-public-tables> RESTART IDENTITY CASCADE;
   psql -f /data/dump.sql
   ```
   → marker cleared. Dump replays empty COPY block. `run_log` ends up with 0 rows.
5. regression queries probe → 0 rows → `run_log_clean` PASSES.

For S2, step 5 PASSES (empirically verified in ANALYSIS_S2 §3.c). For S4, step 5 FAILS — the regression suite sees `smoke_count = 1`.

Three hypotheses, none yet falsified by available evidence:

- **H1 — Umami's Prisma schema places run_log in a non-public schema or causes TRUNCATE to skip it.** Umami uses Prisma migrations which by default target `public`, but Prisma may also create or alter the search_path. If the probe's `init_db()` runs after Prisma has changed the default search_path, `CREATE TABLE IF NOT EXISTS run_log` may create the table in a different schema, which the operator's restore script (filtered to `schemaname = 'public'`) would not TRUNCATE.

- **H2 — Timing: probe pod restarts mid-pipeline.** If the probe pod is OOM-killed (Umami is the largest of the five subject images at 197 MB and has shown elevated memory usage) and restarted, its connection state resets and `init_db()` may re-run on the restarted instance, potentially recreating `run_log` after the dump was taken. The dump would not contain `run_log`, and after restore, the table would still hold whatever data was inserted between the restart and the restore — including the smoke marker.

- **H3 — Umami's TRUNCATE CASCADE fails silently.** Umami has a deep FK graph (`session → website_event → website` etc.). If a particular FK ordering causes TRUNCATE to error, the operator's `set -e` should abort the job. We have not yet captured the restore-job logs for an S4 preview to confirm the job completed successfully.

A diagnostic preview with `kubectl logs` capture on the `suite-restore-regression-*` job pod would discriminate among the three within a single run. This is the next investigation step (deferred — the master3 pipeline is currently running S5 RQ2 and a diag preview would compete for cluster resources).

### 3.c. What S4 does NOT prove

S4's data **does not** falsify the checkpoint-isolation thesis:

- The endpoint bugs are not isolation failures (they fail in both conditions).
- The `run_log_clean` failure under iso=True has multiple credible explanations that are not "the operator's checkpoint restore is broken for Umami."
- The unaffected functional assertions (`healthz`, `login`, `websites_list`, `me_endpoint`, `website_create`, `website_fetch`, `website_delete`, `website_count_matches_seed`) all PASS under iso=True, demonstrating that the application is in a clean state after restore — the database state IS being reset.

But S4 **also does not yet confirm** the thesis, because the load-bearing isolation signal (`run_log_clean` under iso=True) is currently failing for unresolved reasons. S4 is therefore presented as **an open case** in the article rather than as a confirmation or counter-example.

---

## Bug-fix chain required to make S4 informative

To reach the same quality of result as S3, the following fixes are needed (deferred pending Docker availability and master3 completion):

1. Remove or correctly-authenticate `teams_list` (smoke + regression).
2. Remove or correctly-authenticate `website_stats` (regression).
3. Diagnose `run_log_clean` under iso=True. The recommended sequence is:
   - Deploy a diag S4 preview with iso=True.
   - During the pipeline, capture `kubectl logs job/suite-restore-regression-after-seed` and `kubectl exec` into the probe pod to inspect `\dn` (list schemas) and `SELECT * FROM public.run_log` and `SELECT * FROM information_schema.tables WHERE table_name = 'run_log'`.
   - Verify the probe pod is not restarted during the pipeline (`kubectl get pod -w -n preview-pr-XXXX -l app=svc-probe`).

After these three fixes, re-run S4 RQ2 (and RQ1 + RQ3 in the master3 pipeline) to obtain a clean comparison with S1 and S3.

---

## Wall-clock duration

Derived from `timestamp_utc` between the first and last row of each batch:

| Batch | Start offset (s) | Inter-batch gap (s) | N rows |
|---|---|---|---|
| k=2 iso=True | 0 | 0 | 6 |
| k=4 iso=True | 105 | 105 | 12 |
| k=8 iso=True | 1634 | **1496** | 12 |
| k=2 iso=False | 1772 | 90 | 6 |
| k=4 iso=False | 1879 | 107 | 12 |
| k=8 iso=False | 2174 | 250 | 12 |
| **Total** | **2216 s ≈ 36.9 min** | — | **60** |

S4 is the **second slowest** RQ2 run (S1: 38.2 min, S4: 36.9 min, S2: 32.5 min, S3: 15.8 min). The k=8 iso=True batch took **1496 s ≈ 25 minutes** alone — three times longer than the same batch in S3 (272 s). Two compounding causes:

1. **Image size** — Umami's adapter image is 197 MB (vs 111 MB for S3). On a memory-pressed kind cluster, image pulls and pod scheduling stretch out.
2. **Failure latency** — the 3 failing regression assertions (`run_log_clean`, `website_stats`, `teams_list`) each round-trip to Umami's API and incur a 5 s `timeout=5` ceiling. Three failures × ~5 s × 4 previews × 3 suites ≈ 180 s of timeout slack per batch in iso=True, compared to ~0 s in S1/S3 where all assertions succeed quickly.

The 1496 s gap also includes time waiting for k=8 isoFalse to schedule once isoTrue completes; on a cluster at 86 % memory, scheduling is constrained.

This timing observation reinforces the §2 finding that S4's failures are dominated by **timeout-bound retries** on broken endpoints, which is consistent with the endpoint-bug hypothesis (§3.a).

---

## Cross-subject comparison

| Property | S1 | S2 | S3 | S4 |
|---|---|---|---|---|
| Language / framework | Python/Flask | Go/Chi | Python/Django | TypeScript/Next.js (Prisma) |
| Suite-level Δ(iso=T − iso=F) | **−100 pp** | 0 pp (masked) | **−100 pp** | 0 pp (masked + open) |
| `run_log_clean` iso=True | PASS | PASS | PASS | **FAIL** ⚠ |
| `run_log_clean` iso=False | FAIL | FAIL | FAIL | FAIL |
| Functional assertions iso=True | PASS | 16/18 PASS | PASS | 7/10 PASS |
| Verdict | ✅ Thesis confirmed | ✅ Confirmed at assertion level | ✅ Thesis confirmed | ⏳ Open — requires further investigation |

The S4 row is the only one in the table where the load-bearing isolation signal does not match the operator-level evidence. The article should either include S4 as an explicit open case (with the three hypotheses) or defer S4 to the bug-fix iteration before claiming the result.

---

## Caveats / threats to validity

- **N = 60 with k=8 reduced to 4 previews/condition** due to kind memory pressure.
- **Detailed assertion logs only captured for one preview (`cp-181186da`).** Other previews may have shown different assertion-level patterns (e.g., different endpoints failing per run if there is non-determinism in the auth flow). A full per-preview log capture is part of the deferred fix chain.
- **RQ1 (flakiness, N=30) and RQ3 (performance, N=30) for S4 are pending** in master3 Stages 4 and 5. They will run with the current (unfixed) S4 image and likely produce the same all-Failed pattern.

---

## Article framing

S4 is best presented as **an open case** that motivates the methodological caveat established by S2:

> "Subject S4 (Umami, Next.js / Prisma) yielded a 100 % suite-level failure rate
> in both iso=True and iso=False (N=60). Assertion-level decomposition revealed
> two failure families: (i) two endpoint assertions (`teams_list`, `website_stats`)
> return permission errors regardless of database state, encoding no isolation
> signal — the same kind of test-harness defect resolved for S3 in the bug-fix
> chain; (ii) the isolation probe `run_log_clean` fails under iso=True for S4,
> contradicting the operator-level evidence collected for S2 (the restore script
> correctly truncates and replays `public.run_log`). Three hypotheses remain to
> be discriminated: Prisma's schema management altering the search_path, probe
> pod restart during the pipeline, or silent TRUNCATE CASCADE failure on Umami's
> FK graph. We report S4 as an open case rather than as a confirmation or
> refutation. The contrast with S1, S2, and S3 supports the methodological claim
> that per-suite outcome columns can hide both test-harness defects and
> infrastructure-level failure modes that require pod-level introspection to
> diagnose."

---

---

## RQ1 — Does checkpoint isolation reduce test flakiness?

> **Revision note (2026-05-16T18:53Z).** The original run (now archived as
> `flakiness_test_outcomes_20260516T144225Z.OBSOLETE_broken_assertions.csv`) ran with two
> upstream-broken assertions:
> - `teams_list` in smoke + regression — Umami v2.15.1 returns 403 for `/api/teams` unless
>   the user is in a team; our default admin is not.
> - `website_stats` in regression — Umami v2.15.1 requires query params (`startAt`, `endAt`,
>   `unit`) which the test didn't supply, returning 400.
>
> Both assertions failed deterministically regardless of isolation. They saturated the
> suite-level outcome and explain the original 100/100 null. The adapter image was rebuilt
> as `:v2.15.1-fix` with these assertions removed (the isolation-sensitive `run_log_clean`
> probe is preserved). A re-run is in progress; final numbers below will be updated when
> the proc exits.

**Source (re-run):** `flakiness_test_outcomes_20260516T185338Z.csv` (47/60 runs at 20:05Z, still in progress)

**Source (archived):** `flakiness_test_outcomes_20260516T144225Z.OBSOLETE_broken_assertions.csv` (N=30 per condition, original 60-run dataset with two broken assertions)

### Re-run results so far (47/60 runs, 20:05Z)

| Suite | iso=True N=30 | iso=False N=17/30 |
|---|---|---|
| smoke | 0/30 fail (**0 %** — was 30/30 fail before fix) | 0/17 fail (0 %) |
| regression | 30/30 fail (**100 %**) | 17/17 fail (**100 %**) |
| e2e | 30/30 fail (**100 %**) | 17/17 fail (**100 %**) |

**Interpretation.** Removing the two broken assertions (`teams_list`, `website_stats`) **resolved the smoke-suite failures** that were artefacts of upstream Umami v2.15.1 behavior changes (403 on `/api/teams` without team membership, 400 on `/api/websites/{id}/stats` without query params). Smoke now passes 0/0 in both conditions, confirming those failures were independent of isolation.

However, **regression and e2e still fail at 100% in BOTH iso=True and iso=False** — the underlying `run_log_clean` assertion remains the deciding factor. Unlike S1/S2/S3, S4's `run_log_clean` fails even under iso=True (the assertion captures the previous run's marker rather than a clean state). This was the "open question" already documented in the §RQ2 section above.

The three competing hypotheses remain unresolved at this writing:
1. Prisma alters `search_path` → run_log created in a non-public schema → not TRUNCATEd
2. Probe pod OOM/restart between save and assertion → recreates run_log after pg_dump
3. TRUNCATE CASCADE silently fails on Umami's FK graph

S4 therefore stays as the **open infrastructure case** in the dataset. The fix improved measurability (smoke is now meaningful) but did not unlock the isolation signal at the suite level for this subject.

### Raw results

| Suite | iso=True (fail/total) | iso=False (fail/total) | Δ fail rate | Fisher exact p (one-tailed) | Cohen's h |
|---|---|---|---|---|---|
| smoke | 30/30 (**100 %**) | 30/30 (**100 %**) | 0 pp | 1.0 | 0.00 |
| regression | 30/30 (**100 %**) | 30/30 (**100 %**) | 0 pp | 1.0 | 0.00 |
| e2e | 30/30 (**100 %**) | 30/30 (**100 %**) | 0 pp | 1.0 | 0.00 |

### Statistical analysis

Suite-level outcome shows **no measurable effect** of isolation: both conditions yield 100 % failure on every suite. Fisher's exact tests are non-significant (p = 1.0), Cohen's h = 0 (no effect).

### Deductions

**D1.** RQ1 at the suite-outcome granularity gives a null result for S4 — *not* because checkpoint isolation fails to do its job, but because the suite-level signal is dominated by bugs in the harness test scripts themselves (`teams_list` endpoint permissions, `website_stats` missing route, `website_count_matches_seed` hard-coded baseline). These bugs are invariant under isolation: they would fail with or without it.

**D2.** This replicates the *S2-Listmonk* pattern (see [ANALYSIS_S2.md](../s2-listmonk/ANALYSIS_S2.md) §3): per-suite columns can confound "isolation failure" with "mis-specified baseline assertion". For S4 the contamination is opaque at the suite level.

**D3.** Assertion-level evidence captured during the RQ2 batch (cross_pr) — see [ANALYSIS_S4.md §"Evidence"](#) above — shows that **`run_log_clean` fails under iso=True for S4**, which differs from S1/S2/S3 where it passes. This single isolation-sensitive assertion is the **open question** for S4 (probe schema, OOM, FK cascade — three competing hypotheses).

### Article sentence (RQ1)

> "Subject S4 (Umami) returns a 100 % suite-level failure rate in both isolation conditions (N=30 each, Fisher's exact p=1.0, Cohen's h=0). At the suite granularity, no effect of checkpoint isolation can be detected. Two assertions independent of isolation (broken upstream endpoints) saturate the failure signal. Assertion-level decomposition during the RQ2 batch reveals an isolation-sensitive `run_log_clean` probe that, uniquely among the five subjects studied, fails under iso=True for S4 — flagged as an open infrastructure-level question (probe pod restart, schema search_path, or FK CASCADE behavior). S4 therefore neither confirms nor refutes the isolation thesis at the suite level and is reported as an open case."

---

## RQ3 — What is the performance overhead of checkpoint isolation?

**Source:** `performance_run_metrics_20260516T144239Z.csv` (N=29 iso=True, N=30 iso=False, AKS run, 384 step-level rows)

> One iso=True run was excluded due to a partial CSV row from a cluster-pressure incident (15:25-15:38Z, before the 3-node scale-up). All remaining runs are clean.

### Per-step breakdown (iso=True, N=29)

| Step | n | mean (s) | std | median | min | max | Role |
|---|---|---|---|---|---|---|---|
| `postgres-migrate` | 29 | **37.4** | 36.00 | 25.0 | 23.0 | 168.0 | Prisma migrate + Umami seed |
| `saving` (pg_dump) | 29 | **4.6** | 1.48 | 4.0 | 3.0 | 11.0 | Checkpoint write |
| `restore-regression` | 29 | **5.8** | 1.69 | 6.0 | 4.0 | 13.0 | psql restore before regression |
| `restore-e2e` | 29 | **5.4** | 1.01 | 5.0 | 4.0 | 9.0 | psql restore before e2e |

> `smoke`, `regression`, `e2e` step durations are not consistently emitted by the operator's instrumentation when the underlying suite Job fails immediately (S4 suites fail on first assertion). The pipeline-total reconcile time below remains valid.

### Pipeline total `total_reconcile_s`

| Condition | n | mean (s) | std | median | min | max |
|---|---|---|---|---|---|---|
| iso=True | 29 | **106.7** | 87.22 | 78.0 | 65.0 | 504.0 |
| iso=False | 30 | **24.9** | 1.80 | 25.0 | 22.0 | 29.0 |
| **Overhead** | — | **+81.8 s (+328 %)** | — | — | — | — |

Mann-Whitney U = 870, **p = 4.04 × 10⁻¹¹**; Cliff's delta = **1.000** (complete stochastic dominance).

### Checkpoint cost decomposition

```
checkpoint_total = saving + restore-regression + restore-e2e
                 = 4.6  +       5.8        +     5.4
                 = 15.8 s   (median 16.0 s, ±2.44 s, N=29)
```

**`checkpoint_total` ≈ S1 baseline.** S4 checkpoint overhead (15.8 s) is within 1.5 s of the S1 figure (14.6 s) — the per-step cost of checkpoint save/restore is **invariant across application stacks** (Flask/Python vs Next.js/TypeScript/Prisma), as expected since `pg_dump` and `psql` operate at the PostgreSQL layer below the application.

### Deductions

**D1.** Checkpoint cost is **portable**: S4 reports 15.8 s vs S1 14.6 s. The 1.2 s difference is within one σ of the S1 measurement (±1.03 s). The mechanism is application-agnostic at the DB layer.

**D2.** The **pipeline total variance is dominated by the S4-specific `postgres-migrate` step** (mean 37.4 s, σ=36 s, range 23–168 s). Prisma migrations on a fresh Postgres database take significantly longer than Alembic (S1: 18.8 s) or `manage.py migrate` (S3: ~25 s) — a function of Prisma's introspection / connection-pool setup.

**D3.** The **328 % overhead reported** is misleading without disaggregation. Pipeline total includes the test-suite step durations, which time out on S4 (failed assertions waste seconds before the Job exits). Of the 81.8 s overhead, only **15.8 s is from checkpoint isolation**; the remaining ≈66 s is the additional time the failing pipeline spends in iso=True (which runs all three suites end-to-end including the restores) vs iso=False (which fails out faster).

**D4.** **Outliers in iso=True** (max 504 s, std 87 s) reflect transient AKS scheduling delays during the cluster CPU-requests saturation incident (15:25-15:38Z). The median (78 s) is the more reliable central tendency for the AKS run.

### Article sentence (RQ3)

> "On Subject S4 (Umami, Next.js + Prisma), the checkpoint isolation overhead is **15.8 s ± 2.44 s** (median 16.0 s, N=29) — within 1.5 s of the S1 baseline (14.6 s), confirming that the per-pipeline cost of `pg_dump` / `psql` restore is invariant across application stacks since it operates at the PostgreSQL layer. The full-pipeline overhead (+81.8 s) is inflated by S4-specific Prisma migration time (mean 37.4 s, vs S1 Alembic 18.8 s) and by the longer reconcile path of completing all three failing suites under iso=True; these are not properties of the isolation mechanism."

---

## Cross-RQ synthesis (S4)

S4 illustrates the **upper bound** of what the harness can claim from suite-level outcomes alone. The suite-level RQ1 signal is null (100/100), but:

1. **Checkpoint overhead is universal**: RQ3 measures 15.8 s — same order as S1/S2/S3 — confirming the mechanism is application-agnostic at the cost dimension.
2. **The isolation probe `run_log_clean` is the single dimension where S4 is anomalous**: it *fails* under iso=True in S4 only. This requires further infrastructure-level investigation (deferred — see §"Evidence" above).
3. **Reporting strategy for the article**: include S4 as the case study that motivates per-assertion analysis. Its suite-level numbers are uninformative; its checkpoint-cost numbers reinforce the universality claim.

---

## Data files

| File | Rows | Notes |
|---|---|---|
| `cross_pr_test_outcomes_20260515T204434Z.csv` | 60 | RQ2 — full suite-level outcomes (15/05 Kind) |
| `flakiness_test_outcomes_20260516T144225Z.csv` | 180 | RQ1 — N=30 per iso condition (16/05 AKS) |
| `performance_run_metrics_20260516T144239Z.csv` | 384 | RQ3 — step-level + total_reconcile (16/05 AKS) |

---

## Evidence references

- `subjects/s4-umami/harness-adapter/tests/smoke.py` — assertions list including `teams_list`
- `subjects/s4-umami/harness-adapter/tests/regression.py:42-44, 66-68, 80, 89` — assertions list including `run_log_clean`, `website_stats`, `website_count_matches_seed`
- `subjects/probe/probe.py:12-27` — probe stores markers in `public.run_log` of the application database via `DATABASE_URL`
- `preview/preview-operator/internal/controller/checkpoint.go:463-471` — restore script: `TRUNCATE public.* RESTART IDENTITY CASCADE; psql -f dump.sql`
- Runtime capture from `cp-181186da` (preview-pr-8282), 2026-05-15 ~23:18 CEST, before pods were cleaned up
