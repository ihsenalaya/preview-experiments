"""PHASE 7 — file-based experiment lock to prevent RQ5 from running concurrently
with other experiments.

Background
----------
RQ5 (exp_idempotence) deliberately kills the preview-operator pod with
`kubectl delete pods -l control-plane=controller-manager`. During the ~10-20 s
rollout, the validating-admission webhook is unreachable, which makes any
concurrent `kubectl apply preview` from another experiment crash with a
non-zero exit. This caused real incidents on 2026-05-16T14:43Z and again on
2026-05-17T07:12Z (documented in EXPERIMENT_METRICS.md and RQ5_IDEMPOTENCE.md).

Design
------
- A single shared lock file: ``runtime/experiment_lock.json`` (created on demand).
- Two modes:
    * ``exclusive`` (RQ5 / idempotence) — succeeds only if no other experiment
      holds any lock. Blocks all other acquisitions until released.
    * ``shared``    (flakiness, cross_pr, performance, bug_detection) — succeeds
      as long as no ``exclusive`` lock is held. Multiple shared holders can
      coexist (e.g. flak-S2 and perf-S3 running in parallel).
- Lock entries are JSON: ``{"pid": 1234, "experiment": "idempotence",
  "started_at": "2026-05-17T13:00Z", "argv": [...]}``.
- Stale-lock detection: if the recorded PID no longer exists, that entry is
  garbage-collected (covers the case where a previous run crashed without
  releasing).
- Filesystem-level atomicity is enforced with ``fcntl.flock`` on a sibling
  ``.lockfile`` (advisory lock); the JSON is the canonical state.

CLI usage from harness code::

    from harness.experiment_lock import acquire

    with acquire("idempotence", mode="exclusive"):
        run_experiment()   # safe — no other experiment can start

    with acquire("flakiness", mode="shared"):
        run_experiment()   # parallel with other shared holders OK

Force-override
--------------
An environment variable ``EXPERIMENT_LOCK_FORCE=1`` (or the CLI flag
``--force-rq5-alone`` consumed by the caller) bypasses the conflict check
when the user knows what they are doing (e.g. a leftover stale lock that
GC cannot detect because the PID was recycled).
"""
from __future__ import annotations

import contextlib
import errno
import json
import os
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
_RUNTIME = _ROOT / "runtime"
_LOCK_JSON = _RUNTIME / "experiment_lock.json"
_LOCK_FILE = _RUNTIME / ".lockfile"  # fcntl flock target


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class LockEntry:
    pid: int
    experiment: str
    started_at: str
    argv: list = field(default_factory=list)
    hostname: str = ""

    def is_alive(self) -> bool:
        """Return True if the process with this PID is still running."""
        if self.pid <= 0:
            return False
        try:
            os.kill(self.pid, 0)
            return True
        except OSError as exc:
            return exc.errno != errno.ESRCH


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class LockConflict(RuntimeError):
    """Raised when the requested lock cannot be acquired due to an active
    conflicting holder."""


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _read_state() -> dict:
    if not _LOCK_JSON.exists():
        return {"exclusive": None, "shared": []}
    try:
        return json.loads(_LOCK_JSON.read_text())
    except json.JSONDecodeError:
        return {"exclusive": None, "shared": []}


def _write_state(state: dict) -> None:
    _RUNTIME.mkdir(parents=True, exist_ok=True)
    _LOCK_JSON.write_text(json.dumps(state, indent=2))


def _gc_state(state: dict) -> dict:
    """Remove entries whose PID no longer exists. Returns the (mutated) state."""
    if state.get("exclusive"):
        e = LockEntry(**state["exclusive"])
        if not e.is_alive():
            state["exclusive"] = None
    state["shared"] = [e for e in state.get("shared", [])
                       if LockEntry(**e).is_alive()]
    return state


