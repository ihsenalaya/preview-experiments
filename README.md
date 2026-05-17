# Preview-Experiments: Experimental Harness for Checkpoint-Based Database Isolation in Kubernetes Preview Environments

## Title

This repository contains the experimental harness used to evaluate checkpoint-based
database isolation in Kubernetes preview environments. It is a reproducibility-oriented
artefact for an empirical software engineering paper targeting a Q1 IEEE/Springer venue.

## Problem Statement

Preview environments execute migrations, seed data, and multiple test suites inside
ephemeral Kubernetes namespaces. Without explicit database reset points, state
created by one suite can leak into later suites, increasing failure variability and
complicating interpretation of test outcomes. This repository studies whether
checkpoint-based restoration mitigates such state pollution, what runtime overhead it
introduces, and how robust the operator remains under concurrency, mutation-based
fault seeding, and controller restarts.

### Naming conventions used in this tree

**Repositories and images**

| Name | What it refers to |
|---|---|
| `preview-experiments` | this repository (the experimental harness) |
| `preview-operator` | the Kubernetes operator repository (separate repo, not modified by this study) |
| `idp-preview` | the container image name for the S1 reference subject (`ghcr.io/ihsenalaya/idp-preview`) |
| `harness-probe` | shared sidecar image injected into S2–S5 previews (`ghcr.io/ihsenalaya/harness-probe`) |
| `sN-<name>-adapter` | adapter image for subject N (e.g. `s2-listmonk-adapter`) |

**Directories**

| Path | What it contains |
|---|---|
| `testapp/` | source code of the S1 reference subject (Flask Catalog) |
| `subjects/s1-flask-catalog/` | metadata only; S1 source lives in `testapp/` |
| `subjects/sN-*/harness-adapter/` | Dockerfile, wrapper.py, and tests for subjects S2–S5 |
| `subjects/probe/` | source of the shared `harness-probe` sidecar |
| `exp_*/` | one directory per experiment (RQ1–RQ5), each with a `run.py` driver |
| `harness/` | shared Python library used by all experiment drivers |
| `results/` | timestamped CSV outputs written by experiment drivers |
| `logs/` | experiment run logs (gitignored) |
| `analysis/` | statistical analysis scripts and generated figures |
| `setup/` | cluster bootstrap and teardown scripts |
| `scripts/` | utility scripts (anonymization, etc.) |

**Kubernetes and operator concepts**

| Term | What it refers to |
|---|---|
| `Preview` | custom resource (`platform.company.io/v1alpha1`) that the operator reconciles |
| `status.tests.phase` | field used by the harness to detect test completion (not `status.phase`) |
| `preview-operator-system` | Kubernetes namespace where the operator pod runs |
| `preview-pr-<N>` | namespace created by the operator for each Preview CR |
| `run_log` | PostgreSQL table managed by the probe sidecar, used as an isolation probe |

**Configuration and data files**

| File | What it contains |
|---|---|
| `config.yaml` | single source of truth for all experiment parameters; overridable via `EXP_` env vars |
| `subjects/sN-*/meta.yaml` | subject metadata: upstream origin, migration command, service layout, seed count |
| `subjects/CONTRACT.md` | integration contract defining what a conformant subject must provide |
| `exp_bug_detection/fault-catalog.yaml` | generated catalog of mutant diffs used by RQ4 |
| `setup/versions.lock.yaml` | pinned versions for cluster, images, and tools |

**Terms to avoid in paper text**

- `preview-env` — not a directory or repository name in this tree.
- `harness-adapter` used alone — always qualify with the subject ID (e.g. "the S2 harness adapter").

---

## Research Questions

### RQ1 — Flakiness reduction with checkpoint-based database isolation

