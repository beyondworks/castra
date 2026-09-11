#!/usr/bin/env bash
# Castra installer for macOS and Linux.
# The work happens in install.py so that both platforms run the same logic;
# this wrapper only picks an interpreter. Windows users run install.ps1.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYBIN="$(command -v python3 || command -v python || true)"
if [ -z "$PYBIN" ]; then
  echo "error: no python3 or python on PATH. Castra's hooks need one." >&2
  exit 1
fi

exec "$PYBIN" "$HERE/install.py" "$@"
