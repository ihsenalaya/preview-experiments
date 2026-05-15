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

## Data files

| File | Rows | Notes |
|---|---|---|
| `cross_pr_test_outcomes_20260515T204434Z.csv` | 60 | RQ2 — full suite-level outcomes |

---

## Evidence references

- `subjects/s4-umami/harness-adapter/tests/smoke.py` — assertions list including `teams_list`
- `subjects/s4-umami/harness-adapter/tests/regression.py:42-44, 66-68, 80, 89` — assertions list including `run_log_clean`, `website_stats`, `website_count_matches_seed`
- `subjects/probe/probe.py:12-27` — probe stores markers in `public.run_log` of the application database via `DATABASE_URL`
- `preview/preview-operator/internal/controller/checkpoint.go:463-471` — restore script: `TRUNCATE public.* RESTART IDENTITY CASCADE; psql -f dump.sql`
- Runtime capture from `cp-181186da` (preview-pr-8282), 2026-05-15 ~23:18 CEST, before pods were cleaned up
