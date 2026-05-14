# Preview-Operator — Experimental Harness

Reproducibility artefact for the paper:

> **"Checkpoint-based Database Isolation Eliminates Non-deterministic Test Variance
> in Kubernetes Preview Environments"**
>
> Target venue: *Empirical Software Engineering* (Springer), Q1.

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Docker | ≥ 24 | Build subject/adapter images |
| kubectl | ≥ 1.29 | Cluster interaction |
| helm | ≥ 3.14 | Operator install |
| Python | ≥ 3.12 | Harness + analysis |
| yq | ≥ 4 | Parse config.yaml in shell scripts |
| mutmut | 2.4.4 | Mutation testing (RQ4 only) |

All versions are frozen in `setup/versions.lock.yaml`.

---

## Repository layout

```
experimentation/
├── config.yaml                 ← single source of truth for all parameters
├── Makefile
├── run-all-experiments.sh
├── run_demo.py                 ← quick end-to-end smoke run (1 Preview CR)
├── subjects/                   ← one directory per experiment subject
│   ├── CONTRACT.md             ← formal subject contract (directory layout, test format)
│   ├── probe/                  ← shared Flask sidecar for S2–S5 (run_log proxy)
│   │   ├── probe.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   ├── s1-flask-catalog/       ← reference subject (Flask + PostgreSQL)
│   │   ├── meta.yaml
│   │   └── testapp/            ← app source (app.py, frontend.py, migrations/, tests/)
│   ├── s2-listmonk/            ← Listmonk v2.5.1 (Go, AGPL-3.0)
│   │   ├── meta.yaml
│   │   └── harness-adapter/    ← wrapper + tests
│   ├── s3-healthchecks/        ← Healthchecks v3.6 (Django, BSD-3)
│   │   ├── meta.yaml
│   │   └── harness-adapter/
│   ├── s4-umami/               ← Umami v2.15.1 (TypeScript/Next.js, MIT)
│   │   ├── meta.yaml
│   │   └── harness-adapter/
│   └── s5-petclinic/           ← Spring PetClinic REST v3.4.0 (Java, Apache-2.0)
│       ├── meta.yaml
│       └── harness-adapter/
├── setup/
│   ├── kind-config.yaml        ← Kind cluster (3 nodes)
│   ├── versions.lock.yaml      ← frozen image/chart versions
│   ├── bootstrap-cluster.sh    ← install cluster + operator
│   └── teardown.sh
├── harness/                    ← shared Python library
│   ├── config.py               ← reads config.yaml + subject loading helpers
│   ├── preview_factory.py      ← create / wait / delete Preview CRs (multi-subject)
│   ├── metrics_collector.py    ← collect Job timings, kubectl top
│   └── results_writer.py       ← write timestamped CSV files
├── exp_flakiness/              ← RQ1: isolation eliminates flakiness
├── exp_cross_pr/               ← RQ2: cross-PR pollution under concurrency
├── exp_performance/            ← RQ3: checkpoint overhead (30 runs)
├── exp_bug_detection/          ← RQ4: LLM-directed seeding vs. static (3 conditions)
├── exp_idempotence/            ← RQ5: operator convergence after restart
├── results/                    ← raw CSV output (gitignored except .gitkeep)
├── scripts/
│   └── anonymize.sh            ← double-blind submission package
└── analysis/
    ├── shared/stats.py         ← Mann-Whitney U, Vargha-Delaney, McNemar
    ├── shared/plotting.py      ← publication-ready matplotlib style
    ├── shared/latex.py         ← booktabs LaTeX table generation
    ├── 01_flakiness.py         ← RQ1 analysis (jupytext → .ipynb)
    ├── 02_cross_pr.py          ← RQ2
    ├── 03_performance.py       ← RQ3
    ├── 04_bug_detection.py     ← RQ4
    ├── 05_idempotence.py       ← RQ5
    └── figures/                ← generated PDF/PNG figures
```

---

## Experiment subjects

Five subjects of varying technology stacks exercise the isolation mechanism across
diverse application architectures.

| ID | Application | Stack | License | Port | Seed entities |
|----|-------------|-------|---------|------|---------------|
| S1 | Flask Catalog (reference) | Python/Flask + PostgreSQL | MIT | 8080 | 5 products |
| S2 | Listmonk v2.5.1 | Go | AGPL-3.0 | 9000 | 3 mailing lists |
| S3 | Healthchecks v3.6 | Django/Python | BSD-3 | 8000 | 2 health checks |
| S4 | Umami v2.15.1 | TypeScript/Next.js | MIT | 3000 | 1 website |
| S5 | Spring PetClinic REST v3.4.0 | Java/Spring Boot | Apache-2.0 | 9966 | 13 owners/pets |

