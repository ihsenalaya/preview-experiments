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
| Docker | ≥ 24 | Build testapp image |
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
├── testapp/                    ← self-contained reference application
│   ├── app.py                  ← Flask backend, port 8080 (CORS enabled)
│   ├── frontend.py             ← Flask frontend, port 3000
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── migrations/             ← schema (001) + seed data (002)
│   ├── seeds/
│   ├── Dockerfile
│   └── tests/
│       ├── smoke.py            ← 5 API tests (requests)
│       ├── regression.py       ← 11 API tests incl. isolation probe
│       └── e2e.py              ← 8 Playwright/Chromium tests incl. isolation probes
├── setup/
│   ├── kind-config.yaml        ← Kind cluster (3 nodes)
│   ├── versions.lock.yaml      ← frozen image/chart versions
│   ├── bootstrap-cluster.sh    ← install cluster + operator
│   └── teardown.sh
├── harness/                    ← shared Python library
│   ├── config.py               ← reads config.yaml + EXP_* env overrides
│   ├── preview_factory.py      ← create / wait / delete Preview CRs
│   ├── metrics_collector.py    ← collect Job timings, kubectl top
│   └── results_writer.py       ← write timestamped CSV files
├── exp_flakiness/              ← RQ1: isolation eliminates flakiness
├── exp_cross_pr/               ← RQ2: cross-PR pollution under concurrency
├── exp_performance/            ← RQ3: checkpoint overhead
├── exp_bug_detection/          ← RQ4: isolation improves mutation detection
├── exp_idempotence/            ← RQ5: operator convergence after restart
├── results/                    ← raw CSV output (gitignored except .gitkeep)
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

## Reference application (`testapp/`)

A minimal product-catalogue app (Flask + PostgreSQL) used as the experiment subject.

| Component | Description |
|-----------|-------------|
| Backend | Flask, port 8080, REST API: products, categories, reviews, orders, stats |
| Frontend | Flask, port 3000, HTML/JS catalogue with Playwright-testable UI |
| Schema | 5 tables: `categories`, `products`, `reviews`, `orders`, `run_log` |
| Seed | 2 alembic migrations: schema (001) + 5 seed products (002) |
| `run_log` | Isolation probe table: each suite writes its name; restore must clear it |

### Build and push

```bash
cd testapp/
docker build -t ghcr.io/<owner>/idp-preview:<tag> .
docker push ghcr.io/<owner>/idp-preview:<tag>
# Update config.yaml → app.image
```

### Test suites

| Suite | Runner | Tests | Isolation probes |
|-------|--------|-------|-----------------|
| smoke | `requests` | 5 | — |
| regression | `requests` | 11 | `run_log_clean` (run_log empty at start) |
| e2e | Playwright/Chromium | 8 | `run_log_clean`, `product_count_matches_seed` |

---

## Quick demo

Runs one Preview CR end-to-end and prints results:

```bash
cd experimentation/
python3 run_demo.py
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

Runs `mutmut` on `testapp/app.py` and writes `exp_bug_detection/fault-catalog.yaml` (~30s).
A pre-generated catalog (50 mutants) is already committed — only re-run if `testapp/app.py` changes.

Requires `mutmut==2.4.4` on PATH (`pip install mutmut==2.4.4` then add `~/.local/bin` to PATH).

### 5 — Run experiments

```bash
make all
# or individually:
make exp-flakiness      # RQ1 — ~5h  (30 runs × 2 isolation values)
make exp-cross-pr       # RQ2 — ~3h
make exp-performance    # RQ3 — ~2h  (20 runs × 2 isolation values)
make exp-bug-detection  # RQ4 — ~6h
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
| `migration` | alembic upgrade head → schema + seed data |
| `saving` | `pg_dump --data-only` → ConfigMap (checkpoint) |
| `smoke` | 5 API tests via requests |
| `restore-regression` | `psql < checkpoint` — DB reset to post-seed state |
| `regression` | 11 API tests; creates `exp-product`, writes `run_log` |
| `restore-e2e` | `psql < checkpoint` — DB reset again |
| `e2e` | 8 Playwright tests; checks `run_log` is empty and product count = 5 |

When `spec.database.isolationEnabled=false`, the `saving` and `restore-*` steps are
skipped. Suites then share a dirty DB — this is the **baseline** (no isolation) condition.

---

## PR number ranges

Each experiment uses a dedicated range of PR numbers to avoid namespace conflicts when running in parallel:

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
| RQ4 | `detection_rate[LLM] > detection_rate[static]` | McNemar's test (paired binary per mutant) |
| RQ5 | `divergence_count = 0` after any restart | Descriptive; convergence time distribution |

All tests use α = 0.05.

---

## Assumptions

1. Each Preview gets its own namespace and Postgres deployment — namespace-level isolation is
   always active. This experiment measures **within-preview test-suite state** pollution only.
2. DB checkpoint content is deterministic for a given seed script (same SQL, same Postgres version).
3. The LLM seed differs per run (temperature > 0) — this is intentional and models real usage.
4. mutmut mutants that do not compile are skipped automatically.
5. `kubectl top` requires metrics-server to be running (installed by `bootstrap-cluster.sh`).

---

## Zenodo archive

After acceptance, publish a Zenodo archive with:
- This `experimentation/` directory
- `results/` CSV files from the reported runs
- `analysis/figures/` final PDFs
- `setup/versions.lock.yaml` (all exact digests)

Update `CITATION.cff` with the DOI before submission.
