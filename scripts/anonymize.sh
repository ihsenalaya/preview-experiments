#!/usr/bin/env bash
# Prepare the experimentation/ directory for double-blind IEEE submission.
#
# Replaces all identifying strings with neutral placeholders:
#   ghcr.io/ihsenalaya  →  ghcr.io/<owner>
#   ihsenalaya          →  <owner>
#   e7seno@gmail.com    →  <redacted-email>
#   preview-cl-kubebuilder-ec0e82-ybc0tfoe.hcp.eastus.azmk8s.io  →  <aks-endpoint>
#
# Usage:
#   bash scripts/anonymize.sh [--dry-run]
#
# Pass --dry-run to print the list of affected files without modifying them.
#
# The script operates on a COPY of the repository (git archive) and writes
# the anonymized archive to anonymized-submission.tar.gz in the current dir.
set -euo pipefail

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="$(mktemp -d)"
ARCHIVE_NAME="anonymized-submission.tar.gz"

# ── substitution map ────────────────────────────────────────────────────────
declare -A REPLACEMENTS=(
    ["ghcr.io/ihsenalaya"]="ghcr.io/<owner>"
    ["ihsenalaya/idp-preview"]="<owner>/idp-preview"
    ["ihsenalaya"]="<owner>"
    ["e7seno@gmail.com"]="<redacted-email>"
    ["preview-cl-kubebuilder-ec0e82-ybc0tfoe.hcp.eastus.azmk8s.io"]="<aks-endpoint>"
    ["preview.ihsenalaya.xyz"]="<preview-domain>"
    ["github.com/ihsenalaya"]="github.com/<owner>"
)

# ── files to process ─────────────────────────────────────────────────────────
# Exclude: git history, virtual envs, compiled caches, large result CSVs
INCLUDE_PATTERNS=(
    "*.py" "*.yaml" "*.yml" "*.sh" "*.md" "*.toml" "*.cfg"
    "*.txt" "*.json" "Dockerfile" "Makefile" "*.lock"
)

echo "==> Root: $ROOT"
echo "==> Output dir: $OUT_DIR"
echo ""

matched_files=()
for pattern in "${INCLUDE_PATTERNS[@]}"; do
    while IFS= read -r f; do
        # Skip hidden dirs, __pycache__, .git, venv, results CSVs
        if echo "$f" | grep -qE '(/\.git/|/__pycache__/|/\.venv/|/venv/|/results/.*\.csv$)'; then
            continue
        fi
        matched_files+=("$f")
    done < <(find "$ROOT" -name "$pattern" -type f 2>/dev/null)
done

# Deduplicate
IFS=$'\n' sorted_files=($(sort -u <<< "${matched_files[*]}")); unset IFS

echo "Files to anonymize: ${#sorted_files[@]}"

if $DRY_RUN; then
    echo ""
    echo "=== DRY RUN: files that would be modified ==="
    for f in "${sorted_files[@]}"; do
        needs_change=false
        for pattern in "${!REPLACEMENTS[@]}"; do
            if grep -qF "$pattern" "$f" 2>/dev/null; then
                needs_change=true
                break
            fi
        done
        if $needs_change; then
            echo "  MODIFY: ${f#$ROOT/}"
        fi
    done
    echo ""
    echo "Run without --dry-run to produce $ARCHIVE_NAME"
    exit 0
fi

# ── copy tree and apply substitutions ───────────────────────────────────────
rsync -a --exclude='.git' --exclude='__pycache__' --exclude='.venv' \
      --exclude='venv' --exclude='*.pyc' \
      "$ROOT/" "$OUT_DIR/"

modified=0
for f in "${sorted_files[@]}"; do
    rel="${f#$ROOT/}"
    dest="$OUT_DIR/$rel"
    [ -f "$dest" ] || continue

    changed=false
    content=$(cat "$dest")
    new_content="$content"

    for pattern in "${!REPLACEMENTS[@]}"; do
        replacement="${REPLACEMENTS[$pattern]}"
        if echo "$new_content" | grep -qF "$pattern"; then
            new_content=$(echo "$new_content" | sed "s|${pattern}|${replacement}|g")
            changed=true
        fi
    done

    if $changed; then
        echo "$new_content" > "$dest"
        echo "  anonymized: $rel"
        (( modified++ )) || true
    fi
done

echo ""
echo "Modified $modified files."

# ── package ──────────────────────────────────────────────────────────────────
tar -czf "$ROOT/$ARCHIVE_NAME" -C "$OUT_DIR" .
rm -rf "$OUT_DIR"

echo "==> Archive: $ROOT/$ARCHIVE_NAME"
echo "    $(du -sh "$ROOT/$ARCHIVE_NAME" | cut -f1) ready for submission."
