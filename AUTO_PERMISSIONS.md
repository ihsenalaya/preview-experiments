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

## Constraints (always)

- **NO git push** (manual only).
- **NO destructive cluster operations** (no delete preview, no helm uninstall, no kubectl delete deploy).
- **NO new launchers besides those listed above**.
- **NO modification of the in-flight harness code** (modifications only apply to future runs).

## Revocation

Delete this file or replace with `# REVOKED` to disable all auto-permissions
at the next cron firing.
