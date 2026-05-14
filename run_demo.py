"""
Quick demo: create 1 Preview for a given subject, watch it run, print results.

Usage:
  python run_demo.py                      # uses s1-flask-catalog (default)
  python run_demo.py s2-listmonk          # uses subject s2-listmonk
  EXP_APP_IMAGE=... python run_demo.py    # override app image for s1

Isolation can be toggled:
  ISOLATION=false python run_demo.py
"""
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from harness import config as cfg_module
from harness import preview_factory as factory
from harness import metrics_collector as collector

cfg = cfg_module.load()

# Subject selection: first CLI arg, or default to s1
subject_id = sys.argv[1] if len(sys.argv) > 1 else "s1-flask-catalog"
subject = cfg_module.load_subject(subject_id)
s_image = cfg_module.subject_image(cfg, subject_id)
p_image = cfg_module.probe_image(cfg)
use_subject = subject_id != "s1-flask-catalog"

CR_NS  = cfg["app"].get("cr_namespace", "default")
PR_NUM = cfg["app"].get("pr_number_base", 9000) + (uuid.uuid4().int % 100)
NAME   = f"exp-demo-{uuid.uuid4().hex[:6]}"
ISOLATION = os.environ.get("ISOLATION", "true").lower() not in ("false", "0", "no")

print(f"""
=== DEMO RUN ===
  Subject    : {subject_id}
  Preview CR : {NAME} (namespace: {CR_NS})
  PR number  : {PR_NUM}
  Runtime NS : {factory.runtime_namespace(PR_NUM)}
  Image      : {s_image}
  Probe      : {p_image or '(none)'}
  Isolation  : {ISOLATION}
""")


def elapsed(t):
    return f"{time.monotonic()-t:5.0f}s"


t0 = time.monotonic()
factory.create(
    NAME, CR_NS, s_image, branch="main", pr_number=PR_NUM,
    isolation_enabled=ISOLATION,
    subject=subject if use_subject else None,
    subject_image=s_image if use_subject else None,
    probe_image=p_image if use_subject else None,
)
print(f"[{elapsed(t0)}] Preview CR created.")

last_label = ""
deadline = time.monotonic() + 1800
while time.monotonic() < deadline:
    phase = factory.get_phase(NAME, CR_NS)
    step  = factory.get_tests_step(NAME, CR_NS)
    label = f"phase={phase}" + (f"  step={step}" if step else "")
    if label != last_label:
        print(f"[{elapsed(t0)}] {label}")
        last_label = label
    if phase in ("Succeeded", "Failed"):
        break
    time.sleep(6)

total = time.monotonic() - t0

ns = factory.runtime_namespace(PR_NUM)
status = factory.get_status(NAME, CR_NS)
tests  = status.get("tests") or {}

print(f"\n=== RESULTS (total={total:.0f}s) ===")
for suite in ("smoke", "regression", "e2e"):
    s = tests.get(suite.capitalize()) or tests.get(suite) or {}
    if s:
        print(f"  {suite:12s}: phase={s.get('phase','?'):12s}  passed={s.get('passed','-')}  failed={s.get('failed','-')}")

print("\n--- Step timings (from K8s Jobs) ---")
timings = collector.collect_step_timings(ns, NAME)
for t in timings:
    dur = f"{t['duration_s']:.1f}s" if t['duration_s'] is not None else "running"
    print(f"  {t['step']:25s}: {t['outcome']:10s}  {dur}")

print("\n--- Resource usage ---")
usage = collector.collect_resource_usage(ns)
for u in usage:
    print(f"  {u['pod']:40s}: cpu={u['cpu_millicores']}m  mem={u['mem_mib']:.0f}Mi")

print(f"\nDeleting Preview {NAME}...")
factory.delete(NAME, CR_NS)
print("Done.")
