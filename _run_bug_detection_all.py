"""
Wrapper that runs exp_bug_detection across all 5 subjects with resilient retry.

Caveat (per README §"Known limitations"): the fault-catalog mutations target
`testapp/app.py` (the S1 Flask source). For S2–S5 the mutated S1 image is
injected as their service image, which is architecturally inconsistent with
the subject's own adapter. Results on S2–S5 should be interpreted cautiously
(e.g. "exploratory cross-subject mutation injection").
"""
import os
import runpy
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from harness import config as cfg_module
from harness import preview_factory as factory

# --- Monkeypatch 1: enable all 5 subjects
_orig_load = cfg_module.load


def filtered_load():
    cfg = _orig_load()
    cfg["subjects"]["enabled"] = [
        "s1-flask-catalog",
        "s2-listmonk",
        "s3-healthchecks",
        "s4-umami",
        "s5-petclinic",
    ]
    return cfg


cfg_module.load = filtered_load

# --- Monkeypatch 2: retry kubectl apply on transient failures
_orig_create = factory.create


def resilient_create(*args, **kwargs):
    last_exc = None
    for attempt in range(5):
        try:
            return _orig_create(*args, **kwargs)
        except subprocess.CalledProcessError as exc:
            last_exc = exc
            stderr = (exc.stderr or "").lower()
            retryable = (
                "connection refused" in stderr
                or "no endpoints" in stderr
                or "context deadline exceeded" in stderr
                or "tls handshake" in stderr
                or "i/o timeout" in stderr
                or "could not find" in stderr
                or "service unavailable" in stderr
            )
            if attempt < 4 and (retryable or attempt == 0):
                wait = 5 * (attempt + 1)
                print(f"[retry] factory.create attempt {attempt+1} failed: {exc.returncode}; "
                      f"stderr head: {stderr[:200]!r}; sleeping {wait}s")
                time.sleep(wait)
                continue
            raise
    raise last_exc


factory.create = resilient_create


# --- Monkeypatch 3: resilient wait_until_tests_done
# The original raises CalledProcessError if the Preview disappears mid-poll
# (e.g. operator finalizes and deletes a Failed preview, or someone runs
# `kubectl delete preview`). Catch NotFound and treat as "Failed" outcome.
_orig_wait = factory.wait_until_tests_done


def resilient_wait(name, namespace, timeout_s=1200, poll_interval_s=5):
    """Poll Preview {namespace}/{name} until either status.tests.phase is terminal
    OR status.phase is terminal (Failed/Succeeded) at the top level. Handle the
    NotFound case (cleanup mid-poll) by returning "Failed"."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            # Read both fields in one kubectl call to avoid double-poll cost.
            result = subprocess.run(
                ["kubectl", "get", "preview", name, "-n", namespace, "-o",
                 "jsonpath={.status.phase}|{.status.tests.phase}"],
                capture_output=True, text=True, check=True,
            )
            top, tests = (result.stdout.strip().split("|", 1) + [""])[:2]
            if tests in ("Succeeded", "Failed"):
                return tests
            # Top-level Failed when tests never started = the preview died early.
            # The pipeline cannot reach tests; treat as Failed outcome for this run.
            if top == "Failed":
                print(f"[wait] Preview {namespace}/{name} status.phase=Failed without "
                      f"reaching tests; treating run as Failed.")
                return "Failed"
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").lower()
            if "not found" in stderr or "notfound" in stderr:
                print(f"[wait] Preview {namespace}/{name} disappeared mid-poll; "
                      f"treating as Failed.")
                return "Failed"
            # Other kubectl error: sleep and retry
            print(f"[wait] kubectl error: {stderr[:200]!r}; retrying after {poll_interval_s}s")
        time.sleep(poll_interval_s)
    print(f"[wait] timeout after {timeout_s}s on {namespace}/{name}; treating as Failed.")
    return "Failed"


factory.wait_until_tests_done = resilient_wait

runpy.run_path(str(ROOT / "exp_bug_detection" / "run.py"), run_name="__main__")
