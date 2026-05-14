#!/usr/bin/env bash
# Generate Python mutants with mutmut on idp-preview/app.py.
# Outputs a fault-catalog.yaml listing each mutant ID, type, and diff.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_DIR="$ROOT/../preview/idp-preview"
CATALOG="$SCRIPT_DIR/../fault-catalog.yaml"

MUTMUT_VERSION=$(python3 -c "import mutmut; print(mutmut.__version__)" 2>/dev/null || echo "unknown")
echo "mutmut version: $MUTMUT_VERSION"

cd "$APP_DIR"
mutmut run --paths-to-mutate app.py --no-progress 2>&1 | tail -5 || true

echo "---" > "$CATALOG"
echo "generated_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$CATALOG"
echo "mutmut_version: $MUTMUT_VERSION" >> "$CATALOG"
echo "source_file: app.py" >> "$CATALOG"
echo "mutants:" >> "$CATALOG"

mutmut results 2>/dev/null | grep -E "^[0-9]+" | while IFS= read -r line; do
    mutant_id=$(echo "$line" | awk '{print $1}')
    status=$(echo "$line" | awk '{print $2}')
    diff=$(mutmut show "$mutant_id" 2>/dev/null | head -30 || echo "unavailable")
    operator=$(echo "$diff" | grep -oE "(AOR|ROR|COI|DDL|SDL|SVR)" | head -1 || echo "unknown")
    cat >> "$CATALOG" <<YAML
  - id: $mutant_id
    status: $status
    operator: $operator
    diff: |
$(echo "$diff" | sed 's/^/      /')
YAML
done

echo "Catalog written to $CATALOG"
