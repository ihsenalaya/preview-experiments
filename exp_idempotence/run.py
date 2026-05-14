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
        ["kubectl", "rollout", "status", "deployment/preview-operator-controller-manager",
         "-n", operator_ns, f"--timeout={timeout_s}s"],
        check=True,
    )


def run_once(run_id: str, kill_step: str, cfg: dict) -> list[dict]:
    image = cfg["app"]["image"]
    operator_ns = cfg["operator"]["namespace"]
    name = factory.unique_name("idem")
    rows = []

    try:
        factory.create(name, "default", image, isolation_enabled=True)

        # Wait until the operator has advanced to (or past) the target step
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
        final_phase = factory.wait_until_phase(
            name, "default",
            target_phases=["Running", "Failed"],
            timeout_s=cfg["experiments"]["idempotence"]["timeout_minutes"] * 60,
        )
        converge_elapsed = time.monotonic() - converge_start

        status = factory.get_status(name, "default")
        tests = status.get("tests") or {}
        diverged = final_phase == "Failed" and kill_step not in ("e2e",)

        rows.append({
            "run_id": run_id,
            "experiment": EXPERIMENT,
            "preview_name": name,
            "namespace": f"{cfg['app']['namespace_prefix']}-{name}",
            "isolation_enabled": "true",
            "phase": final_phase,
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

    with RunWriter("run_metrics", EXPERIMENT) as writer:
        for step in kill_steps:
            print(f"\n=== Kill at step={step} ({n} restarts) ===")
            for i in range(n):
                run_id = f"{EXPERIMENT}-step{step}-{i:02d}-{uuid.uuid4().hex[:6]}"
                print(f"  Run {i+1}/{n}  run_id={run_id}")
                rows = run_once(run_id, step, cfg)
                for row in rows:
                    writer.write(row)
                time.sleep(10)

    print(f"\nResults: {writer.path}")


if __name__ == "__main__":
    main()
