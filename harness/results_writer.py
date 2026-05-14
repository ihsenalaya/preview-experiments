"""Write experiment results to timestamped CSV files with strict schema validation."""
import csv
import pathlib
from datetime import datetime, timezone

_ROOT = pathlib.Path(__file__).parent.parent
_RESULTS = _ROOT / "results"
_RESULTS.mkdir(exist_ok=True)

_SCHEMAS = {
    "run_metrics": [
        "run_id", "experiment", "preview_name", "namespace",
        "isolation_enabled", "phase", "step", "step_duration_s",
        "total_reconcile_s", "requeue_count", "timestamp_utc",
    ],
    "test_outcomes": [
        "run_id", "experiment", "preview_name", "isolation_enabled",
        "suite", "test_name", "outcome", "db_rows_before",
        "db_rows_after", "timestamp_utc",
    ],
    "resource_usage": [
        "run_id", "experiment", "preview_name", "namespace",
        "timestamp_utc", "cpu_millicores", "mem_mib",
    ],
}


def _open_csv(schema_name: str, experiment: str):
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = _RESULTS / f"{experiment}_{schema_name}_{ts}.csv"
    f = open(path, "w", newline="")
    writer = csv.DictWriter(f, fieldnames=_SCHEMAS[schema_name], extrasaction="ignore")
    writer.writeheader()
    return f, writer, path


class RunWriter:
    """Context manager that writes rows to a single CSV file for one experiment run."""

    def __init__(self, schema_name: str, experiment: str):
        self._schema = schema_name
        self._experiment = experiment
        self._f = None
        self._writer = None
        self._path = None

    def __enter__(self):
        self._f, self._writer, self._path = _open_csv(self._schema, self._experiment)
        return self

    def __exit__(self, *_):
        if self._f:
            self._f.close()

    def write(self, row: dict) -> None:
        if self._writer is None:
            raise RuntimeError("Use RunWriter as a context manager")
        validated = {k: row.get(k, "") for k in _SCHEMAS[self._schema]}
        self._writer.writerow(validated)
        self._f.flush()

    @property
    def path(self) -> pathlib.Path:
        return self._path