All subjects implement the [subjects/CONTRACT.md](subjects/CONTRACT.md) interface:
a `/healthz` readiness endpoint, deterministic seed data, and three test suites
(`smoke.py`, `regression.py`, `e2e.py`) that write `PASS`/`FAIL` lines to stdout.

S2–S5 use a **shared probe sidecar** (`subjects/probe/`) that exposes the `run_log`
table over HTTP at port 9090 (`GET /api/run-log`, `POST /api/run-log`), decoupling
isolation probes from the upstream application.

### Enable subjects

Edit `config.yaml` to uncomment the subjects to include in all experiments:

```yaml
subjects:
  enabled:
    - s1-flask-catalog   # always active (reference)
    - s2-listmonk
    - s3-healthchecks
    - s4-umami
    - s5-petclinic
```

### Build and push adapter images

```bash
# Reference subject (S1)
cd subjects/s1-flask-catalog/testapp/
docker build -t ghcr.io/<owner>/idp-preview:<tag> .
docker push ghcr.io/<owner>/idp-preview:<tag>

# Shared probe sidecar (required for S2–S5)
cd subjects/probe/
docker build -t ghcr.io/<owner>/harness-probe:latest .
docker push ghcr.io/<owner>/harness-probe:latest

# Per-subject adapters (repeat for s3, s4, s5)
cd subjects/s2-listmonk/harness-adapter/
docker build -t ghcr.io/<owner>/s2-listmonk-adapter:v2.5.1 .
docker push ghcr.io/<owner>/s2-listmonk-adapter:v2.5.1
```

Update the image tags in `config.yaml → subjects.images` after pushing.

---

## Quick demo

Runs one Preview CR end-to-end and prints results:

```bash
cd experimentation/
python3 run_demo.py                  # default: s1-flask-catalog
python3 run_demo.py s2-listmonk      # run a specific subject
ISOLATION=false python3 run_demo.py  # baseline (no checkpoint isolation)
```

Expected output (isolation ON, all suites pass):

```
smoke       : phase=Succeeded  passed=5   failed=-
regression  : phase=Succeeded  passed=11  failed=-
e2e         : phase=Succeeded  passed=8   failed=-
```

---

## Step-by-step protocol

### 1 — Point to your cluster

Edit `config.yaml`:

```yaml
cluster:
  type: aks        # or kind
  name: <your-cluster>

app:
  image: ghcr.io/<owner>/idp-preview:<tag>
```

For AKS: run `az aks get-credentials --name <cluster> --resource-group <rg>` first.
For Kind: run `make bootstrap` to create the cluster and install the operator.

### 2 — Install Python analysis dependencies

```bash
make setup
```

### 3 — Verify the pipeline

```bash
python3 run_demo.py
```

All three suites must show `phase=Succeeded` before running the full experiments.

### 4 — (RQ4 only) Generate mutants

```bash
make generate-mutants
```

Runs `mutmut` on `subjects/s1-flask-catalog/testapp/app.py` and writes
`exp_bug_detection/fault-catalog.yaml` (~30s).
A pre-generated catalog (50 mutants) is already committed — only re-run if the
application source changes.

Requires `mutmut==2.4.4` on PATH (`pip install mutmut==2.4.4` then add
`~/.local/bin` to PATH).

### 5 — Run experiments

```bash
make all
# or individually:
make exp-flakiness      # RQ1 — ~5h  (30 runs × 2 isolation values × N subjects)
make exp-cross-pr       # RQ2 — ~3h
make exp-performance    # RQ3 — ~4h  (30 runs × 2 isolation values × N subjects)
make exp-bug-detection  # RQ4 — ~8h  (3 seed conditions: static, llm_fixed, llm_free)
make exp-idempotence    # RQ5 — ~2h
```

Each script writes a timestamped CSV to `results/`.

Override any parameter without editing files:

```bash
EXP_EXPERIMENTS_FLAKINESS_N_RUNS=5 make exp-flakiness
```

### 6 — Analyse and generate figures

```bash
make notebooks   # converts .py to .ipynb via jupytext
jupyter lab analysis/
```

Or run directly:

```bash
python analysis/01_flakiness.py
python analysis/02_cross_pr.py
# ...
```

Figures are written to `analysis/figures/` as 600-dpi PDFs.

---

## Test pipeline

The operator runs tests sequentially inside the Preview's namespace:

```
migration → saving → smoke → restore-regression → regression → restore-e2e → e2e
```

