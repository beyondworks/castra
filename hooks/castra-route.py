#!/usr/bin/env python3
"""Refresh a session contract when changed and route explicit Castra requests."""
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
    'reframe': 'Preserve the user objective. Revisit shared symptoms and the actual runtime; test one discriminating counterexample before choosing the causal repair.',
    'finish': 'Close the requested user flow across identity, state and failure cases. Inspect affected neighbors and verify supported actual surfaces; fix related defects within authority, without adding unrelated features.',
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
    except (OSError, ValueError, TypeError):
        return 0
    prompt = payload.get('prompt', '')
    mode = route(prompt) if isinstance(prompt, str) else None
    messages, notices = [], []
    try:
        session, cwd = payload.get('session_id'), payload.get('cwd')
        if isinstance(session, str) and session and isinstance(cwd, str) and cwd:
            from castra_runtime import begin_turn
            begin_turn(cwd, session)
    except (OSError, ValueError, ImportError, TypeError):
        notices.append('Castra automatic recovery reset is unverified; scoped state could not be restored.')
    # Plain opts out of contract injection only; existing evidence and authority
    # survive. Explicit invocations can restore a contract lost in a long session.
    try:
        from castra_contract import contract_context
        body = contract_context(payload, HERE, force=bool(mode), skip=(mode == 'plain'))
        if body:
            messages.append(body)
    except (OSError, ValueError, ImportError, TypeError):
        notices.append('Castra current execution contract could not be loaded or its session emission recorded; freshness is unverified.')
    if mode:
        messages.append('Castra mode: ' + mode + '. ' + MODES[mode])
    result = {}
    if messages:
        result['hookSpecificOutput'] = {
            'hookEventName': 'UserPromptSubmit',
            'additionalContext': '\n\n'.join(messages),
        }
    if notices:
        result['systemMessage'] = ' '.join(notices)
    if result:
        print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
