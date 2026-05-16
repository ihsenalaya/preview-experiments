"""
Wrapper that runs exp_bug_detection for [s1-flask-catalog, s2-listmonk] only.
Monkeypatches cfg.subjects.enabled to force the subject list AND wraps the
fragile kubectl-apply calls in factory.create with a retry loop so transient
kubectl/webhook hiccups don't kill the whole experiment.
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

# --- Monkeypatch 1: filter subjects to S1 + S2 only
_orig_load = cfg_module.load


def filtered_load():
    cfg = _orig_load()
    cfg["subjects"]["enabled"] = ["s1-flask-catalog", "s2-listmonk"]
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
            # Webhook unreachable (operator pod restarted) or transient API issues
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

runpy.run_path(str(ROOT / "exp_bug_detection" / "run.py"), run_name="__main__")
