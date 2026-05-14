"""
RQ1 — Checkpoint isolation reduces test flakiness.

Protocol:
  For each subject in cfg.subjects.enabled:
    For each isolation value (True, False):
      Repeat N=30 times:
        1. Create a Preview CR with the given isolation setting.
        2. Wait until phase = Running or Failed (max 20 min).
        3. Collect test outcomes (smoke, regression, e2e pass/fail).
        4. Delete the Preview.
        5. Write one row per suite to test_outcomes CSV.

Hypothesis: failure_rate[isolation=False] > failure_rate[isolation=True].
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

EXPERIMENT = "flakiness"


def run_once(run_id: str, isolation: bool, cfg: dict,
             subject: dict, s_image: str, p_image: str) -> list[dict]:
    subject_id = subject["id"]
    pr_number = cfg["app"].get("pr_number_base", 9000) + (hash(run_id) % 900)
    name = factory.unique_name("fl")
    ns = factory.runtime_namespace(pr_number)

    use_subject = subject_id != "s1-flask-catalog"

    rows = []
    try:
        factory.create(
            name, "default", s_image, pr_number=pr_number,
            isolation_enabled=isolation,
            subject=subject if use_subject else None,
            subject_image=s_image if use_subject else None,
            probe_image=p_image if use_subject else None,
        )

        factory.wait_until_phase(
            name, "default",
            target_phases=["Running", "Failed"],
            timeout_s=cfg["experiments"]["flakiness"]["timeout_minutes"] * 60,
        )
        factory.wait_until_tests_done(
            name, "default",
            timeout_s=cfg["experiments"]["flakiness"]["timeout_minutes"] * 60,
        )

        status = factory.get_status(name, "default")
        tests = status.get("tests") or {}
        try:
            db_rows = collector.count_db_rows(ns, db_secret="postgres-credentials") or 0
        except Exception:
            db_rows = 0

        for suite in ("smoke", "regression", "e2e"):
            suite_status = tests.get(suite.capitalize()) or tests.get(suite) or {}
            rows.append({
                "run_id": run_id,
                "experiment": EXPERIMENT,
                "subject_id": subject_id,
                "preview_name": name,
                "isolation_enabled": str(isolation),
                "suite": suite,
                "test_name": suite,
                "outcome": suite_status.get("phase", "unknown"),
                "db_rows_before": db_rows,
                "db_rows_after": "",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            })

        step_rows = collector.collect_step_timings(ns, name)
        for s in step_rows:
            rows.append({
                "run_id": run_id,
                "experiment": EXPERIMENT,
                "subject_id": subject_id,
                "preview_name": name,
                "isolation_enabled": str(isolation),
                "suite": "step_timing",
                "test_name": s["step"],
                "outcome": s["outcome"],
                "db_rows_before": "",
                "db_rows_after": "",
                "timestamp_utc": s.get("start_utc", ""),
            })
    finally:
        factory.delete(name, "default")

    return rows


def main():
    cfg = cfg_module.load()
    exp_cfg = cfg["experiments"]["flakiness"]
    n = exp_cfg["n_runs"]
    isolation_values = exp_cfg["isolation_values"]
    subjects = cfg_module.load_enabled_subjects(cfg)

    with RunWriter("test_outcomes", EXPERIMENT) as writer:
        for subject in subjects:
            sid = subject["id"]
            s_image = cfg_module.subject_image(cfg, sid)
            p_image = cfg_module.probe_image(cfg)
            print(f"\n{'='*60}")
            print(f"Subject: {sid}")
            for isolation in isolation_values:
                print(f"\n=== Isolation={isolation} — {n} runs ===")
                for i in range(n):
                    run_id = f"{EXPERIMENT}-{sid}-iso{isolation}-{i:03d}-{uuid.uuid4().hex[:6]}"
                    print(f"  Run {i+1}/{n}  run_id={run_id}")
                    rows = run_once(run_id, isolation, cfg, subject, s_image, p_image)
                    for row in rows:
                        writer.write(row)
                    time.sleep(5)

    print(f"\nResults written to: {writer.path}")


if __name__ == "__main__":
    main()
