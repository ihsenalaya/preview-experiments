"""Create, wait for, and delete Preview CRs for experiments."""
import json
import subprocess
import time
import uuid
from typing import Optional


def _kubectl(*args, check=True, capture=True) -> subprocess.CompletedProcess:
    cmd = ["kubectl", *args]
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
    )


def create(
    name: str,
    namespace: str,
    image: str,
    branch: str = "main",
    pr_number: int = 1,
    isolation_enabled: bool = True,
    extra_spec: Optional[dict] = None,
) -> str:
    """Create a Preview CR and return its name."""
    iso_val = "true" if isolation_enabled else "false"
    manifest = {
        "apiVersion": "platform.company.io/v1alpha1",
        "kind": "Preview",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "branch": branch,
            "prNumber": pr_number,
            "image": image,
            "ttl": "2h",
            "database": {
                "enabled": True,
                "version": "15",
                "isolationEnabled": isolation_enabled,
                "migration": {"enabled": True},
                "seed": {"enabled": True},
            },
            "testSuite": {
                "enabled": True,
                "smoke": {"enabled": True},
                "regression": {"enabled": True},
                "e2e": {"enabled": True},
            },
        },
    }
    if extra_spec:
        _deep_merge(manifest["spec"], extra_spec)

    proc = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=json.dumps(manifest),
        capture_output=True,
        text=True,
        check=True,
    )
    return name


def wait_until_phase(
    name: str,
    namespace: str,
    target_phases: list[str],
    timeout_s: int = 1200,
    poll_interval_s: int = 5,
) -> str:
    """Block until the Preview reaches one of target_phases. Returns final phase."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        phase = get_phase(name, namespace)
        if phase in target_phases:
            return phase
        time.sleep(poll_interval_s)
    raise TimeoutError(
        f"Preview {namespace}/{name} did not reach {target_phases} within {timeout_s}s"
    )


def get_phase(name: str, namespace: str) -> str:
    result = _kubectl(
        "get", "preview", name, "-n", namespace,
        "-o", "jsonpath={.status.phase}",
    )
    return result.stdout.strip() or "Unknown"


def get_status(name: str, namespace: str) -> dict:
    result = _kubectl(
        "get", "preview", name, "-n", namespace, "-o", "json",
    )
    return json.loads(result.stdout).get("status", {})


def get_tests_step(name: str, namespace: str) -> str:
    result = _kubectl(
        "get", "preview", name, "-n", namespace,
        "-o", "jsonpath={.status.tests.step}",
    )
    return result.stdout.strip()


def delete(name: str, namespace: str, wait: bool = True) -> None:
    _kubectl("delete", "preview", name, "-n", namespace, "--ignore-not-found=true")
    if wait:
        _kubectl(
            "wait", "--for=delete",
            f"preview/{name}", "-n", namespace,
            "--timeout=120s",
            check=False,
        )


def unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
