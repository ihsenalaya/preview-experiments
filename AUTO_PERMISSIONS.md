# Auto-Permissions (granted 2026-05-17T21:10Z = 23h10 Paris dimanche)

The cron monitoring loop reads this file each firing to know what autonomous
actions are allowed. Modify or delete to revoke.

## 1. Commit intermediate after 4h without significant news

**Trigger**: every cron check, if `git log -1 --format=%ct` shows last commit
> 14400 seconds ago AND uncommitted changes exist in tracked working dirs.

**Action**:
```bash
git add analysis/effect_sizes_and_ci.py \
        analysis/assertion_level_decomposition.py \
        analysis/t2_replication_and_sensitivity.py \
        _run_one_subject_retry.py \
        _launch_t2_*.sh \
        scripts/db_state_multi_watch.py \
        scripts/collect_assertions_from_preview.py \
        harness/metrics_collector.py \
        paper/abstract.tex \
        paper/threats_to_validity.tex \
        repro/ \
        results/analysis/tables/T1_*.{md,tex,csv} \
        results/analysis/tables/T2_*.{md,tex,csv} \
        results/analysis/paper_claims.md \
        results/frozen/MANIFEST.json \
        results/frozen/CHECKSUMS.sha256 \
        AUTO_PERMISSIONS.md
git commit -m "TSE hardening intermediate snapshot (auto-${TIMESTAMP})"
```

**Do NOT push** (manual decision).

## 2. Auto-relaunch T2.10 v3 on crash

**Trigger**: T2.10 v3 PID disappears AND its CSV row count < 200
(threshold: a complete run produces ~510 rows; 200 is well below normal).

**Action**:
```bash
nohup ./_launch_t2_10_sensitivity_k_v2.sh > /dev/null 2>&1 &
```
(uses retry wrapper, max 1 relaunch per 24h to avoid infinite loop).

## 3a. Auto-trigger T2.9 (24h time-series, AKS) when launcher 80162 exits

**Trigger**: `kill -0 80162` fails AND T2.9 not yet started AND S5 baseline
CSV exists in results/s5-petclinic/*_mode-migration*.

**Action**:
```bash
nohup ./_launch_t2_9_timeseries_24h.sh > /dev/null 2>&1 &
```

## 3b. Auto-trigger T2.8 (Kind cross-cluster, LOCAL) when launcher 80162 exits

**Trigger**: same as 3a, in parallel.

**Action**:
```bash
nohup ./_launch_t2_8_kind_replication.sh > /dev/null 2>&1 &
```

**Caveats**:
- Consumes 4-8 vCPU + 8-16 GB RAM on the LOCAL machine for ~4h.
- Creates a Kind cluster (Docker-in-Docker), tears it down on exit.
- Preserves AKS context via trap.

## 3c. Auto-trigger PHASE 8 v2 RQ5 instrumented re-run when launcher 80162 exits

**Trigger**: same as 3a, **but only AFTER 3a (T2.9) has cleared its first batch**
to avoid both running simultaneously. C kills the operator which would disrupt
T2.9 if running concurrently. Safe order: 3a first, wait ~1h, then 3c.

**Action**:
```bash
nohup ./_launch_t2_rq5_v2_instrumented.sh s5-petclinic > /dev/null 2>&1 &
```

**Why s5**: explicit user request 2026-05-17T21:35Z — "À refaire : S5 RQ5
idempotence uniquement". Re-runs the RQ5 idempotence experiment on S5 with
the augmented PHASE 8 v2 instrumentation (15 columns) **and** the fix7
image (config.yaml = v3.4.0-fix7), giving a clean S5 RQ5 dataset that
supersedes the previous fix6 retry data.

ETA on S5 (Spring Boot): ~2-3h (Spring kill-restart slower than other stacks).

**Caveats**:
- Kills `preview-operator` pod multiple times during the run (~18 kill-restart cycles).
- Launcher's safety check refuses to start if another harness Python runner is alive.
- Output: `results/s5-petclinic/idempotence_v2_run_metrics_<TS>.csv` (15 cols).

## Constraints (always)

- **NO git push** (manual only).
- **NO destructive cluster operations** (no delete preview, no helm uninstall, no kubectl delete deploy).
- **NO new launchers besides those listed above**.
- **NO modification of the in-flight harness code** (modifications only apply to future runs).

## Revocation

Delete this file or replace with `# REVOKED` to disable all auto-permissions
at the next cron firing.
