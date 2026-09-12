#!/usr/bin/env python3
"""Bounded Stop recovery for known unverified session changes.

Uses the public Stop decision contract, not private model instructions. Deferred
and blocked work remains evidence, and legacy unassigned loops are preserved.
"""
import json
import os
from pathlib import Path
import sys

# Source/plugin sibling scripts take precedence over a standalone installation.
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts'),
                str(Path(os.environ.get('CASTRA_HOME', str(Path.home() / '.castra'))).expanduser() / 'scripts')]
import castra_runtime as runtime


def main():
    result = {}
    try:
        payload = json.load(sys.stdin)
        if isinstance(payload, dict):
            session = runtime.session_id(payload.get('session_id'))
            cwd = payload.get('cwd') or os.getcwd()
            if session and isinstance(cwd, str):
                result = runtime.stop_decision(cwd, session, payload.get('stop_hook_active'))
                legacy = runtime.legacy_count(cwd)
                if legacy:
                    result['systemMessage'] = result.get('systemMessage', '') + f' Castra: {legacy} legacy unassigned loops preserved; inspect before explicitly adopting them into this session.'
    except (OSError, ValueError, TypeError):
        result = {'systemMessage': 'Castra: malformed input or unavailable evidence state; no verification claim.'}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
