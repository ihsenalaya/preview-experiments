"""
Wrapper that runs a single experiment for a single subject.

Usage:
    SUBJECT=s2-listmonk EXPERIMENT=flakiness python3 _run_one_subject.py

Monkeypatches harness.config.load() so cfg.subjects.enabled becomes [SUBJECT].
Then invokes exp_<EXPERIMENT>/run.py as __main__.
"""
import os
import runpy
import sys
from pathlib import Path

SUBJECT = os.environ["SUBJECT"]
EXPERIMENT = os.environ["EXPERIMENT"]

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from harness import config as cfg_module

_orig_load = cfg_module.load


def filtered_load():
    cfg = _orig_load()
    cfg["subjects"]["enabled"] = [SUBJECT]
    return cfg


cfg_module.load = filtered_load

script = ROOT / f"exp_{EXPERIMENT}" / "run.py"
runpy.run_path(str(script), run_name="__main__")
