#!/usr/bin/env python3
"""Reset a session's recovery opportunity and route explicit Castra requests."""
import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
for candidate in (HERE.parent / 'scripts', pathlib.Path(os.environ.get('CASTRA_HOME') or pathlib.Path.home() / '.castra') / 'scripts'):
    if (candidate / 'castra_runtime.py').is_file():
        sys.path.insert(0, str(candidate))
        break

MODES = {
    'run': 'Inspect the affected surface and current source; define the outcome and discriminating check, then implement and verify within existing authority.',
    'review': 'Read-only review: inspect requested diff and consumers, return concrete findings with evidence; do not mutate without a request.',
    'verify': 'Inspect pending changes and execute relevant checks tied to explicit files; distinguish process success from semantic coverage.',
    'resume': 'Read the scoped checkpoint and verify its source/branch pointers, then continue the original objective with later steering.',
    'status': 'Read scoped runtime state and checkpoint; report pending, verified and deferred separately. A status question does not cancel active work.',
    'plain': 'Answer the request directly without activating a Castra workflow. Existing permissions and pending evidence remain in force.',
}


def route(prompt):
    # Anchored invocation only; quoted code and casual mentions do not activate.
    match = re.match(r'^(?:/castra(?::castra)?\b|castra\s*:)(?:\s*)(.*)$', prompt.strip(), re.I | re.S)
    if not match:
        return None
    rest = match.group(1).strip()
    first = rest.split(None, 1)[0].lower() if rest else 'run'
    return first if first in MODES else 'run'


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        session, cwd = payload.get('session_id'), payload.get('cwd')
        if isinstance(session, str) and session and isinstance(cwd, str) and cwd:
            from castra_runtime import begin_turn
            begin_turn(cwd, session)
        prompt = payload.get('prompt', '')
        mode = route(prompt) if isinstance(prompt, str) else None
        if mode:
            print(json.dumps({'hookSpecificOutput': {
                'hookEventName': 'UserPromptSubmit',
                'additionalContext': 'Castra mode: ' + mode + '. ' + MODES[mode],
            }}))
    except (OSError, ValueError, ImportError, TypeError):
        print(json.dumps({'systemMessage': 'Castra route could not restore scoped runtime state; automatic recovery reset is unverified.'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
