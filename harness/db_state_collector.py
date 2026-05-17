"""PHASE 3 — read-only PostgreSQL state collector.

Captures the state of every user table in a Preview's PostgreSQL pod at a given
pipeline step. Used to verify that the operator's checkpoint/restore mechanism
reproduces the saved state exactly: ``snapshot_hash_global`` at
``post_checkpoint`` MUST equal ``snapshot_hash_global`` at
``post_restore_regression`` and ``post_restore_e2e``.

Design
------
- Connects to the postgres pod via ``kubectl exec`` — no port-forward needed,
  no app dependency.
- For each user-schema table (not in pg_catalog/information_schema):
    - row_count  via ``SELECT count(*)``
    - content_hash via ``SELECT md5(string_agg((t)::text, E'\\n' ORDER BY (t)::text)) FROM <table> t``
      → deterministic across runs because all columns are included AND the order
      is stable (lexicographic on the full row representation).
- snapshot_hash_global = sha256 of concatenated "schema.table:content_hash" pairs
  sorted by qualified name.
- Output rows fit the ``db_state_metrics`` schema (see harness/results_writer.py).

Constraints (from prompt.txt PHASE 3)
-------------------------------------
- Read-only (no writes, no schema changes, no DROP/CREATE).
- excluded_columns: documented per table when a volatile column prevents stable
  hashing (e.g. ``last_login`` timestamps updated by the SUT runtime even after
  restore). Default: none excluded — let the user opt-in to per-SUT exclusion
  via a config file (deferred to v2).
- Deterministic: ``ORDER BY (t)::text`` is stable as long as the row tuple text
  representation is stable across runs (it is, for non-binary types).
- If a table has no rows, content_hash = md5("") = "d41d8cd98f00b204e9800998ecf8427e".
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

# 9 step labels from prompt.txt PHASE 3
PIPELINE_STEPS = (
    "post_migration",
    "post_checkpoint",
    "post_smoke",
    "pre_restore_regression",
    "post_restore_regression",
    "post_regression",
    "pre_restore_e2e",
    "post_restore_e2e",
    "post_e2e",
)

# Schemas to ignore when enumerating tables
SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "pg_toast")

# Default excluded columns per (subject, table) — placeholder for v2 ; v1 excludes nothing
DEFAULT_EXCLUDED_COLUMNS: dict[tuple[str, str], list[str]] = {}


# ---------------------------------------------------------------------------
# Connection — via kubectl exec
# ---------------------------------------------------------------------------

@dataclass
class PostgresTarget:
    namespace: str
    pod: str
    user: str
    database: str
    password_env: str = "POSTGRES_PASSWORD"  # name of env var inside the pod


def discover_postgres_in_namespace(namespace: str) -> PostgresTarget:
    """Best-effort discovery of the postgres pod + credentials in a Preview's
    runtime namespace. Reads pod label app=postgres and the
    postgres-credentials Secret created by the operator."""
    pod_p = subprocess.run(
        ["kubectl", "-n", namespace, "get", "pod", "-l", "app=postgres",
         "-o", "jsonpath={.items[0].metadata.name}"],
        check=True, capture_output=True, text=True,
    )
    pod = pod_p.stdout.strip()
    if not pod:
        raise RuntimeError(f"no postgres pod found in namespace {namespace}")

    sec_p = subprocess.run(
        ["kubectl", "-n", namespace, "get", "secret", "postgres-credentials",
         "-o", "json"],
        check=True, capture_output=True, text=True,
    )
    sec = json.loads(sec_p.stdout)["data"]
    import base64
    user = base64.b64decode(sec.get("POSTGRES_USER", "")).decode().strip()
    db = base64.b64decode(sec.get("POSTGRES_DB", "")).decode().strip()
    return PostgresTarget(namespace=namespace, pod=pod, user=user or "postgres",
                          database=db or "postgres")


def _kubectl_psql(tgt: PostgresTarget, sql: str) -> str:
    """Run a SQL statement inside the postgres pod via ``kubectl exec`` and
    return the raw stdout (pipe-separated, no header)."""
    # `-At` means unaligned, no header → cleaner parsing.
    # `-F '|'` separator — avoid \\t because bash double-quotes don't interpret
    # backslash escapes, leading psql to use literal "\t" (2 chars) as the
    # separator which then breaks Python's str.split("\t").
    cmd = [
        "kubectl", "-n", tgt.namespace, "exec", tgt.pod, "--",
        "sh", "-c",
        f'PGPASSWORD="${tgt.password_env}" psql -U "{tgt.user}" -d "{tgt.database}" '
        f"-At -F '|' -c {_shquote(sql)}",
    ]
    r = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)
    return r.stdout


def _shquote(s: str) -> str:
    # Single-quote safe for sh -c
    return "'" + s.replace("'", "'\"'\"'") + "'"


# ---------------------------------------------------------------------------
# Enumeration + hashing
# ---------------------------------------------------------------------------

def list_user_tables(tgt: PostgresTarget) -> list[tuple[str, str]]:
    """Return [(schema, table)] for user-schema tables. Excludes system schemas."""
    sys_filter = ", ".join(f"'{s}'" for s in SYSTEM_SCHEMAS)
    sql = (f"SELECT schemaname, tablename FROM pg_tables "
           f"WHERE schemaname NOT IN ({sys_filter}) "
           f"ORDER BY schemaname, tablename")
    out = _kubectl_psql(tgt, sql)
    rows = []
    for line in out.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|")
        if len(parts) >= 2:
            rows.append((parts[0], parts[1]))
    return rows


def hash_table(tgt: PostgresTarget, schema: str, table: str) -> tuple[int, str, str]:
    """Return (row_count, content_hash_md5, excluded_columns_str) for a single table."""
    qname = f'"{schema}"."{table}"'
    excluded = DEFAULT_EXCLUDED_COLUMNS.get((tgt.database, table), [])

    # row_count
    rc_out = _kubectl_psql(tgt, f"SELECT count(*) FROM {qname}")
    try:
        row_count = int(rc_out.strip())
    except ValueError:
        row_count = -1

    # content hash — entire row tuple cast to text, ORDER BY full text repr
    # Empty table: md5 of empty string
    if row_count == 0:
        return (0, hashlib.md5(b"").hexdigest(), ",".join(excluded))

    sql = (f"SELECT md5(coalesce(string_agg((t)::text, E'\\n' ORDER BY (t)::text), '')) "
           f"FROM {qname} t")
    h_out = _kubectl_psql(tgt, sql)
    content_hash = h_out.strip() or hashlib.md5(b"").hexdigest()
    return (row_count, content_hash, ",".join(excluded))


def snapshot(
    *,
    tgt: PostgresTarget,
    run_id: str,
    subject_id: str,
    preview_name: str,
    isolation_enabled: bool,
    step: str,
    timestamp: str | None = None,
) -> list[dict]:
    """Capture the full DB state of ``tgt`` at this moment. Returns rows for the
    ``db_state_metrics`` schema: one per (schema, table) plus a 'snapshot_hash_global'
    summary row with table_name='*' for convenience."""
    if step not in PIPELINE_STEPS:
        # Allow free-form step labels but warn
        print(f"[warn] step {step!r} not in PIPELINE_STEPS — proceeding anyway",
              file=sys.stderr)

    tables = list_user_tables(tgt)
    if not tables:
        print(f"[warn] no user tables found in {tgt.namespace}/{tgt.database}",
              file=sys.stderr)

    ts = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    iso_str = "True" if isolation_enabled else "False"

    rows = []
    per_table = []  # for global hash
    for schema, table in tables:
        try:
            row_count, content_hash, excluded = hash_table(tgt, schema, table)
        except subprocess.CalledProcessError as exc:
            print(f"[warn] hash failed for {schema}.{table}: {exc.stderr[:120]}",
                  file=sys.stderr)
            row_count, content_hash, excluded = -1, "", ""
        rows.append({
            "run_id": run_id,
            "subject_id": subject_id,
            "preview_name": preview_name,
            "isolation_enabled": iso_str,
            "step": step,
            "schema_name": schema,
            "table_name": table,
            "row_count": row_count,
            "content_hash": content_hash,
            "excluded_columns": excluded,
            "snapshot_hash_global": "",  # filled by summary row only
            "ts": ts,
        })
        per_table.append(f"{schema}.{table}:{content_hash}")

    # Global hash row
    combined = "\n".join(sorted(per_table)).encode()
    snapshot_hash_global = hashlib.sha256(combined).hexdigest()
    rows.append({
        "run_id": run_id,
        "subject_id": subject_id,
        "preview_name": preview_name,
        "isolation_enabled": iso_str,
        "step": step,
        "schema_name": "*",
        "table_name": "*",
        "row_count": sum(r["row_count"] for r in rows if r["row_count"] >= 0),
        "content_hash": "",
        "excluded_columns": "",
        "snapshot_hash_global": snapshot_hash_global,
        "ts": ts,
    })
    # Backfill snapshot_hash_global into every per-table row so analysis can
    # group easily.
    for r in rows:
        r["snapshot_hash_global"] = snapshot_hash_global
    return rows


# ---------------------------------------------------------------------------
# Append to CSV — same convention as other harness CSVs
# ---------------------------------------------------------------------------

def iter_rows_to_csv(rows: Iterable[dict], path: str, append: bool = True) -> None:
    import csv
    from pathlib import Path

    fieldnames = [
        "run_id", "subject_id", "preview_name", "isolation_enabled",
        "step", "schema_name", "table_name", "row_count", "content_hash",
        "excluded_columns", "snapshot_hash_global", "ts",
    ]
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_header = (not p.exists()) or (not append)
    mode = "a" if (append and p.exists()) else "w"
    with p.open(mode, newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            w.writeheader()
        for r in rows:
            w.writerow(r)
