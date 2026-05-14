"""
RQ3 — Performance overhead of checkpoint isolation.

Protocol:
  Repeat N=20 times for each isolation value:
    1. Create Preview, wait for test suite to complete.
    2. Collect K8s Job start/completionTime for each step.
    3. Compute:
       - checkpoint_save_s: duration of suite-checkpoint-save job
       - restore_regression_s: duration of suite-restore-regression job
       - restore_e2e_s: duration of suite-restore-e2e job
       - pipeline_total_s: ReconcileEvent(TestFinished).OccurredAt - ReconcileEvent(TestStarted).OccurredAt
       - overhead_pct: (save + restore_regression + restore_e2e) / pipeline_total * 100

Hypothesis: overhead_pct < 15%.
"""
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

EXPERIMENT = "performance"


def run_once(run_id: str, isolation: bool, cfg: dict) -> list[dict]:
    image = cfg["app"]["image"]
    pr_number = cfg["app"].get("pr_number_base", 9000) + (hash(run_id) % 900)
    name = factory.unique_name("perf")
    ns = factory.runtime_namespace(pr_number)

    rows = []
    try:
        factory.create(name, "default", image, pr_number=pr_number, isolation_enabled=isolation)
        factory.wait_until_phase(
            name, "default",
            target_phases=["Running", "Failed"],
            timeout_s=cfg["experiments"]["performance"]["timeout_minutes"] * 60,
        )
        factory.wait_until_tests_done(
            name, "default",
            timeout_s=cfg["experiments"]["performance"]["timeout_minutes"] * 60,
        )

        raw_steps = collector.collect_step_timings(ns, name)
        step_timings = {s["step"]: s["duration_s"] for s in raw_steps}

        # pipeline_total_s: first job startTime → last job completionTime
        starts = [s["start_utc"] for s in raw_steps if s["start_utc"]]
        ends   = [s["end_utc"]   for s in raw_steps if s["end_utc"]]
        if starts and ends:
            from datetime import datetime as _dt
            t0 = min(_dt.fromisoformat(t.replace("Z", "+00:00")) for t in starts)
            t1 = max(_dt.fromisoformat(t.replace("Z", "+00:00")) for t in ends)
            pipeline_total_s = (t1 - t0).total_seconds()
        else:
            pipeline_total_s = None
        save_s = step_timings.get("saving")
        restore_reg_s = step_timings.get("restore-regression")
        restore_e2e_s = step_timings.get("restore-e2e")
        checkpoint_total_s = sum(
            v for v in [save_s, restore_reg_s, restore_e2e_s] if v is not None
        ) or None

        overhead_pct = (
            round(100 * checkpoint_total_s / pipeline_total_s, 2)
            if checkpoint_total_s and pipeline_total_s else None
        )

        for step, duration in step_timings.items():
            rows.append({
                "run_id": run_id,
                "experiment": EXPERIMENT,
                "preview_name": name,
                "namespace": ns,
                "isolation_enabled": str(isolation),
                "phase": "test_suite",
                "step": step,
                "step_duration_s": duration,
                "total_reconcile_s": pipeline_total_s,
                "requeue_count": "",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            })

        rows.append({
            "run_id": run_id,
            "experiment": EXPERIMENT,
            "preview_name": name,
            "namespace": ns,
            "isolation_enabled": str(isolation),
            "phase": "test_suite",
            "step": "checkpoint_total",
            "step_duration_s": checkpoint_total_s,
            "total_reconcile_s": pipeline_total_s,
            "requeue_count": overhead_pct,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        })

    finally:
        factory.delete(name, "default")

    return rows


def main():
    cfg = cfg_module.load()
    exp_cfg = cfg["experiments"]["performance"]
    n = exp_cfg["n_runs"]

    with RunWriter("run_metrics", EXPERIMENT) as writer:
        for isolation in [True, False]:
            print(f"\n=== Performance: isolation={isolation}, {n} runs ===")
            for i in range(n):
                run_id = f"{EXPERIMENT}-iso{isolation}-{i:03d}-{uuid.uuid4().hex[:6]}"
                print(f"  Run {i+1}/{n}  run_id={run_id}")
                rows = run_once(run_id, isolation, cfg)
                for row in rows:
                    writer.write(row)
                time.sleep(5)

    print(f"\nResults: {writer.path}")


if __name__ == "__main__":
    main()
