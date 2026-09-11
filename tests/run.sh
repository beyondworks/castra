#!/usr/bin/env bash
# Thin wrapper for macOS and Linux; the checks live in run.py.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYBIN="$(command -v python3 || command -v python)"
exec "$PYBIN" "$HERE/run.py" "$@"