def _flocked_open():
    """Context manager that holds an fcntl.flock on _LOCK_FILE for the duration
    of the with-block. Provides cross-process serialization of state mutations."""
    import fcntl  # POSIX only — fine for Linux/macOS/WSL2

    _RUNTIME.mkdir(parents=True, exist_ok=True)

    @contextlib.contextmanager
    def _ctx():
        f = open(_LOCK_FILE, "w")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            finally:
                f.close()
    return _ctx()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _make_self_entry(experiment: str) -> dict:
    import socket
    return asdict(LockEntry(
        pid=os.getpid(),
        experiment=experiment,
        started_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        argv=list(sys.argv),
        hostname=socket.gethostname(),
    ))


def _format_conflict(state: dict, requested_mode: str, requested_exp: str) -> str:
    msg = [
        f"\nEXPERIMENT_LOCK conflict — cannot acquire {requested_mode!r} lock for "
        f"experiment {requested_exp!r}.",
        "",
    ]
    if state.get("exclusive"):
        e = state["exclusive"]
        msg.append(f"  EXCLUSIVE holder: experiment={e['experiment']!r} "
                   f"pid={e['pid']} started_at={e['started_at']}")
    for s in state.get("shared", []):
        msg.append(f"  SHARED holder:    experiment={s['experiment']!r} "
                   f"pid={s['pid']} started_at={s['started_at']}")
    msg.extend([
        "",
        "RQ5 (idempotence) restarts the preview operator and cannot run "
        "concurrently with other experiments.",
        "If you are sure no conflict exists (stale lock or recycled PID), set "
        "EXPERIMENT_LOCK_FORCE=1 to bypass.",
        f"Lock state file: {_LOCK_JSON.relative_to(_ROOT)}",
        "",
    ])
    return "\n".join(msg)


@contextlib.contextmanager
def acquire(experiment: str, mode: str = "shared"):
    """Acquire a lock for ``experiment`` and ``mode`` (``"exclusive"`` or
    ``"shared"``). Releases on exit. Raises ``LockConflict`` on failure unless
    ``EXPERIMENT_LOCK_FORCE`` is set."""
    if mode not in ("exclusive", "shared"):
        raise ValueError(f"mode must be 'exclusive' or 'shared', got {mode!r}")
    force = os.environ.get("EXPERIMENT_LOCK_FORCE") == "1"

    with _flocked_open():
        state = _gc_state(_read_state())
        # Conflict checks
        if mode == "exclusive":
            if state.get("exclusive") or state.get("shared"):
                if not force:
                    raise LockConflict(_format_conflict(state, mode, experiment))
        else:  # shared
            if state.get("exclusive"):
                if not force:
                    raise LockConflict(_format_conflict(state, mode, experiment))

        entry = _make_self_entry(experiment)
        if mode == "exclusive":
            state["exclusive"] = entry
        else:
            state.setdefault("shared", []).append(entry)
        _write_state(state)

    try:
        yield entry
    finally:
        with _flocked_open():
            state = _read_state()
            if mode == "exclusive":
                if state.get("exclusive") and state["exclusive"].get("pid") == os.getpid():
                    state["exclusive"] = None
            else:
                state["shared"] = [s for s in state.get("shared", [])
                                   if s.get("pid") != os.getpid()]
            _write_state(state)


def status() -> dict:
    """Return the current GC'd state of the lock (read-only). Useful for CLI tools."""
    with _flocked_open():
        return _gc_state(_read_state())


def clear_all() -> None:
    """Force-remove the lock state. Equivalent to deleting runtime/experiment_lock.json.
    Intended for manual recovery after operator-level mishaps; NEVER call from
    within an experiment."""
    with _flocked_open():
        _LOCK_JSON.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# CLI for inspection
# ---------------------------------------------------------------------------

def _cli() -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="Print current lock state.")
    sub.add_parser("clear", help="Remove the lock file (manual recovery).")
    args = p.parse_args()

    if args.cmd == "status":
        s = status()
        print(json.dumps(s, indent=2))
        return 0
    if args.cmd == "clear":
        clear_all()
        print(f"[ok] removed {_LOCK_JSON.relative_to(_ROOT)}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(_cli())
