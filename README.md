# Preview-Experiments: Experimental Harness for Checkpoint-Based Database Isolation in Kubernetes Preview Environments

## Title

This repository contains the experimental harness used to evaluate checkpoint-based
database isolation in Kubernetes preview environments. It is intended as a
reproducibility-oriented artefact for an empirical software engineering paper and
documents the current state of the harness conservatively, without claiming
artefacts, results, or subject integrations that are not present in the repository.

## Problem Statement

Preview environments execute migrations, seed data, and multiple test suites inside
ephemeral Kubernetes namespaces. Without explicit database reset points, state
created by one suite can leak into later suites, which may increase failure
variability and complicate interpretation of test outcomes. This repository studies
whether checkpoint-based restoration mitigates such state pollution, what runtime
overhead it introduces, and how robust the operator remains under concurrency,
mutation-based fault seeding, and controller restarts.

This repository should be described as `preview-experiments` or
`experimentation/`. Several names coexist in the tree and must be interpreted
carefully:

- `preview-operator` refers to the operator repository used by the harness, not to this repository.
- `idp-preview` refers to the current application image/repository configured in `config.yaml`.
- `s1-flask-catalog` is the canonical identifier of the current reference subject.
- `testapp/` contains the source code of the current reference subject.
- `preview-env` is not a repository or directory name in this tree and should be avoided in the paper text.

## Research Questions

### RQ1 — Flakiness reduction with checkpoint-based database isolation

- Objective: Evaluate whether checkpoint save/restore reduces suite-level failure variability relative to a no-isolation baseline.
- Independent variables: `isolation_enabled ∈ {true, false}`; subject ID.
- Metrics measured: `failure_rate`, `suite_pass_rate`; step-level timings are also captured and can support contextual interpretation. `flaky_test_rate` and `state_contamination_rate` are desirable reporting metrics but are not yet emitted directly as dedicated CSV columns.
- Number of runs: 30 runs per isolation condition per enabled subject, as specified in `config.yaml`.
- Expected output: `results/flakiness_test_outcomes_<timestamp>.csv`.
- Planned statistical test: Mann-Whitney U, Fisher's exact test, and Vargha-Delaney effect size.

### RQ2 — Cross-preview / cross-PR state pollution under concurrency

- Objective: Evaluate whether higher concurrency amplifies failure rates when isolation is disabled.
- Independent variables: `concurrency_K ∈ {2, 4, 8}`; `isolation_enabled ∈ {true, false}`; subject ID.
- Metrics measured: `cross_preview_failure_rate`, `suite_pass_rate`; `queueing_delay_sec` is desirable but not currently emitted as a dedicated metric.
- Number of runs: the current implementation launches one concurrent batch per `K × isolation × subject` for each invocation of `exp_cross_pr/run.py`. Additional replications require rerunning the script and aggregating CSV files.
- Expected output: `results/cross_pr_test_outcomes_<timestamp>.csv`.
- Planned statistical test: Mann-Whitney U and Vargha-Delaney effect size per concurrency level.

### RQ3 — Performance overhead of checkpoint/restore isolation

- Objective: Quantify the time cost of checkpoint save/restore relative to overall pipeline duration.
- Independent variables: `isolation_enabled ∈ {true, false}`; subject ID.
- Metrics measured: `checkpoint_save_time_sec`, `checkpoint_restore_time_sec`, `pipeline_duration_sec`, `overhead_pct`. CPU and memory summaries are desirable but are not written automatically by the current experiment scripts.
- Number of runs: 30 runs per isolation condition per enabled subject. This README documents 30 runs to align RQ3 with the RQ1 protocol, and `config.yaml` already sets `experiments.performance.n_runs: 30`.
- Expected output: `results/performance_run_metrics_<timestamp>.csv`.
- Planned statistical test: descriptive statistics are currently implemented; if inferential comparison is added later, it should be reported explicitly.

### RQ4 — Mutation-based bug detection with seed conditions

- Objective: Evaluate whether richer seed data improves mutation detection, while separating data-volume effects from semantic-diversity effects.
- Independent variables: seed condition; mutant ID; subject ID.
- Metrics measured: `killed_mutants`, `survived_mutants`, `mutation_score`, `detection_rate_by_seed_condition`.
- Number of runs: one execution per `mutant × seed condition × subject` in the current implementation, after mutant generation.
- Expected output: `results/bug_detection_test_outcomes_<timestamp>.csv`.
- Planned statistical test: McNemar's test on paired mutant-detection outcomes.