| Step | What happens |
|------|-------------|
| `migration` | Subject migration command → schema + seed data |
| `saving` | `pg_dump --data-only` → ConfigMap (checkpoint) |
| `smoke` | Quick API tests via requests |
| `restore-regression` | `psql < checkpoint` — DB reset to post-seed state |
| `regression` | API tests; creates test entities, writes `run_log` |
| `restore-e2e` | `psql < checkpoint` — DB reset again |
| `e2e` | End-to-end tests; checks `run_log` is empty and entity count = seed_count |

When `spec.database.isolationEnabled=false`, the `saving` and `restore-*` steps are
skipped. Suites then share a dirty DB — this is the **baseline** (no isolation) condition.

---

## RQ4 — Seed conditions

RQ4 uses a three-condition volume-control design to separate quality from diversity effects:

| Condition | AI enrichment | Temperature | Effect isolated |
|-----------|--------------|-------------|-----------------|
| `static` | No | — | Baseline (static fixtures only) |
| `llm_fixed` | Yes | 0.0 (deterministic) | Quality at constant diversity |
| `llm_free` | Yes | 0.7 (stochastic) | Diversity added on top of quality |

Hypothesis: `detection_rate[llm_free] > detection_rate[llm_fixed] > detection_rate[static]`.

The comparison `static` vs `llm_fixed` isolates content quality at equal volume.
The comparison `llm_fixed` vs `llm_free` isolates output diversity.

---

## PR number ranges

Each experiment uses a dedicated range of PR numbers to avoid namespace conflicts
when running in parallel:

| Experiment | PR range | Config key |
|-----------|----------|-----------|
| RQ1 Flakiness | 9000–9899 | `pr_number_base` + hash % 900 |
| RQ2 Cross-PR | 8000–8899 | `pr_number_base - 1000` + hex % 900 |
| RQ3 Performance | 9000–9899 | `pr_number_base` + hash % 900 |
| RQ4 Bug detection | 7000–7899 | `pr_number_base - 2000` + hash % 900 |
| RQ5 Idempotence | 6000–6899 | `pr_number_base - 3000` + hash % 900 |

Note: the Preview CR's `status.phase` stays `Running` even after tests complete.
Test completion is tracked via `status.tests.phase` (Succeeded / Failed).

---

## Operator instrumentation

| File | Change |
|------|--------|
| `api/v1alpha1/preview_types.go` | Added `spec.database.isolationEnabled *bool` (default `true`) |
| `internal/controller/tests.go` | `checkpointIsolationEnabled()` helper; save/restore steps conditional |

No test logic was added to the operator itself.

---

## Hypotheses and statistical tests

| RQ | Hypothesis | Test |
|----|-----------|------|
| RQ1 | `failure_rate[OFF] > failure_rate[ON]` | Mann-Whitney U, Vargha-Delaney Â₁₂, Fisher's exact |
| RQ2 | Failure rate grows with K when isolation=OFF | Mann-Whitney U per K, Â₁₂ |
| RQ3 | `overhead_pct < 15%` | Descriptive (mean, p95); no NHST needed |
| RQ4 | `detection_rate[llm_free] > detection_rate[llm_fixed] > detection_rate[static]` | McNemar's test (paired binary per mutant) |
| RQ5 | `divergence_count = 0` after any restart | Descriptive; convergence time distribution |

All tests use α = 0.05.

---

## Assumptions

1. Each Preview gets its own namespace and Postgres deployment — namespace-level isolation is
   always active. This experiment measures **within-preview test-suite state** pollution only.
2. DB checkpoint content is deterministic for a given seed script (same SQL, same Postgres version).
3. The LLM seed differs per run in `llm_free` condition (temperature > 0) — this is intentional
   and models real usage. The `llm_fixed` condition (temperature = 0) provides a deterministic
   quality baseline.
4. mutmut mutants that do not compile are skipped automatically.
5. `kubectl top` requires metrics-server to be running (installed by `bootstrap-cluster.sh`).

---

## Double-blind submission

To produce an anonymized archive for double-blind review:

```bash
bash scripts/anonymize.sh            # produces anonymized-submission.tar.gz
bash scripts/anonymize.sh --dry-run  # preview affected files without modifying
```

The script replaces all identifying strings (GitHub username, email, AKS endpoint,
registry URLs) with neutral placeholders and packages the result as a gzip archive.

---

## Zenodo archive

After acceptance, publish a Zenodo archive with:
- This `experimentation/` directory
- `results/` CSV files from the reported runs
- `analysis/figures/` final PDFs
- `setup/versions.lock.yaml` (all exact digests)

Update `CITATION.cff` with the DOI before submission.
