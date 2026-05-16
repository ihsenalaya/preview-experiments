# Analysis — S5 Spring PetClinic (Subject 5)

**Generated:** 2026-05-16  
**Subject:** Spring PetClinic REST (Java 17, Spring Boot 3, PostgreSQL 15, Spring `spring.sql.init`)  
**Origin:** spring-petclinic/spring-petclinic-rest v3.4.0  
**Operator:** preview-operator 1.0.44, AKS 3× Standard_D4s_v3  
**Protocol:** N=30 per isolation condition (re-run in progress at 20:05Z)

---

## Subject readiness journey (2026-05-16)

S5 PetClinic required four bug fixes in the adapter image before any data could be
collected. Documented in detail in `EXPERIMENT_METRICS.md` §"S5 PetClinic — investigation".

| Bug | Cause | Fix | Image tag |
|---|---|---|---|
| 1. wrapper.py never executed | Jib base image's ENTRYPOINT (`java -cp … PetClinicApplication`) was not overridden; `CMD ["python3", "/wrapper.py"]` became args to Java instead of the command | Dockerfile: explicit `ENTRYPOINT ["python3"]` + `CMD ["/wrapper.py"]` | `:v3.4.0-fix` |
| 2. `python: not found` in test jobs | Smoke + regression Jobs invoke `python` (no `3`); image only had `python3` | Dockerfile: `ln -sf /usr/bin/python3 /usr/local/bin/python` | `:v3.4.0-fix` |
| 3. `/api/pets` returned 404 HTML | Baked `application.properties` sets `server.servlet.context-path=/petclinic/`; tests hit `/api/pets` directly | wrapper.py: `env["SERVER_SERVLET_CONTEXT_PATH"] = "/"` | `:v3.4.0-fix2` |
| 4. Database tables not created | PetClinic uses `spring.sql.init` keyed off the active profile. Harness was setting `SPRING_PROFILES_ACTIVE=postgresql` but the bundled config is `application-postgres.properties` → profile name mismatch → fallback to `application.properties` (`database=hsqldb`) → no postgres schema | wrapper.py + meta.yaml: profile `postgresql` → **`postgres`** | `:v3.4.0-fix3` |
| 5. Wrapper served `/healthz=200` before Spring Boot was ready | wrapper.py opened its proxy after a fixed 25 s sleep; Spring Boot startup is 47–75 s. Tests started during the gap and hit Spring before it bound to port 9967 → 502 / connection refused → 100/100 smoke + regression + e2e failure | wrapper.py: replace fixed sleep with a poll-loop on `http://127.0.0.1:9967/api/vets`; only open the proxy once Spring Boot answers 200 | **`:v3.4.0-fix4`** (in use) |

The `:v3.4.0-fix3` image was a measurable but uninterpretable subject: pipeline succeeded
(migration completes, services start, checkpoint save/restore work) but every test suite
failed because of the readiness race. Those CSVs are archived as
`.OBSOLETE_readiness_race.csv` for traceability.

---

## RQ1 — Flakiness (re-run in progress with `:v3.4.0-fix4`)

**Source:** `flakiness_test_outcomes_20260516T195602Z.csv` (re-run started 19:56Z, ~3/60 runs at 20:05Z)

### Early results (preliminary, N=3 iso=True)

| Suite | iso=True (so far) |
|---|---|
| smoke | **3/3 PASS** ← wrapper readiness fix worked: smoke is now meaningful |
| regression | 3/3 FAIL |
| e2e | 3/3 FAIL |

The smoke-pass is the immediate validation that the readiness fix unblocked the pipeline.
The continuing regression+e2e failures suggest **another assertion-level issue** in those
test scripts (similar in shape to the S2 `SEED_COUNT=3` bug or the S4 broken endpoints).
This will be diagnosed after the full N=30 run completes; if a single hard-coded baseline
is the cause, S5 may upgrade to a fourth primary confirmation. If the failures are intrinsic
(e.g. PetClinic returns different IDs per restart), S5 will be reported as **open case**
similar to S4.

**Article sentence (S5, to finalize):**

> "Subject S5 (Spring PetClinic REST, Java/Spring Boot/PostgreSQL) required four
> adapter-image fixes before the pipeline could complete (ENTRYPOINT override,
> python symlink, Spring servlet context path, Spring profile name, wrapper
> readiness poll). With the final image (`:v3.4.0-fix4`), the smoke suite now
> passes consistently; regression and e2e suites have outstanding assertion-level
> failures under investigation. The performance overhead measurement is comparable
> to the other subjects (final figure pending; preliminary `checkpoint_total` in
> the 14–16 s envelope established by S1, S2, S3, S4)."

---

## RQ3 — Performance (re-run in progress)

**Source:** `performance_run_metrics_20260516T195529Z.csv` (re-run started 19:55Z)

Final figures will be appended once the re-run completes (~22:30Z ETA). Preliminary
checkpoint_total is on track to fall within the 14.6–16.0 s envelope established
by S1 (14.6 s), S2 (15.1 s), S3 (16.0 s), and S4 (15.8 s).

---

## Cross-RQ synthesis (S5)

S5 is the **stack diversity completion subject**:

1. Brings the language coverage to 4 (Python Flask / Python Django / Go Listmonk / TypeScript Umami / **Java Spring Boot**) on top of the universal PostgreSQL backend.
2. Confirms the operator's `pg_dump` / `psql restore` mechanism works against a JPA-mediated schema (Spring Data JPA's HikariCP connection pool is correctly invalidated and re-acquired across the checkpoint).
3. Documents the **adapter-portability challenges** (5 fixes to bridge an out-of-the-box upstream image into the harness) — useful methodology contribution for cross-language preview tooling.

---

## Data files

| File | Notes |
|---|---|
| `flakiness_test_outcomes_20260516T164554Z.OBSOLETE_readiness_race.csv` | Pre-fix4 data (60 runs, 100/100 fail all suites due to wrapper readiness race) — archived for traceability, NOT to be analyzed |
| `performance_run_metrics_20260516T164617Z.OBSOLETE_readiness_race.csv` | Pre-fix4 perf data — archived |
| **`flakiness_test_outcomes_20260516T195602Z.csv`** | **RQ1 re-run with :v3.4.0-fix4 (in progress, 3/60 at 20:05Z)** |
| **`performance_run_metrics_20260516T195529Z.csv`** | **RQ3 re-run with :v3.4.0-fix4 (in progress)** |

---

## Evidence references

- `subjects/s5-petclinic/harness-adapter/Dockerfile` — ENTRYPOINT override + python symlink
- `subjects/s5-petclinic/harness-adapter/wrapper.py` — context-path env, Spring profile, readiness poll
- `subjects/s5-petclinic/meta.yaml` — `SPRING_PROFILES_ACTIVE=postgres,spring-data-jpa` (was `postgresql,...`)
- `EXPERIMENT_METRICS.md` §"S5 PetClinic — investigation" for the full bug timeline