Protocol-level seed conditions for the paper should be:

- `static`: static seed data only.
- `llm_matched_volume`: LLM-generated seed data constrained to the same number of rows per table as the static seed.
- `llm_free_volume`: LLM-generated seed data with unconstrained volume.

This distinction is methodologically important because it separates the effect of
row-count volume from the effect of semantic diversity or relevance.

Current repository status:

- The current configuration implements `static`, `llm_fixed`, and `llm_free`.
- The repository does not yet provide explicit artefacts proving per-table row-count matching for `llm_matched_volume`.
- The analysis script still reflects an older two-condition parsing assumption and must be updated before submission.

Accordingly, `llm_matched_volume` and `llm_free_volume` should be treated as the
documented target protocol for the paper, not as fully implemented repository
artefacts at present.

### RQ5 — Operator idempotence and convergence after restart

- Objective: Evaluate whether the operator converges to a consistent end state after controller restarts during pipeline execution.
- Independent variables: restart step; subject ID.
- Metrics measured: `convergence_time_sec`, `duplicate_job_count`, `lost_status_count`, `final_state_consistent`.
- Number of runs: 3 restarts per configured pipeline step per enabled subject, as specified in `config.yaml`.
- Expected output: `results/idempotence_run_metrics_<timestamp>.csv`.
- Planned statistical test: descriptive analysis of convergence time and divergence counts.

## Experimental Design

The harness evaluates a preview pipeline in which a Preview custom resource creates
an application instance, a PostgreSQL instance, and sequential test jobs. The core
comparison for RQ1 and RQ3 is between two operator configurations:

- Isolation ON: database checkpointing is enabled and restore jobs execute between suites.
- Isolation OFF: checkpoint save/restore jobs are skipped and suites share state.

The current repository supports the following experiment drivers:

- `exp_flakiness/run.py`
- `exp_cross_pr/run.py`
- `exp_performance/run.py`
- `exp_bug_detection/run.py`
- `exp_idempotence/run.py`

The harness writes timestamped CSV files under `results/` and analysis scripts under
`analysis/` consume these files to generate tables and figures. The documentation in
this README is intentionally restricted to what these scripts and files currently
support.

## Repository Structure

```text
experimentation/
├── README.md
├── CITATION.cff
├── LICENSE
├── Makefile
├── config.yaml
├── run_demo.py
├── run-all-experiments.sh
├── analysis/
│   ├── 01_flakiness.py
│   ├── 02_cross_pr.py
│   ├── 03_performance.py
│   ├── 04_bug_detection.py
│   ├── 05_idempotence.py
│   ├── requirements.txt
│   └── shared/
├── exp_bug_detection/
│   ├── fault-catalog.yaml
│   ├── mutations/
│   └── run.py
├── exp_cross_pr/run.py
├── exp_flakiness/
│   ├── README.md
│   └── run.py
├── exp_idempotence/run.py
├── exp_performance/run.py
├── harness/
│   ├── config.py
│   ├── metrics_collector.py
│   ├── preview_factory.py
│   ├── results_writer.py
│   └── schemas/
├── results/
├── scripts/
│   └── anonymize.sh
├── setup/
│   ├── bootstrap-cluster.sh
│   ├── kind-config.yaml
│   ├── teardown.sh
│   └── versions.lock.yaml
├── subjects/
│   ├── CONTRACT.md
│   ├── probe/
│   ├── s1-flask-catalog/meta.yaml
│   ├── s2-listmonk/meta.yaml
│   ├── s3-healthchecks/meta.yaml
│   ├── s4-umami/meta.yaml
│   └── s5-petclinic/meta.yaml
└── testapp/
    ├── app.py
    ├── frontend.py
    ├── migrations/
    ├── requirements.txt
    ├── seeds/
    └── tests/
```

Important scope notes:

- `subjects/` currently contains a formal contract, metadata files, and the shared `probe/` service.
- The source tree of the reference subject is currently stored in `testapp/`, not under `subjects/s1-flask-catalog/testapp/`.
- The repository does not currently contain committed `harness-adapter/` directories for `s2` to `s5`; only metadata files are present.

## Subject Applications

### Current subject