- Objective: evaluate whether checkpoint save/restore reduces suite-level failure variability relative to a no-isolation baseline.
- Independent variables: `isolation_enabled ∈ {true, false}`; subject ID.
- Metrics: `failure_rate`, `suite_pass_rate`; step-level timings.
- Runs: 30 per isolation condition per subject (`config.yaml`).
- Output: `results/flakiness_test_outcomes_<timestamp>.csv`.
- Statistical test: Mann-Whitney U, Fisher's exact test, Vargha-Delaney effect size.

### RQ2 — Cross-preview state pollution under concurrency

- Objective: evaluate whether higher concurrency amplifies failure rates when isolation is disabled.
- Independent variables: `concurrency_K ∈ {2, 4, 8}`; `isolation_enabled ∈ {true, false}`; subject ID.
- Metrics: `cross_preview_failure_rate`, `suite_pass_rate`.
- Runs: one concurrent batch per `K × isolation × subject` per script invocation.
- Output: `results/cross_pr_test_outcomes_<timestamp>.csv`.
- Statistical test: Mann-Whitney U and Vargha-Delaney effect size per concurrency level.

### RQ3 — Performance overhead of checkpoint/restore isolation

- Objective: quantify the time cost of checkpoint save/restore relative to overall pipeline duration.
- Independent variables: `isolation_enabled ∈ {true, false}`; subject ID.
- Metrics: `checkpoint_save_time_sec`, `checkpoint_restore_time_sec`, `pipeline_duration_sec`, `overhead_pct`.
- Runs: 30 per isolation condition per subject.
- Output: `results/performance_run_metrics_<timestamp>.csv`.
- Statistical test: descriptive statistics; inferential comparison if added before submission.

### RQ4 — Mutation-based bug detection with seed conditions

- Objective: evaluate whether richer seed data improves mutation detection, while separating data-volume effects from semantic-diversity effects.
- Independent variables: seed condition; mutant ID; subject ID.
- Metrics: `killed_mutants`, `survived_mutants`, `mutation_score`, `detection_rate_by_seed_condition`.
- Runs: one per `mutant × seed condition × subject`.
- Output: `results/bug_detection_test_outcomes_<timestamp>.csv`.
- Statistical test: McNemar's test on paired mutant-detection outcomes.

Seed conditions (submission-facing names):

| Internal name | Paper name | Description |
|---|---|---|
| `static` | `static` | Static seed data only (baseline) |
| `llm_fixed` | `llm_matched_volume` | LLM-generated, temperature=0, same row count as static |
| `llm_free` | `llm_free_volume` | LLM-generated, temperature=0.7, unconstrained volume |

This design separates semantic diversity from volume effects: `static` vs `llm_fixed`
isolates quality at equal volume; `llm_fixed` vs `llm_free` isolates diversity at
equal model temperature.

### RQ5 — Operator idempotence and convergence after restart

- Objective: evaluate whether the operator converges to a consistent end state after controller restarts during pipeline execution.
- Independent variables: restart step; subject ID.
- Metrics: `convergence_time_sec`, `duplicate_job_count`, `lost_status_count`, `final_state_consistent`.
- Runs: 3 restarts per pipeline step per subject.
- Output: `results/idempotence_run_metrics_<timestamp>.csv`.
- Statistical test: descriptive analysis of convergence time and divergence counts.

---

## Subject Applications

The harness evaluates five real open-source applications. Each subject is integrated
without modifying its upstream source code. Integration consists of three added
artefacts only: a `Dockerfile` layered on top of the upstream image, a `wrapper.py`
proxy entrypoint, and a harness-specific test suite. A shared `probe/` sidecar
manages the `run_log` isolation table and is injected into every S2–S5 preview.

### Subject overview

