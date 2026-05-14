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
| Docker | ≥ 24 | Build images |
| kind | ≥ 0.23 | Local K8s cluster |
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
├── setup/
│   ├── kind-config.yaml        ← Kind cluster (3 nodes)
│   ├── versions.lock.yaml      ← frozen image/chart versions
│   ├── bootstrap-cluster.sh    ← install cluster + operator
│   └── teardown.sh
├── harness/                    ← shared Python library (no tests here)
│   ├── config.py               ← reads config.yaml
│   ├── preview_factory.py      ← create / wait / delete Preview CRs
│   ├── metrics_collector.py    ← collect ReconcileEvents, Job timings, kubectl top
│   └── results_writer.py       ← write timestamped CSV files
├── exp_flakiness/              ← RQ1
├── exp_cross_pr/               ← RQ2
├── exp_performance/            ← RQ3
├── exp_bug_detection/          ← RQ4
├── exp_idempotence/            ← RQ5
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

## Step-by-step protocol

### 1 — Bootstrap the cluster

```bash
cd experimentation/
make bootstrap
```

This creates a 3-node Kind cluster (`preview-exp`), installs ingress-nginx,
metrics-server, and the preview-operator via Helm. Both `preview-operator:dev`
and `idp-preview:dev` images are built from the local repos and loaded into Kind.

**AKS**: edit `config.yaml` → `cluster.type: aks` and set `cluster.name` to your
AKS cluster name. Run `az aks get-credentials` before bootstrapping.

### 2 — Install Python analysis dependencies

```bash
make setup
```

### 3 — (RQ4 only) Generate mutants

```bash
make generate-mutants
```

Runs `mutmut` on `idp-preview/app.py` and writes `exp_bug_detection/fault-catalog.yaml`.
This step is slow (~10 min); results are committed and shipped with the artefact.

### 4 — Run all experiments

```bash
make all
# or individually:
make exp-flakiness
make exp-cross-pr
make exp-performance
make exp-bug-detection
make exp-idempotence
```

Each script writes a timestamped CSV to `results/`.

Override any parameter without editing files:

```bash
EXP_EXPERIMENTS_FLAKINESS_N_RUNS=5 make exp-flakiness
```

### 5 — Analyse and generate figures

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

## Operator instrumentation

The operator (`preview-operator`) was minimally modified to support baseline experiments:

| File | Change |
|------|--------|
| `api/v1alpha1/preview_types.go` | Added `spec.database.isolationEnabled *bool` (default `true`) |
| `internal/controller/tests.go` | Added `checkpointIsolationEnabled()` helper; 4 step transitions now conditional |

When `isolationEnabled=false`, the pipeline skips the `saving`, `restore-regression`, and
`restore-e2e` steps. This is the **baseline** condition (no isolation).
No test code was added to the operator itself.

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