- Subject ID: `s1-flask-catalog`
- Source directory: `testapp/`
- Metadata file: `subjects/s1-flask-catalog/meta.yaml`
- Stack: Python, Flask, Playwright-based UI tests, PostgreSQL
- Database: PostgreSQL
- Tests available: `testapp/tests/smoke.py`, `testapp/tests/regression.py`, `testapp/tests/e2e.py`
- Current limitations: the source tree and the metadata tree are not colocated, which is acceptable for internal use but less tidy for an archival artefact

### Planned extension

- `subjects/CONTRACT.md` defines the expected structure for external subjects.
- Metadata stubs already exist for:
  - `s2-listmonk`
  - `s3-healthchecks`
  - `s4-umami`
  - `s5-petclinic`
- Future repository cleanup may move the reference application under `subjects/s1-flask-catalog/`.
- Additional open-source subjects should not be claimed as integrated until their adapter code, tests, and build artefacts are committed.

## Test Pipeline

The intended pipeline for each preview run is:

1. deploy preview environment
2. run migrations
3. load seed data
4. save database checkpoint
5. run smoke tests
6. restore checkpoint
7. run regression tests
8. restore checkpoint
9. run e2e tests
10. collect metrics
11. cleanup environment

Current implementation notes:

- The operator-level step names visible through Kubernetes Jobs are `migration`, `saving`, `smoke`, `restore-regression`, `regression`, `restore-e2e`, and `e2e`.
- The current S1 test suites emit parseable `PASS` / `FAIL` lines plus a final summary line.
- A structured `harness-v1` JSON output format is not yet implemented in the repository and should be treated as planned work.
- The shell wrappers `smoke.sh`, `regression.sh`, and `e2e.sh` do not exist in this repository. The current executable suites are Python scripts under `testapp/tests/`.

## Metrics Collected

The table below distinguishes between metrics that are currently emitted or directly
derivable from repository outputs and metrics that are desirable for the paper but
not yet first-class artefacts in the repository.

| Metric | Status | Current source or note |
|---|---|---|
| `failure_rate` | available | Derivable from `*_test_outcomes_*.csv` suite outcomes |
| `flaky_test_rate` | planned | Requires a stable per-test flakiness definition and per-test outcome capture |
| `suite_pass_rate` | available | Derivable from suite-level outcomes |
| `state_contamination_rate` | partial | Proxied by restore-sensitive suite failures; not emitted as a dedicated column |
| `checkpoint_save_time_sec` | available | `run_metrics.step == saving` |
| `checkpoint_restore_time_sec` | available | `run_metrics.step ∈ {restore-regression, restore-e2e}` |
| `restore_success_rate` | partial | Indirectly inferable; not emitted explicitly |
| `dirty_state_detected` | partial | Indirectly inferable from restore-sensitive failures; not emitted explicitly |
| `run_log_clean` | planned as first-class metric | Tested in S1 Python suites, but not persisted as a named CSV metric today |
| `provisioning_time_sec` | planned | Not emitted as a dedicated field |
| `pipeline_duration_sec` | available | Stored as `total_reconcile_s` in `performance` outputs |
| `overhead_pct` | available | Stored in `performance` outputs using the `requeue_count` field as a carrier |
| `cpu_avg` / `cpu_p95` | planned or manual | `kubectl top` collection exists in `harness.metrics_collector`, but experiment scripts do not persist these summaries automatically |
| `memory_avg` / `memory_p95` | planned or manual | Same status as CPU summaries |
| `concurrency_K` | available | Encoded in RQ2 run identifiers |
| `cross_preview_failure_rate` | partial | Derivable from RQ2 suite failures; not emitted as a dedicated field |
| `queueing_delay_sec` | planned | Not emitted today |
| `killed_mutants` | derivable | Derivable from failed mutant runs |
| `survived_mutants` | derivable | Derivable from non-failed mutant runs |
| `mutation_score` | derivable | Computed during analysis from mutant outcomes |
| `detection_rate_by_seed_condition` | derivable | Computed during analysis |
| `convergence_time_sec` | available | `idempotence` uses `step_duration_s` for convergence time |
| `duplicate_job_count` | planned | Not emitted today |
| `lost_status_count` | planned | Not emitted today |
| `final_state_consistent` | partial | Inferred through successful completion and zero divergence flags |

## Configuration

