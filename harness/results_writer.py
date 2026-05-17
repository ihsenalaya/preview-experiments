"""Write experiment results to per-subject timestamped CSV files."""
import csv
import pathlib
from datetime import datetime, timezone

_ROOT = pathlib.Path(__file__).parent.parent
_RESULTS = _ROOT / "results"
_RESULTS.mkdir(exist_ok=True)

_SCHEMAS = {
    "run_metrics": [
        "run_id", "experiment", "subject_id", "preview_name", "namespace",
        "isolation_enabled", "phase", "step", "step_duration_s",
        "total_reconcile_s", "requeue_count", "timestamp_utc",
    ],
    "test_outcomes": [
        "run_id", "experiment", "subject_id", "preview_name", "isolation_enabled",
        "suite", "test_name", "outcome", "db_rows_before",
        "db_rows_after", "timestamp_utc",
    ],
    "resource_usage": [
        "run_id", "experiment", "subject_id", "preview_name", "namespace",
        "timestamp_utc", "cpu_millicores", "mem_mib",
    ],
    # PHASE 2 — assertion-level outcomes (per individual t("...", ...) call
    # in the test programs). Populated by harness/assertion_collector.py via
    # reading kubectl get preview .status.tests.<suite>.output. Coexists with
    # test_outcomes (suite-level) for backward compatibility.
    "assertion_outcomes": [
        "experiment_id", "subject_id", "run_id", "preview_name",
        "isolation_enabled", "strategy", "suite_name", "assertion_id",
        "assertion_category", "outcome", "expected", "observed",
        "normalized_failure_signature", "is_isolation_sensitive", "ts",
    ],
    # PHASE 3 — DB-state metrics for restore verification. Populated by
    # harness/db_state_collector.py via kubectl exec into the postgres pod.
    # One row per (run_id, step, schema, table) plus a summary row
    # (table_name='*') carrying snapshot_hash_global.
    # Verification: post_checkpoint snapshot_hash_global must equal
    # post_restore_regression and post_restore_e2e snapshot_hash_global.
    "db_state_metrics": [
        "run_id", "subject_id", "preview_name", "isolation_enabled",
        "step", "schema_name", "table_name", "row_count", "content_hash",
        "excluded_columns", "snapshot_hash_global", "ts",
    ],
}


def _subject_dir(subject_id: str) -> pathlib.Path:
    d = _RESULTS / (subject_id or "unknown")
    d.mkdir(exist_ok=True)
    return d


def _open_csv(schema_name: str, experiment: str, subject_id: str):
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = _subject_dir(subject_id) / f"{experiment}_{schema_name}_{ts}.csv"
    f = open(path, "w", newline="")
    writer = csv.DictWriter(f, fieldnames=_SCHEMAS[schema_name], extrasaction="ignore")
    writer.writeheader()
    return f, writer, path


class RunWriter:
    """Context manager that writes rows to per-subject CSV files.

    One file is created per subject_id encountered. Files are stored under
    results/<subject_id>/<experiment>_<schema>_<timestamp>.csv.
    """

    def __init__(self, schema_name: str, experiment: str):
        self._schema = schema_name
        self._experiment = experiment
        self._handles: dict[str, tuple] = {}  # subject_id -> (file, writer, path)
        self._last_path: pathlib.Path | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        for f, _, _ in self._handles.values():
            f.close()
        self._handles.clear()

    def write(self, row: dict) -> None:
        subject_id = row.get("subject_id") or "unknown"
        if subject_id not in self._handles:
            f, writer, path = _open_csv(self._schema, self._experiment, subject_id)
            self._handles[subject_id] = (f, writer, path)
            self._last_path = path
        f, writer, _ = self._handles[subject_id]
        validated = {k: row.get(k, "") for k in _SCHEMAS[self._schema]}
        writer.writerow(validated)
        f.flush()

    @property
    def path(self) -> pathlib.Path | None:
        return self._last_path
