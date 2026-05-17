#!/usr/bin/env bash
# Regenerate results/frozen/CHECKSUMS.sha256 from MANIFEST.json.
# Run from repo root: ./repro/checksums.sh
set -euo pipefail
cd "$(dirname "$0")/.."
out="results/frozen/CHECKSUMS.sha256"
> "$out"
python3 -c "
import json, pathlib
m = json.load(open('results/frozen/MANIFEST.json'))
for e in m['entries']:
    if e.get('status') != 'final':
        continue
    print(f\"{e['sha256']}  {e['frozen_path']}\")
" | sort > "$out"
echo "wrote $(wc -l < "$out") entries to $out"