The single source of truth for experiment parameters is `config.yaml`, with optional
environment-variable overrides through the `EXP_...` prefix.

Current noteworthy configuration values are:

- Cluster mode: `kind` by default
- Operator namespace: `preview-operator-system`
- Preview CR namespace: `default`
- Enabled subject list: currently only `s1-flask-catalog` is enabled by default
- RQ1 run count: `experiments.flakiness.n_runs = 30`
- RQ3 run count: `experiments.performance.n_runs = 30`
- RQ5 restart count: `experiments.idempotence.n_restarts_per_step = 3`

Current naming inconsistencies that should be interpreted carefully:

- `app.repo` and image tags still reference `ihsenalaya/idp-preview`.
- `subjects.images.s1-flask-catalog` points to the same application image.
- RQ4 currently uses `static`, `llm_fixed`, and `llm_free` in `config.yaml`; the paper protocol should rename these to `static`, `llm_matched_volume`, and `llm_free_volume` once implementation and analysis are aligned.

## How to Run Experiments

### Prerequisites

- Docker
- `kubectl`
- Helm
- Python 3
- `pip`
- `jupytext` for notebook conversion
- `mutmut` for RQ4 mutant generation
- A Kubernetes cluster reachable through the active kubeconfig

Exact versions should be frozen using:

- `setup/versions.lock.yaml`
- `config.yaml`
- `analysis/requirements.txt`

### Recommended execution sequence

```bash
make setup
make bootstrap
python3 run_demo.py
make exp-flakiness
make exp-cross-pr
make exp-performance
make generate-mutants
make exp-bug-detection
make exp-idempotence
make notebooks
```

An alternative batch entry point is:

```bash
bash run-all-experiments.sh
```

Examples of parameter overrides:

```bash
EXP_EXPERIMENTS_FLAKINESS_N_RUNS=5 python3 exp_flakiness/run.py
EXP_EXPERIMENTS_PERFORMANCE_N_RUNS=5 python3 exp_performance/run.py
ISOLATION=false python3 run_demo.py
```

## Expected Outputs

The following outputs are expected from the current repository state:

- `results/flakiness_test_outcomes_<timestamp>.csv`
- `results/cross_pr_test_outcomes_<timestamp>.csv`
- `results/performance_run_metrics_<timestamp>.csv`
- `results/bug_detection_test_outcomes_<timestamp>.csv`
- `results/idempotence_run_metrics_<timestamp>.csv`
- `results/run-all-<timestamp>.log` when `run-all-experiments.sh` is used
- `analysis/0*.ipynb` after `make notebooks`
- `analysis/figures/*.pdf` after running the analysis scripts
- `anonymized-submission.tar.gz` after running `scripts/anonymize.sh`

CSV schemas currently present in the repository are:

- `harness/schemas/test_outcomes.schema.csv`
- `harness/schemas/run_metrics.schema.csv`
- `harness/schemas/resource_usage.schema.csv`

The repository currently stores raw CSV files under `results/`. It does not yet
ship a dedicated manifest that binds a paper figure to a specific raw CSV file and
analysis command; that mapping should be finalized before submission.

## Statistical Analysis

The repository contains analysis scripts for each research question:

- `analysis/01_flakiness.py`
- `analysis/02_cross_pr.py`
- `analysis/03_performance.py`
- `analysis/04_bug_detection.py`
- `analysis/05_idempotence.py`

Current statistical plan:

- RQ1: Mann-Whitney U, Fisher's exact test, Vargha-Delaney effect size
- RQ2: Mann-Whitney U and Vargha-Delaney effect size per concurrency level
- RQ3: descriptive statistics for step durations and overhead
- RQ4: McNemar's test on paired mutant outcomes
- RQ5: descriptive statistics for convergence times and divergence counts

Important caveats before submission:

- `analysis/03_performance.py` still contains a stale caption mentioning `N=20`; the documented protocol and `config.yaml` both use 30 runs.
- `analysis/04_bug_detection.py` still reflects an outdated two-condition parsing assumption and should be aligned with the three-condition protocol before publication.

## Reproducibility

To support reproducibility, the following should be fixed and archived for every
reported run:

- cluster and container versions from `setup/versions.lock.yaml`
- experiment parameters from `config.yaml`
- Python dependencies from `analysis/requirements.txt`
- raw CSV outputs from `results/`
- generated figures from `analysis/figures/`
- analysis scripts under `analysis/`
- mutant catalog `exp_bug_detection/fault-catalog.yaml` when RQ4 is reported
- `CITATION.cff`, which is present in the repository

