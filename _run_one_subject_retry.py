"""Wrapper that adds retry-logic to kubectl apply calls inside the harness.

Used to make T2.10 robust against transient AKS contention errors (e.g.
admission webhook timeout during operator restart, like the crash at Run 17/30
on 2026-05-17T19:51Z which killed T2.10 v1).

Monkey-patches subprocess.run so that any `kubectl apply` call that fails with
a non-zero exit retries up to 5 times with exponential backoff (2s, 4s, 8s,
16s, 30s capped). Other subprocess calls are passthrough.

Usage (drop-in replacement for _run_one_subject.py):
    SUBJECT=s2-listmonk EXPERIMENT=flakiness \\
        python3 _run_one_subject_retry.py
"""
import os
import runpy
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

_orig_run = subprocess.run


def retry_run(*args, **kwargs):
    cmd = args[0] if args else kwargs.get("args", [])
    is_kubectl_apply = (
        isinstance(cmd, (list, tuple))
        and len(cmd) >= 2
        and cmd[0] == "kubectl"
        and cmd[1] == "apply"
    )
    if not is_kubectl_apply:
        return _orig_run(*args, **kwargs)
    max_attempts = 5
    # Capture stdin so we can dump the manifest if all attempts fail
    manifest_input = kwargs.get("input", "")
    for attempt in range(1, max_attempts + 1):
        try:
            return _orig_run(*args, **kwargs)
        except subprocess.CalledProcessError as exc:
            stderr_excerpt = (exc.stderr or "")[:800].replace("\n", " | ")
            stdout_excerpt = (exc.stdout or "")[:400].replace("\n", " | ")
            if attempt == max_attempts:
                print(f"[retry-wrapper] kubectl apply FAILED after "
                      f"{max_attempts} attempts: rc={exc.returncode}\n"
                      f"  stderr: {stderr_excerpt}\n"
                      f"  stdout: {stdout_excerpt}\n"
                      f"  manifest_excerpt: {manifest_input[:600]}",
                      file=sys.stderr)
                raise
            backoff = min(2 ** attempt, 30)
            print(f"[retry-wrapper] kubectl apply rc={exc.returncode}, "
                  f"attempt {attempt}/{max_attempts}, sleep {backoff}s "
                  f"| stderr: {stderr_excerpt}",
                  file=sys.stderr)
            time.sleep(backoff)


subprocess.run = retry_run

# Same subject-filter hook as _run_one_subject.py
from harness import config as cfg_module

SUBJECT = os.environ["SUBJECT"]
EXPERIMENT = os.environ["EXPERIMENT"]
_orig_load = cfg_module.load


def filtered_load():
    cfg = _orig_load()
    cfg["subjects"]["enabled"] = [SUBJECT]
    return cfg


cfg_module.load = filtered_load

script = ROOT / f"exp_{EXPERIMENT}" / "run.py"
runpy.run_path(str(script), run_name="__main__")