| ID | Application | Upstream repository | License | Pinned version |
|---|---|---|---|---|
| `s1-flask-catalog` | Flask Product Catalog | internal (custom-built reference) | internal | `exp-20260514` |
| `s2-listmonk` | Listmonk Newsletter Manager | [knadh/listmonk](https://github.com/knadh/listmonk) | AGPL-3.0 | `v2.5.1` |
| `s3-healthchecks` | Healthchecks Cron Monitor | [healthchecks/healthchecks](https://github.com/healthchecks/healthchecks) | BSD-3-Clause | `v3.6` |
| `s4-umami` | Umami Web Analytics | [umami-software/umami](https://github.com/umami-software/umami) | MIT | `v2.15.1` |
| `s5-petclinic` | Spring PetClinic REST | [spring-petclinic/spring-petclinic-rest](https://github.com/spring-petclinic/spring-petclinic-rest) | Apache-2.0 | `3.4.0` |

### Detailed subject table

| Attribute | S1 Flask Catalog | S2 Listmonk | S3 Healthchecks | S4 Umami | S5 PetClinic |
|---|---|---|---|---|---|
| **Language** | Python 3 | Go | Python 3 | TypeScript | Java |
| **Framework** | Flask 3 | Chi router | Django 5 | Next.js 14 | Spring Boot 3 |
| **Database** | PostgreSQL | PostgreSQL | PostgreSQL | PostgreSQL | PostgreSQL |
| **Migration mechanism** | Alembic | `listmonk --install` | `manage.py migrate` | Prisma migrate | Flyway (auto on startup) |
| **Seed entity** | products (5 rows) | mailing lists (3 rows) | cron checks (2 rows) | websites (1 row) | pets (13 rows, Flyway) |
| **Upstream image used** | custom (`idp-preview`) | `listmonk/listmonk:v2.5.1` | `healthchecks/healthchecks:v3.6` | `ghcr.io/umami-software/umami:postgresql-v2.15.1` | `springcommunity/spring-petclinic-rest:3.4.0` |
| **Adapter image** | `ghcr.io/ihsenalaya/idp-preview` | `ghcr.io/ihsenalaya/s2-listmonk-adapter:v2.5.1` | `ghcr.io/ihsenalaya/s3-healthchecks-adapter:v3.6` | `ghcr.io/ihsenalaya/s4-umami-adapter:v2.15.1` | `ghcr.io/ihsenalaya/s5-petclinic-adapter:v3.4.0` |
| **Test origin** | written for harness | added by harness | added by harness | added by harness | added by harness |
| **Test scope** | REST CRUD + run_log probe | REST API (lists, subscribers) | REST API v3 (checks, pings) | REST API (auth, pageviews) | REST API (pets, vets, owners) |
| **Added wrapper files** | — (source is the image) | `wrapper.py`, `Dockerfile`, `tests/`, `requirements.txt` | `wrapper.py`, `Dockerfile`, `tests/` | `wrapper.py`, `Dockerfile`, `tests/`, `requirements.txt` | `wrapper.py`, `Dockerfile`, `tests/`, `requirements.txt` |
| **Upstream source modified** | N/A | No | No | No | No |
| **Probe sidecar** | embedded in app | shared `harness-probe` | shared `harness-probe` | shared `harness-probe` | shared `harness-probe` |
| **RQ4 mutation target** | `testapp/app.py` | — | — | — | — |

**Test origin note:** the upstream applications do not ship REST integration test
suites compatible with the harness pipeline. For S2–S5, all test scripts
(`smoke.py`, `regression.py`, `e2e.py`) were written for this study, targeting each
application's public REST API with scenarios exercising the seeded entities. No
upstream unit or integration tests were modified or reused.

### Adapter architecture

Each adapter image is built on top of the upstream official Docker image without
modifying the application binary:

```
FROM <upstream-official-image>     # e.g. springcommunity/spring-petclinic-rest:3.4.0
USER root
RUN <install python3 + pip>        # alpine: apk; debian: apt-get
COPY tests/     /app/tests/
COPY wrapper.py /wrapper.py
EXPOSE <port>
CMD ["python3", "/wrapper.py"]
```

`wrapper.py` starts the upstream process, waits for it to become ready, then serves:

- `GET /healthz` → `200 ok` (liveness probe for the operator)
- All other paths → transparent HTTP reverse proxy to the upstream port

The upstream process start command varies by subject:

| Subject | Start command |
|---|---|
| S2 Listmonk | `/listmonk --config=/tmp/listmonk-config.toml` |
| S3 Healthchecks | `uwsgi --http-socket 0.0.0.0:8001 --module hc.wsgi:application` |
| S4 Umami | `node server.js` (Next.js production server) |
| S5 PetClinic | `java -cp @/app/jib-classpath-file org.springframework.samples.petclinic.PetClinicApplication` (Jib exploded JAR) |

### Probe sidecar

All S2–S5 previews receive a shared probe container (`ghcr.io/ihsenalaya/harness-probe:latest`)
running on port 9090. It manages the `run_log` table used by isolation probes and
exposes `/probe` endpoints consumed by test suites.

### S1 reference subject

S1 is a custom-built Flask/PostgreSQL REST API written for this study. It is the
sole mutation target for RQ4. Its source lives in `testapp/` and is not colocated
under `subjects/s1-flask-catalog/` for historical reasons.

- Source: `testapp/`
- Metadata: `subjects/s1-flask-catalog/meta.yaml`
- Tests: `testapp/tests/smoke.py`, `testapp/tests/regression.py`, `testapp/tests/e2e.py`
- Mutation targets: `testapp/app.py` (RQ4 only)

---

## Test Pipeline

For each preview run the operator executes the following sequential steps:

```
migration → saving → smoke → restore-regression → regression → restore-e2e → e2e
```

- `migration`: runs database schema + seed data commands from `meta.yaml`.
- `saving`: `pg_dump --data-only` → stored in a ConfigMap as a checkpoint.
- `restore-regression` / `restore-e2e`: `psql < checkpoint` before each subsequent suite.
- With `isolation_enabled: false` the saving and restore steps are skipped.

The operator exposes completion status through `status.tests.phase` on the Preview CR.
Pipeline completion is detected by the harness via `wait_until_tests_done()`.

---

## Repository Structure

```text
experimentation/
├── config.yaml                    # single source of truth for all parameters
├── run_demo.py                    # smoke-test a single subject end-to-end
├── run-all-experiments.sh         # sequential batch entry point (local)
├── analysis/
│   ├── 01_flakiness.py
│   ├── 02_cross_pr.py
│   ├── 03_performance.py
│   ├── 04_bug_detection.py
│   ├── 05_idempotence.py
│   └── requirements.txt
├── exp_bug_detection/
│   ├── fault-catalog.yaml         # generated mutant diffs
│   ├── mutations/
│   │   ├── apply-mutant.sh        # applies catalog diff via patch(1); no mutmut cache
│   │   └── generate-mutants.sh
│   └── run.py
├── exp_cross_pr/run.py
├── exp_flakiness/run.py
├── exp_idempotence/run.py
├── exp_performance/run.py
├── harness/
│   ├── config.py
│   ├── metrics_collector.py
│   ├── preview_factory.py         # create/wait/delete Preview CRs via kubectl
│   ├── results_writer.py          # timestamped CSV writer
│   └── schemas/
├── logs/                          # experiment run logs (gitignored)
├── results/                       # timestamped CSV outputs
├── scripts/
│   └── anonymize.sh
├── setup/
│   ├── bootstrap-cluster.sh
│   ├── kind-config.yaml
│   ├── teardown.sh
│   └── versions.lock.yaml
├── subjects/
│   ├── CONTRACT.md
│   ├── probe/                     # shared sidecar for S2–S5
│   ├── s1-flask-catalog/meta.yaml
│   ├── s2-listmonk/
│   │   ├── meta.yaml
│   │   └── harness-adapter/       # Dockerfile, wrapper.py, tests/
│   ├── s3-healthchecks/
│   │   ├── meta.yaml
│   │   └── harness-adapter/
│   ├── s4-umami/
│   │   ├── meta.yaml
│   │   └── harness-adapter/
│   └── s5-petclinic/
│       ├── meta.yaml
│       └── harness-adapter/
└── testapp/                       # S1 source code (Flask Catalog)
    ├── app.py
    ├── migrations/
    ├── requirements.txt
    ├── seeds/
    └── tests/
```

---

## Infrastructure

### Local execution (WSL2)

The harness Python scripts run locally and orchestrate Preview CRs on AKS via
`kubectl`. This approach is simple but stops if the machine sleeps or restarts.

### Remote execution on Azure VM (recommended)

A dedicated Azure VM (`exp-runner`, `Standard_B2s`, `eastus`) is provisioned in the
`kubebuilder` resource group for persistent experiment execution. All five experiment
scripts run in the background via `nohup` and are independent of the local machine.

```
Resource group : kubebuilder
VM name        : exp-runner
Size           : Standard_B2s (2 vCPU, 4 GB RAM)
OS             : Ubuntu 22.04 LTS
Location       : eastus (same region as AKS cluster)
SSH key        : ~/.ssh/exp_runner
```

**Connect to the VM:**

```bash
ssh -i ~/.ssh/exp_runner ihsen@172.190.167.113
```

**Start all experiments on the VM:**

```bash
ssh -i ~/.ssh/exp_runner ihsen@172.190.167.113 "bash ~/run-all.sh"
```

**Monitor experiment progress:**

```bash
ssh -i ~/.ssh/exp_runner ihsen@172.190.167.113 "tail -f ~/experiments/logs/rq1.log"
ssh -i ~/.ssh/exp_runner ihsen@172.190.167.113 "kubectl get previews -A"
```

**Retrieve results:**

```bash
scp -i ~/.ssh/exp_runner -r ihsen@172.190.167.113:~/experiments/results/ ./results/
```

The VM has Docker installed and can run RQ4 `docker build` + `docker push` without
the credential-helper limitation that affects WSL2 background processes.

### AKS cluster

```
Cluster : preview-cluster
RG      : kubebuilder
Region  : eastus
Operator namespace : preview-operator-system
```

---

## Configuration

`config.yaml` is the single source of truth for all experiment parameters.
All values can be overridden with `EXP_`-prefixed environment variables.

Current active configuration:

```yaml
subjects:
  enabled:
    - s1-flask-catalog
    - s2-listmonk
    - s3-healthchecks
    - s4-umami
    - s5-petclinic

experiments:
  flakiness:    { n_runs: 30, isolation_values: [true, false], timeout_minutes: 20 }
  cross_pr:     { k_values: [2, 4, 8], isolation_values: [true, false], timeout_minutes: 40 }
  performance:  { n_runs: 30, timeout_minutes: 25 }
  bug_detection:
    n_mutations_max: 50
    isolation_values: [static, llm_fixed, llm_free]
    llm_fixed_temperature: 0.0
    llm_free_temperature:  0.7
    timeout_minutes: 60
  idempotence:
    kill_steps: [saving, smoke, restore-regression, regression, restore-e2e, e2e]
    n_restarts_per_step: 3
    timeout_minutes: 30
```

PR number ranges (to avoid collisions between parallel experiments):

| Experiment | PR range |
|---|---|
| RQ1 Flakiness | 9000–9899 |
| RQ3 Performance | 9000–9899 |
| RQ2 Cross-PR | 8000–8899 |
| RQ4 Bug Detection | 7000–7899 |
| RQ5 Idempotence | 6000–6899 |

---

## How to Run Experiments

### Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Docker | ≥ 24 | Build and push adapter images |
| kubectl | ≥ 1.29 | Cluster interaction |
| helm | ≥ 3.14 | Operator install |
| Python | ≥ 3.10 | Harness + analysis |
| yq | ≥ 4 | Parse config.yaml in shell scripts |
| mutmut | 2.4.4 | Mutant generation (RQ4 only) |
| patch | any | Apply mutant diffs (RQ4 only) |

### Build and push adapter images (S2–S5)

Each adapter image is built from its `harness-adapter/` directory:

```bash
# S2 — Listmonk
docker build -t ghcr.io/ihsenalaya/s2-listmonk-adapter:v2.5.1 \
  subjects/s2-listmonk/harness-adapter/
docker push ghcr.io/ihsenalaya/s2-listmonk-adapter:v2.5.1

# S3 — Healthchecks
docker build -t ghcr.io/ihsenalaya/s3-healthchecks-adapter:v3.6 \
  subjects/s3-healthchecks/harness-adapter/
docker push ghcr.io/ihsenalaya/s3-healthchecks-adapter:v3.6

# S4 — Umami
docker build -t ghcr.io/ihsenalaya/s4-umami-adapter:v2.15.1 \
  subjects/s4-umami/harness-adapter/
docker push ghcr.io/ihsenalaya/s4-umami-adapter:v2.15.1

# S5 — PetClinic
docker build -t ghcr.io/ihsenalaya/s5-petclinic-adapter:v3.4.0 \
  subjects/s5-petclinic/harness-adapter/
docker push ghcr.io/ihsenalaya/s5-petclinic-adapter:v3.4.0
```

### Run all experiments (on Azure VM — recommended)

```bash
ssh -i ~/.ssh/exp_runner ihsen@172.190.167.113
cd ~/experiments && git pull
bash ~/run-all.sh
```

### Run all experiments (locally)

```bash
nohup python3 exp_flakiness/run.py    >> logs/rq1.log 2>&1 &
nohup python3 exp_cross_pr/run.py     >> logs/rq2.log 2>&1 &
nohup python3 exp_performance/run.py  >> logs/rq3.log 2>&1 &
nohup python3 exp_bug_detection/run.py >> logs/rq4.log 2>&1 &
nohup python3 exp_idempotence/run.py  >> logs/rq5.log 2>&1 &
```

Or using the batch entry point:

```bash
bash run-all-experiments.sh
```

### Run a single subject demo

```bash
python3 run_demo.py                          # S1 only
SUBJECT=s2-listmonk python3 run_demo.py     # specific subject
```

### Generate mutants for RQ4

```bash
bash exp_bug_detection/mutations/generate-mutants.sh
# Produces: exp_bug_detection/fault-catalog.yaml
```

Mutants are applied at runtime by `apply-mutant.sh`, which extracts the diff from
`fault-catalog.yaml` and applies it with `patch(1)`. This avoids the `mutmut` cache
invalidation that occurs when the source file is restored via `git checkout`.

### Parameter overrides

```bash
EXP_EXPERIMENTS_FLAKINESS_N_RUNS=5 python3 exp_flakiness/run.py
EXP_EXPERIMENTS_PERFORMANCE_N_RUNS=5 python3 exp_performance/run.py
```

---

## Expected Outputs

| File pattern | Produced by |
|---|---|
| `results/flakiness_test_outcomes_<ts>.csv` | `exp_flakiness/run.py` |
| `results/cross_pr_test_outcomes_<ts>.csv` | `exp_cross_pr/run.py` |
| `results/performance_run_metrics_<ts>.csv` | `exp_performance/run.py` |
| `results/bug_detection_test_outcomes_<ts>.csv` | `exp_bug_detection/run.py` |
| `results/idempotence_run_metrics_<ts>.csv` | `exp_idempotence/run.py` |
| `results/analysis/figures/*.pdf` | `analysis/0*.py` |
| `anonymized-submission.tar.gz` | `scripts/anonymize.sh` |

CSV schemas are in `harness/schemas/`.

---

## Metrics Collected

| Metric | Status | Source |
|---|---|---|
| `failure_rate` | available | `*_test_outcomes_*.csv` suite outcomes |
| `suite_pass_rate` | available | suite-level outcomes |
| `checkpoint_save_time_sec` | available | `run_metrics.step == saving` |
| `checkpoint_restore_time_sec` | available | `run_metrics.step ∈ {restore-regression, restore-e2e}` |
| `pipeline_duration_sec` | available | `total_reconcile_s` in performance outputs |
| `overhead_pct` | available | performance outputs |
| `concurrency_K` | available | encoded in RQ2 run identifiers |
| `killed_mutants` / `survived_mutants` | derivable | mutant run outcomes |
| `mutation_score` | derivable | computed during analysis |
| `detection_rate_by_seed_condition` | derivable | computed during analysis |
| `convergence_time_sec` | available | `idempotence` step durations |
| `flaky_test_rate` | planned | requires per-test outcome capture |
| `state_contamination_rate` | partial | proxied by restore-sensitive failures |
| `queueing_delay_sec` | planned | not emitted |
| `duplicate_job_count` | planned | not emitted |
| `cpu_avg` / `memory_avg` | planned | helpers exist; not persisted automatically |

---

## Statistical Analysis

```bash
python3 analysis/01_flakiness.py
python3 analysis/02_cross_pr.py
python3 analysis/03_performance.py
python3 analysis/04_bug_detection.py
python3 analysis/05_idempotence.py
```

Planned tests:

- RQ1: Mann-Whitney U, Fisher's exact test, Vargha-Delaney A
- RQ2: Mann-Whitney U and Vargha-Delaney A per concurrency level
- RQ3: descriptive statistics for step durations and overhead
- RQ4: McNemar's test on paired mutant outcomes across seed conditions
- RQ5: descriptive statistics for convergence times and divergence counts

---

## Reproducibility

Archive the following for every reported run:

- `config.yaml` — experiment parameters
- `setup/versions.lock.yaml` — cluster and container versions
- `analysis/requirements.txt` — Python dependencies
- `results/*.csv` — raw outputs
- `results/analysis/figures/*.pdf` — generated figures
- `exp_bug_detection/fault-catalog.yaml` — mutant catalog (RQ4)
- `CITATION.cff`

---

## Artifact (TSE-ready reproducibility infrastructure)

This repository ships a complete artifact for reproducing every number/table/figure
in the paper from frozen CSVs, without cluster access. Pipeline:

```
results/  ──▶  scripts/consolidate_results.py  ──▶  results/frozen/
                                                  │   ├── MANIFEST.json (SHA-256)
                                                  │   └── excluded_datasets.csv
                                                  ▼
                  analysis/build_all.py  ──▶  results/analysis/
                                              ├── tables/*.{md,tex}
                                              ├── figures/*.{pdf,png}
                                              ├── MANIFEST_ANALYSIS.json
                                              └── warnings.txt
```

### One-command reproduction

```bash
pip install -r analysis/requirements.txt
python3 scripts/consolidate_results.py    # freeze raw → results/frozen/
python3 analysis/check_k_consistency.py   # RQ2 K-batch completeness audit
python3 analysis/build_all.py             # 50+ paper outputs (tables + figures)
```

### Artifact documents

| Document | Purpose |
|---|---|
| [`AUDIT.md`](AUDIT.md) | initial repo audit (PHASE 0) + modification plan |
| [`DATASET_POLICY.md`](DATASET_POLICY.md) | 5-status classification (final/obsolete/diagnostic/partial/excluded), selection rules, hard guards |
| [`HARNESS_FIXES.md`](HARNESS_FIXES.md) | per-subject (S2/S4/S5) test corrections with root cause + why each fix does not mask an isolation failure |
| [`REPRODUCE.md`](REPRODUCE.md) | step-by-step reproduction from a clean clone |
| [`RQ5_IDEMPOTENCE.md`](RQ5_IDEMPOTENCE.md) | RQ5 protocol, current metrics, TSE-confirmatory gaps |
| [`PHASE2_ASSERTION_LEVEL.md`](PHASE2_ASSERTION_LEVEL.md) | per-assertion outcome collector + categories |
| [`PHASE7_RQ5_LOCK.md`](PHASE7_RQ5_LOCK.md) | RQ5 lock mechanism preventing parallel execution |
| `results/analysis/paper_claims.md` | every paper claim classified by evidence level |
| `results/analysis/paper_limitations.md` | L1-L10 limitations + mitigation paths |
| `results/analysis/tse_readiness_checklist.md` | A-K checklist of TSE-required items |

### RQ5 must run alone

RQ5 (idempotence) deliberately kills the operator pod. Other experiments running
concurrently will crash. The `harness/experiment_lock.py` module enforces this
mechanically:

```bash
# Inspect current lock state
python3 harness/experiment_lock.py status

# Recover after a manual abort (only when state is genuinely stale)
python3 harness/experiment_lock.py clear
```

See `PHASE7_RQ5_LOCK.md` for integration recipe.

### Live tracker vs frozen data

`EXPERIMENT_METRICS.md` is a **work-in-progress journal**, not a citable source.
The paper must cite `results/frozen/MANIFEST.json` and `results/analysis/MANIFEST_ANALYSIS.json`
for every number. `consolidate_results.py` enforces this by refusing to read
`EXPERIMENT_METRICS.md`, `AUDIT.md`, or `CLAUDE.md`.

---

## Anonymization for Double-Blind Submission

```bash
bash scripts/anonymize.sh --dry-run
bash scripts/anonymize.sh --apply
```

The script strips personal names, GitHub owner names, `ghcr.io/<owner>` registry
paths, personal email addresses, and private endpoints.

---

## Known Limitations

- RQ4 iterates over all five subjects, but `fault-catalog.yaml` mutations target
  `testapp/app.py` (S1 Flask app only). For S2–S5 the mutated flask image is injected
  as the main app image, which is architecturally inconsistent with the subject's own
  adapter image. RQ4 results for S2–S5 should be interpreted cautiously or restricted
  to S1 before submission.
- The RQ4 internal names (`static`, `llm_fixed`, `llm_free`) must be renamed to
  (`static`, `llm_matched_volume`, `llm_free_volume`) in code and analysis before
  publication.
- `analysis/04_bug_detection.py` still reflects a two-condition parsing assumption
  and must be updated for the three-condition protocol.
- `analysis/03_performance.py` contains a stale `N=20` caption; the configured and
  documented protocol uses 30 runs.
- CPU and memory summaries are not persisted automatically by experiment drivers.
- A figure-to-data provenance manifest is not yet committed.
- A Zenodo archive and DOI are not yet present.
- `anonymize.sh --check` is not yet implemented.

## Submission Readiness Checklist

- [x] all experiment drivers exist and produce output
- [x] all five subjects have adapter images and harness-adapter source
- [x] all subjects enabled in `config.yaml`
- [x] outputs are parseable (timestamped CSV)
- [x] RQ1, RQ3 use 30 runs
- [x] RQ4 uses three seed conditions
- [x] `fault-catalog.yaml` generated with `patch`-based apply
- [x] Azure VM provisioned for persistent experiment execution
- [ ] RQ4 scope restricted to S1 or cross-subject protocol clarified
- [ ] RQ4 seed condition names aligned with paper
- [ ] `analysis/04_bug_detection.py` updated for three conditions
- [ ] `analysis/03_performance.py` N=20 caption fixed
- [ ] figure-to-data provenance manifest committed
- [ ] Zenodo archive and DOI
- [ ] anonymization `--check` implemented

## Citation

This repository includes `CITATION.cff`. No Zenodo DOI is recorded yet. Until a DOI
is minted, cite using the repository title and state that it is the experimental
harness accompanying the study of checkpoint-based database isolation in Kubernetes
preview environments.