Suggested minimal reproduction workflow:

```bash
make setup
make bootstrap
python3 run_demo.py
bash run-all-experiments.sh
python3 analysis/01_flakiness.py
python3 analysis/02_cross_pr.py
python3 analysis/03_performance.py
python3 analysis/04_bug_detection.py
python3 analysis/05_idempotence.py
```

Expected reproducibility artefacts:

- raw CSV files under `results/`
- generated PDF figures under `analysis/figures/`
- optional `.ipynb` notebooks generated from the analysis scripts

Zenodo status:

- `CITATION.cff` exists.
- A Zenodo archive is planned but no DOI is recorded in the repository yet.

## Anonymization for Double-Blind Submission

An IEEE-style double-blind package should remove or replace:

- personal names
- GitHub owner names
- `ghcr.io/<owner>` registry paths
- personal email addresses
- private domains or endpoints

The repository already contains `scripts/anonymize.sh`, which currently supports:

- `--dry-run`
- default archive creation to `anonymized-submission.tar.gz`

Recommended submission-facing interface:

```bash
bash scripts/anonymize.sh --dry-run
bash scripts/anonymize.sh --apply
bash scripts/anonymize.sh --check
```

Current limitation:

- `--apply` and `--check` are not implemented today and should be treated as TODO items.

## Known Limitations / TODO

- The repository documents multi-subject experimentation, but only the S1 reference subject is materially present as source code in `testapp/`.
- `subjects/s2-*` to `subjects/s5-*` currently provide metadata only; committed adapter source trees are absent.
- The RQ4 implementation currently uses `static`, `llm_fixed`, and `llm_free` rather than the submission-facing names `static`, `llm_matched_volume`, and `llm_free_volume`.
- The repository does not yet provide explicit row-count auditing that proves `llm_matched_volume` matches the static seed volume table by table.
- `analysis/04_bug_detection.py` must be updated to consume the three-condition protocol correctly.
- `analysis/03_performance.py` still contains stale `N=20` text even though the documented and configured protocol uses 30 runs.
- The current CSV outputs are suite-level for most experiments and do not yet persist all per-test isolation probes as first-class metrics.
- `smoke.sh`, `regression.sh`, and `e2e.sh` do not exist; the current tests are Python scripts.
- A `harness-v1` JSON result format is not yet implemented.
- CPU and memory sampling helpers exist, but the experiment drivers do not yet persist `cpu_avg`, `cpu_p95`, `memory_avg`, or `memory_p95` automatically.
- Queueing delay, duplicate job counts, and lost status counts are not yet emitted as dedicated metrics.
- A figure-to-data provenance manifest is not yet committed.
- A finalized Zenodo archive and DOI are not yet present.
- An anonymization script with `--dry-run`, `--apply`, and `--check` parity is not yet available.

## Planned / TODO

The following items are methodologically desirable for a camera-ready artefact but
should not be described as already implemented:

- Rename the RQ4 seed conditions in code and analysis to `static`, `llm_matched_volume`, and `llm_free_volume`.
- Add explicit per-table seed-volume validation for the matched-volume condition.
- Persist per-test outcomes, not only suite outcomes, in raw CSV files.
- Add structured `harness-v1` JSON outputs alongside `PASS` / `FAIL` text outputs.
- Move the S1 source tree under `subjects/s1-flask-catalog/` or document the split layout with a formal rationale.
- Commit adapter implementations for the planned external subjects before claiming cross-subject validation.

## Citation

This repository includes `CITATION.cff`. At present, no Zenodo DOI is recorded in
that file. Until a DOI is minted, cite the artefact using its repository title and
state clearly that it is the experimental harness accompanying the study of
checkpoint-based database isolation in Kubernetes preview environments.

## Submission Readiness Checklist

- [ ] all test scripts exist
- [x] outputs are parseable
- [ ] config matches documented protocol
- [x] RQ3 uses 30 runs
- [ ] RQ4 controls seed volume
- [x] raw CSV files are generated
- [ ] statistical scripts are reproducible
- [ ] figures are generated from raw data
- [ ] artifact archive is prepared
- [ ] anonymization check passes
- [x] multi-subject validation is available or clearly marked as planned
