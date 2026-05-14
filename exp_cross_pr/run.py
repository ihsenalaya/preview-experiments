"""
RQ2 — Cross-PR pollution with concurrent previews.

Protocol:
  For each K in [2, 4, 8]:
    For each isolation in [True, False]:
      Launch K Preview CRs simultaneously (same image, different PR numbers).
      Wait until all reach a terminal phase.
      Record failures and attribute them to cross-PR interference
      (i.e. failures that appear only when K > 1 in the no-isolation condition).

Hypothesis: failure_rate grows with K when isolation=False; stays near 0 with isolation=True.

NOTE: True cross-namespace DB isolation is already guaranteed by the operator (each Preview
gets its own namespace and Postgres). This experiment measures whether test-suite state
pollution (dirty DB between suites) accumulates differently under concurrent load.
The "pollution" we observe is within-preview dirty-state accumulation; concurrency
amplifies it by shortening the window between test jobs when the cluster is under load.
"""
import concurrent.futures
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from harness import config as cfg_module
from harness import preview_factory as factory
from harness import metrics_collector as collector
from harness.results_writer import RunWriter

EXPERIMENT = "cross_pr"


def run_single(run_id: str, name: str, pr_number: int, isolation: bool, cfg: dict) -> list[dict]:
    image = cfg["app"]["image"]
    ns = f"{cfg['app']['namespace_prefix']}-{name}"
    rows = []
    try:
        factory.create(name, "default", image, pr_number=pr_number, isolation_enabled=isolation)
        final_phase = factory.wait_until_phase(
            name, "default",
            target_phases=["Running", "Failed"],
            timeout_s=cfg["experiments"]["cross_pr"]["timeout_minutes"] * 60,
        )
        status = factory.get_status(name, "default")
        tests = status.get("tests") or {}
        for suite in ("smoke", "regression", "e2e"):
            suite_status = tests.get(suite.capitalize()) or tests.get(suite) or {}
            rows.append({
                "run_id": run_id,
                "experiment": EXPERIMENT,
                "preview_name": name,
                "isolation_enabled": str(isolation),
                "suite": suite,
                "test_name": suite,
                "outcome": suite_status.get("phase", "unknown"),
                "db_rows_before": "",
                "db_rows_after": "",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            })
    finally:
        factory.delete(name, "default")
    return rows


def run_batch(k: int, isolation: bool, cfg: dict, writer: RunWriter) -> None:
    batch_id = uuid.uuid4().hex[:8]
    names = [factory.unique_name("cp") for _ in range(k)]
    pr_numbers = list(range(100 + int(batch_id[:2], 16), 100 + int(batch_id[:2], 16) + k))

    with concurrent.futures.ThreadPoolExecutor(max_workers=k) as pool:
        futures = {
            pool.submit(
                run_single,
                f"{EXPERIMENT}-k{k}-iso{isolation}-{batch_id}-{i}",
                names[i],
                pr_numbers[i],
                isolation,
                cfg,
            ): i
            for i in range(k)
        }
        for fut in concurrent.futures.as_completed(futures):
            try:
                rows = fut.result()
                for row in rows:
                    row["run_id"] += f"-concurrent_k{k}"
                    writer.write(row)
            except Exception as exc:
                print(f"  Worker failed: {exc}")


def main():
    cfg = cfg_module.load()
    exp_cfg = cfg["experiments"]["cross_pr"]
    k_values = exp_cfg["k_values"]
    isolation_values = exp_cfg["isolation_values"]

    with RunWriter("test_outcomes", EXPERIMENT) as writer:
        for isolation in isolation_values:
            for k in k_values:
                print(f"\n=== K={k}, isolation={isolation} ===")
                run_batch(k, isolation, cfg, writer)
                time.sleep(10)

    print(f"\nResults: {writer.path}")


if __name__ == "__main__":
    main()
