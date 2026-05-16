"""
Wrapper that runs exp_bug_detection for [s1-flask-catalog, s2-listmonk] only.
Monkeypatches cfg.subjects.enabled to force the subject list.
"""
import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from harness import config as cfg_module

_orig_load = cfg_module.load


def filtered_load():
    cfg = _orig_load()
    cfg["subjects"]["enabled"] = ["s1-flask-catalog", "s2-listmonk"]
    return cfg


cfg_module.load = filtered_load

runpy.run_path(str(ROOT / "exp_bug_detection" / "run.py"), run_name="__main__")
