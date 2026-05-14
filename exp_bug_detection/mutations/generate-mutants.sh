#!/usr/bin/env bash
# Generate Python mutants with mutmut on testapp/app.py.
# Outputs a fault-catalog.yaml listing each mutant ID, type, and diff.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_DIR="$ROOT/testapp"
CATALOG="$SCRIPT_DIR/../fault-catalog.yaml"
MAX="${MAX_MUTANTS:-50}"

export PATH="$PATH:/home/ihsen/.local/bin"

MUTMUT_VERSION="2.4.4"
echo "mutmut version: $MUTMUT_VERSION"

cd "$APP_DIR"
python3 -m mutmut run --paths-to-mutate app.py --runner "true" --no-progress 2>&1 | tail -3 || true

# Expand ranges like "1-166" into individual IDs
ALL_IDS=$(python3 -m mutmut results 2>/dev/null | grep -oE '[0-9]+-[0-9]+|^[0-9]+' | python3 -c "
import sys, re
ids = []
for line in sys.stdin:
    line = line.strip()
    if '-' in line:
        parts = line.split('-')
        ids.extend(range(int(parts[0]), int(parts[1])+1))
    elif line.isdigit():
        ids.append(int(line))
for i in ids[:${MAX}]:
    print(i)
")

TOTAL=$(echo "$ALL_IDS" | wc -l)
echo "Found $TOTAL mutants (capped at $MAX)"

cat > "$CATALOG" <<HEADER
---
generated_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
mutmut_version: $MUTMUT_VERSION
source_file: testapp/app.py
mutants:
HEADER

echo "$ALL_IDS" | while IFS= read -r mutant_id; do
    [ -z "$mutant_id" ] && continue
    diff=$(python3 -m mutmut show "$mutant_id" 2>/dev/null || echo "unavailable")
    operator=$(echo "$diff" | grep -oE '\b(AOR|ROR|COI|DDL|SDL|SVR)\b' | head -1 || echo "unknown")
    cat >> "$CATALOG" <<YAML
  - id: $mutant_id
    operator: $operator
    diff: |
$(echo "$diff" | sed 's/^/      /')
YAML
done

echo "Catalog written to $CATALOG ($(grep '^  - id:' "$CATALOG" | wc -l) mutants)"
