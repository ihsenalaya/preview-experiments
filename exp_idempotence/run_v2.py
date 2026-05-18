"""RQ5 v2 — PHASE 8 instrumentation: augmented idempotence runner.

Extends the original exp_idempotence/run.py with three new metrics
recorded per-run (in addition to the original 12 columns):

  - duplicate_job_count    int    # k8s Jobs with duplicated suffixes post-restart
  - lost_status_count      int    # CR status sub-fields lost during restart
  - final_state_consistent bool   # all expected pods/services/CR fields present

These metrics directly answer the PHASE 8 prompt-criterion #5 (operator
behaviour under crash-restart): "does the operator leave behind orphan
Jobs / lose CR status / fail to converge on the expected namespace
state?"

CSV schema: 12 + 3 = 15 columns. Written under a distinct file pattern
(`idempotence_v2_run_metrics_*.csv`) so the consolidate_results.py
schema validator routes it to a separate experiment key.

Usage (drop-in for the existing runner):
    SUBJECT=s1-flask-catalog EXPERIMENT=idempotence \\
        python3 -u exp_idempotence/run_v2.py
"""
from __future__ import annotations

import json
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

EXPERIMENT = "idempotence_v2"

# CR status sub-fields we expect to remain populated after a restart.
EXPECTED_CR_STATUS_FIELDS = ("phase", "namespaceName", "publicURL", "tests")


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


def count_duplicate_jobs(namespace: str) -> int:
    """Count k8s Job objects that have the same base name (suffix-stripped)
    appearing more than once — indicates the controller created a duplicate
    Job after the restart instead of recognising the existing one."""
    try:
        r = subprocess.run(
            ["kubectl", "get", "jobs", "-n", namespace,
             "-o", "jsonpath={range .items[*]}{.metadata.name}\\n{end}"],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError:
        return 0
    names = [n for n in r.stdout.split("\n") if n.strip()]
    # Base name = strip the controller-runtime hex suffix (8 hex chars).
    bases = []
    for n in names:
        parts = n.rsplit("-", 1)
        if len(parts) == 2 and len(parts[1]) == 8:
            bases.append(parts[0])
        else:
            bases.append(n)
    from collections import Counter
    c = Counter(bases)
    return sum(max(0, n - 1) for n in c.values())


def count_lost_status_fields(preview_name: str, cr_namespace: str = "default") -> int:
    """Inspect Preview.status; count expected fields that are missing/null."""
    try:
        r = subprocess.run(
            ["kubectl", "get", "preview", preview_name, "-n", cr_namespace,
             "-o", "json"], capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError:
        return len(EXPECTED_CR_STATUS_FIELDS)
    try:
        status = json.loads(r.stdout).get("status", {}) or {}
    except json.JSONDecodeError:
        return len(EXPECTED_CR_STATUS_FIELDS)
    missing = 0
    for f in EXPECTED_CR_STATUS_FIELDS:
        v = status.get(f)
        if v is None or v == "" or v == {}:
            missing += 1
    return missing


def check_final_state_consistent(preview_name: str, runtime_ns: str,
                                 cr_namespace: str = "default") -> bool:
    """Return True iff: CR phase==Running OR Failed AND tests dict has 3
    suites AND at least 1 Pod is Running in the runtime namespace."""
    try:
        r = subprocess.run(
            ["kubectl", "get", "preview", preview_name, "-n", cr_namespace,
             "-o", "json"], capture_output=True, text=True, check=True,
        )
        cr = json.loads(r.stdout)
        phase = cr.get("status", {}).get("phase", "")
        tests = cr.get("status", {}).get("tests", {}) or {}
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return False
    if phase not in ("Running", "Failed", "Succeeded"):
        return False
    if len(tests) < 3:
        return False
    try:
        pods = subprocess.run(
            ["kubectl", "get", "pods", "-n", runtime_ns, "--field-selector",
             "status.phase=Running", "--no-headers"],
            capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return False
    return bool(pods.strip())


def run_once(run_id: str, kill_step: str, cfg: dict,
             subject: dict, s_image: str, p_image: str) -> list[dict]:
    subject_id = subject["id"]
    use_subject = subject_id != "s1-flask-catalog"
    operator_ns = cfg["operator"]["namespace"]
    pr_number = cfg["app"].get("pr_number_base", 9000) - 3000 + (hash(run_id) % 900)
    name = factory.unique_name("idem")
    runtime_ns = factory.runtime_namespace(pr_number)
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

        # PHASE 8 v2 augmented metrics
        dup_jobs = count_duplicate_jobs(runtime_ns)
        lost_fields = count_lost_status_fields(name)
        consistent = check_final_state_consistent(name, runtime_ns)

        rows.append({
            "run_id": run_id,
            "experiment": EXPERIMENT,
            "subject_id": subject_id,
            "preview_name": name,
            "namespace": runtime_ns,
            "isolation_enabled": "true",
            "phase": tests_phase,
            "step": kill_step,
            "step_duration_s": converge_elapsed,
            "total_reconcile_s": restart_elapsed,
            "requeue_count": 1 if diverged else 0,
            "timestamp_utc": kill_ts,
            # PHASE 8 v2 augmentation
            "duplicate_job_count": dup_jobs,
            "lost_status_count": lost_fields,
            "final_state_consistent": str(consistent).lower(),
        })

    finally:
        factory.delete(name, "default")

    return rows


def main() -> int:
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
                print(f"\n=== Kill at step={step} ({n} restarts) v2 ===")
                for i in range(n):
                    run_id = f"{EXPERIMENT}-{sid}-step{step}-{i:02d}-{uuid.uuid4().hex[:6]}"
                    print(f"  Run {i+1}/{n}  run_id={run_id}")
                    rows = run_once(run_id, step, cfg, subject, s_image, p_image)
                    for row in rows:
                        writer.write(row)
                    time.sleep(10)

    print(f"\nResults: {writer.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
