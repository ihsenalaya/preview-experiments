"""Collect experiment metrics from Kubernetes API without operator changes."""
import json
import subprocess
from datetime import datetime, timezone
from typing import Optional


def _kubectl(*args, check=True) -> str:
    result = subprocess.run(
        ["kubectl", *args], capture_output=True, text=True, check=check,
    )
    return result.stdout.strip()


def _kubectl_json(*args) -> dict | list:
    return json.loads(_kubectl(*args, "-o", "json"))


# ---------------------------------------------------------------------------
# ReconcileEvents
# ---------------------------------------------------------------------------

def list_reconcile_events(preview_name: str, namespace: str) -> list[dict]:
    """Return all ReconcileEvent CRs for a given Preview, sorted by OccurredAt."""
    raw = _kubectl_json(
        "get", "reconcileevent", "-n", namespace,
        "--field-selector", f"spec.previewRef.name={preview_name}",
    )
    items = raw.get("items", [])
    return sorted(items, key=lambda e: e.get("spec", {}).get("occurredAt", ""))


def reconcile_event_timestamp(event: dict) -> Optional[datetime]:
    ts = event.get("spec", {}).get("occurredAt")
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Job timing (step-level)
# ---------------------------------------------------------------------------

def list_jobs(namespace: str, label_selector: str = "") -> list[dict]:
    args = ["get", "jobs", "-n", namespace, "-o", "json"]
    if label_selector:
        args += ["-l", label_selector]
    raw = _kubectl_json(*args)
    return raw.get("items", [])


def job_duration_s(job: dict) -> Optional[float]:
    """Return job wall-clock duration in seconds from K8s Job status."""
    start = job.get("status", {}).get("startTime")
    end = job.get("status", {}).get("completionTime")
    if not start or not end:
        return None
    t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
    t1 = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return (t1 - t0).total_seconds()


def collect_step_timings(namespace: str, preview_name: str) -> list[dict]:
    """
    Return per-step timings derived from K8s Job start/completionTime.
    Each dict: {step, job_name, start_utc, end_utc, duration_s, outcome}
    """
    jobs = list_jobs(namespace, label_selector=f"platform.company.io/preview={preview_name}")
    rows = []
    for job in jobs:
        name = job["metadata"]["name"]
        status = job.get("status", {})
        start = status.get("startTime")
        end = status.get("completionTime")
        succeeded = status.get("succeeded", 0) > 0
        failed = any(
            c.get("type") == "Failed" and c.get("status") == "True"
            for c in status.get("conditions", [])
        )
        rows.append({
            "step": _job_name_to_step(name),
            "job_name": name,
            "start_utc": start,
            "end_utc": end,
            "duration_s": job_duration_s(job),
            "outcome": "succeeded" if succeeded else ("failed" if failed else "running"),
        })
    return sorted(rows, key=lambda r: r["start_utc"] or "")


def _job_name_to_step(job_name: str) -> str:
    mapping = {
        "smoke-tests": "smoke",
        "suite-checkpoint-save": "saving",
        "suite-restore-regression": "restore-regression",
        "regression-tests": "regression",
        "suite-restore-e2e": "restore-e2e",
        "e2e-tests": "e2e",
        "microcks-contract-tests": "contract",
        "microcks-import": "import-spec",
        "migration-tests": "migration",
    }
    return mapping.get(job_name, job_name)


# ---------------------------------------------------------------------------
# DB row count (external psql job)
# ---------------------------------------------------------------------------

def count_db_rows(namespace: str, db_secret: str = "postgres-secret") -> Optional[int]:
    """
    Launch a one-shot pod to COUNT(*) rows across all tables and return total.
    Assumption: secret named db_secret contains POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB.
    """
    pod_name = f"rowcount-{_short_uid()}"
    query = (
        "SELECT SUM(cnt) FROM ("
        "SELECT COUNT(*) AS cnt FROM products UNION ALL "
        "SELECT COUNT(*) FROM categories UNION ALL "
        "SELECT COUNT(*) FROM reviews UNION ALL "
        "SELECT COUNT(*) FROM orders) t;"
    )
    manifest = json.dumps({
        "apiVersion": "v1", "kind": "Pod",
        "metadata": {"name": pod_name, "namespace": namespace},
        "spec": {
            "restartPolicy": "Never",
            "containers": [{
                "name": "count",
                "image": "postgres:15-alpine",
                "command": ["sh", "-c", f'psql -h postgres -U "$POSTGRES_USER" "$POSTGRES_DB" -At -c "{query}"'],
                "envFrom": [{"secretRef": {"name": db_secret}}],
                "env": [{"name": "PGPASSWORD", "valueFrom": {"secretKeyRef": {"name": db_secret, "key": "POSTGRES_PASSWORD"}}}],
            }],
        },
    })
    subprocess.run(["kubectl", "apply", "-f", "-"], input=manifest, capture_output=True, text=True, check=True)
    import time
    for _ in range(30):
        phase = _kubectl("get", "pod", pod_name, "-n", namespace, "-o", "jsonpath={.status.phase}", check=False)
        if phase == "Succeeded":
            logs = _kubectl("logs", pod_name, "-n", namespace)
            subprocess.run(["kubectl", "delete", "pod", pod_name, "-n", namespace, "--ignore-not-found=true"], capture_output=True)
            try:
                return int(logs.strip())
            except ValueError:
                return None
        if phase == "Failed":
            break
        time.sleep(2)
    subprocess.run(["kubectl", "delete", "pod", pod_name, "-n", namespace, "--ignore-not-found=true"], capture_output=True)
    return None


# ---------------------------------------------------------------------------
# Resource usage (kubectl top)
# ---------------------------------------------------------------------------

def collect_resource_usage(namespace: str) -> list[dict]:
    """Return CPU/RAM per pod in namespace via kubectl top (requires metrics-server)."""
    raw = _kubectl("top", "pods", "-n", namespace, "--no-headers", check=False)
    rows = []
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            rows.append({
                "pod": parts[0],
                "cpu_raw": parts[1],
                "mem_raw": parts[2],
                "cpu_millicores": _parse_cpu(parts[1]),
                "mem_mib": _parse_mem(parts[2]),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            })
    return rows


def _parse_cpu(s: str) -> int:
    if s.endswith("m"):
        return int(s[:-1])
    return int(s) * 1000


def _parse_mem(s: str) -> float:
    if s.endswith("Mi"):
        return float(s[:-2])
    if s.endswith("Gi"):
        return float(s[:-2]) * 1024
    if s.endswith("Ki"):
        return float(s[:-2]) / 1024
    return float(s)


def _short_uid() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Requeue count (operator logs)
# ---------------------------------------------------------------------------

def count_requeues(preview_name: str, operator_namespace: str = "preview-operator-system") -> int:
    """Count reconcile loops for a given preview by parsing operator pod logs."""
    pods_raw = _kubectl(
        "get", "pods", "-n", operator_namespace,
        "-l", "control-plane=controller-manager",
        "-o", "jsonpath={.items[*].metadata.name}",
    )
    total = 0
    for pod in pods_raw.split():
        logs = _kubectl("logs", pod, "-n", operator_namespace, "--since=1h", check=False)
        total += logs.count(f'"name":"{preview_name}"')
    return total
