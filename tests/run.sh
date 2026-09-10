#!/usr/bin/env bash
# Run every Castra check. Exits non-zero if any of them fails.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
status=0
for t in test_*.py; do
  echo "── $t"
  python3 "$t" || status=1
done
exit "$status"
