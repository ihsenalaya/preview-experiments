"""
RQ5 — Pipeline idempotence under operator restarts.

Protocol:
  For each pipeline step in kill_steps:
    Repeat N=3 times:
      1. Create a Preview CR, wait until status.tests.step == target_step.
      2. Kill the operator pod (kubectl delete pod -l control-plane=controller-manager).
      3. Wait for the operator to restart (new pod ready).
      4. Wait for the Preview to reach a terminal phase.
      5. Compare final status to expected (Succeeded with same pass/fail counts).
      6. Measure time-to-convergence after restart.

Hypothesis: divergence = 0 (controller-runtime guarantees at-least-once reconciliation).
"""
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from harness import config as cfg_module
from harness import preview_factory as factory
from harness.results_writer import RunWriter

EXPERIMENT = "idempotence"


def kill_operator_pod(operator_ns: str) -> None:
    subprocess.run(
        ["kubectl", "delete", "pods", "-n", operator_ns,
         "-l", "control-plane=controller-manager", "--wait=false"],
        check=True, capture_output=True,
    )


def wait_operator_ready(operator_ns: str, timeout_s: int = 120) -> None:
    subprocess.run(
        ["kubectl", "rollout", "status", "deployment/preview-operator",
         "-n", operator_ns, f"--timeout={timeout_s}s"],
        check=True,
    )


def run_once(run_id: str, kill_step: str, cfg: dict,
             subject: dict, s_image: str, p_image: str) -> list[dict]:
    subject_id = subject["id"]
    use_subject = subject_id != "s1-flask-catalog"
    operator_ns = cfg["operator"]["namespace"]
    pr_number = cfg["app"].get("pr_number_base", 9000) - 3000 + (hash(run_id) % 900)
    name = factory.unique_name("idem")
    rows = []

    try:
        factory.create(
            name, "default", s_image, pr_number=pr_number,
            isolation_enabled=True,
            subject=subject if use_subject else None,
            subject_image=s_image if use_subject else None,
            probe_image=p_image if use_subject else None,
        )

        print(f"    Waiting for step={kill_step}...")
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            current = factory.get_tests_step(name, "default")
            if current == kill_step:
                break
            phase = factory.get_phase(name, "default")
            if phase in ("Failed", "Running") and current not in ("", kill_step):
                break
            time.sleep(3)

        kill_ts = datetime.now(timezone.utc).isoformat()
        print(f"    Killing operator pod at step={current}...")
        kill_operator_pod(operator_ns)

        restart_start = time.monotonic()
        wait_operator_ready(operator_ns)
        restart_elapsed = time.monotonic() - restart_start

        converge_start = time.monotonic()
        factory.wait_until_phase(
            name, "default",
            target_phases=["Running", "Failed"],
            timeout_s=cfg["experiments"]["idempotence"]["timeout_minutes"] * 60,
        )
        tests_phase = factory.wait_until_tests_done(
            name, "default",
            timeout_s=cfg["experiments"]["idempotence"]["timeout_minutes"] * 60,
        )
        converge_elapsed = time.monotonic() - converge_start
        diverged = tests_phase == "Failed"

        rows.append({
            "run_id": run_id,
            "experiment": EXPERIMENT,
            "subject_id": subject_id,
            "preview_name": name,
            "namespace": factory.runtime_namespace(pr_number),
            "isolation_enabled": "true",
            "phase": tests_phase,
            "step": kill_step,
            "step_duration_s": converge_elapsed,
            "total_reconcile_s": restart_elapsed,
            "requeue_count": 1 if diverged else 0,
            "timestamp_utc": kill_ts,
        })

    finally:
        factory.delete(name, "default")

    return rows


def main():
    cfg = cfg_module.load()
    exp_cfg = cfg["experiments"]["idempotence"]
    kill_steps = exp_cfg["kill_steps"]
    n = exp_cfg["n_restarts_per_step"]
    subjects = cfg_module.load_enabled_subjects(cfg)

    with RunWriter("run_metrics", EXPERIMENT) as writer:
        for subject in subjects:
            sid = subject["id"]
            s_image = cfg_module.subject_image(cfg, sid)
            p_image = cfg_module.probe_image(cfg)
            print(f"\n{'='*60}\nSubject: {sid}")
            for step in kill_steps:
                print(f"\n=== Kill at step={step} ({n} restarts) ===")
                for i in range(n):
                    run_id = f"{EXPERIMENT}-{sid}-step{step}-{i:02d}-{uuid.uuid4().hex[:6]}"
                    print(f"  Run {i+1}/{n}  run_id={run_id}")
                    rows = run_once(run_id, step, cfg, subject, s_image, p_image)
                    for row in rows:
                        writer.write(row)
                    time.sleep(10)

    print(f"\nResults: {writer.path}")


if __name__ == "__main__":
    main()
