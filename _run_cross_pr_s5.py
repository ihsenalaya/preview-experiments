"""
Wrapper: run exp_cross_pr for s5-petclinic only.
Monkeypatches cfg.subjects.enabled to [s5-petclinic].
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
    cfg["subjects"]["enabled"] = ["s5-petclinic"]
    return cfg


cfg_module.load = filtered_load

runpy.run_path(str(ROOT / "exp_cross_pr" / "run.py"), run_name="__main__")
