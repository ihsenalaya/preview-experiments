PYTHON      := python3
RESULTS_DIR := results
FIGURES_DIR := analysis/figures

.PHONY: all setup bootstrap teardown \
        exp-flakiness exp-cross-pr exp-performance exp-bug-detection exp-idempotence \
        generate-mutants notebooks clean help

## Run all experiments end-to-end
all: setup exp-flakiness exp-cross-pr exp-performance exp-bug-detection exp-idempotence notebooks

## Install Python analysis dependencies
setup:
	pip install -r analysis/requirements.txt
	pip install pyyaml

## Bootstrap Kind cluster and install operator
bootstrap:
	bash setup/bootstrap-cluster.sh

## Tear down experiment namespaces (add CLUSTER=1 to delete the cluster)
teardown:
	bash setup/teardown.sh $(if $(CLUSTER),--delete-cluster,)

## RQ1: flakiness
exp-flakiness:
	$(PYTHON) exp_flakiness/run.py

## RQ2: cross-PR pollution
exp-cross-pr:
	$(PYTHON) exp_cross_pr/run.py

## RQ3: performance overhead
exp-performance:
	$(PYTHON) exp_performance/run.py

## RQ4: generate mutants (run once before exp-bug-detection)
generate-mutants:
	bash exp_bug_detection/mutations/generate-mutants.sh

## RQ4: bug detection
exp-bug-detection:
	$(PYTHON) exp_bug_detection/run.py

## RQ5: idempotence
exp-idempotence:
	$(PYTHON) exp_idempotence/run.py

## Convert .py analysis scripts to Jupyter notebooks
notebooks:
	jupytext --to notebook analysis/0*.py

## Remove generated figures and compiled Python files
clean:
	rm -rf $(FIGURES_DIR)/*.pdf $(FIGURES_DIR)/*.png
	find . -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

help:
	@grep -E '^##' Makefile | sed 's/## //'
