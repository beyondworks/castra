#!/usr/bin/env python3
"""Load the public execution contract and track emission per runtime session."""
import hashlib
import os
from pathlib import Path

MAX_PACK_BYTES = 10 * 1024
START = '<castra_execution_posture>'
END = '</castra_execution_posture>'


def load_contract(hook_dir):
    home = Path(os.environ.get('CASTRA_HOME') or Path.home() / '.castra')
    candidates = (Path(hook_dir).parent / 'packs' / 'execution-posture-pack.txt',
                  home / 'packs' / 'execution-posture-pack.txt')
    pack = next((path for path in candidates if path.is_file()), None)
    if pack is None:
        raise FileNotFoundError('execution contract is missing')
    # Reject oversized/truncated or malformed contracts rather than silently
    # presenting a partial policy as the current one. Never read unbounded text.
    with pack.open('rb') as source:
        raw = source.read(MAX_PACK_BYTES + 1)
    if len(raw) > MAX_PACK_BYTES:
        raise ValueError('execution contract exceeds the byte limit')
    body = raw.decode('utf-8').strip()
    if (not body.startswith(START) or not body.endswith(END)
            or body.count(START) != 1 or body.count(END) != 1):
        raise ValueError('execution contract has invalid boundaries')
    return body, hashlib.sha256(raw).hexdigest()


def contract_context(payload, hook_dir, force=False, session_start=False, skip=False):
    """Return a fresh contract once per session/hash, or on explicit restoration.

    This records hook emission, not a claim that the model followed the contract.
    All unrelated runtime evidence remains intact under the same session lock.
    """
    body, digest = (None, None) if skip else load_contract(hook_dir)
    session, cwd = payload.get('session_id'), payload.get('cwd')
    if (not isinstance(session, str) or not session.strip()
            or not isinstance(cwd, str) or not cwd.strip()):
        return body if force else None
    from castra_runtime import locked
    with locked(cwd, session) as state:
        # SessionStart already supplies the contract to the first prompt, whether
        # startup, resume or compact. Consume this flag even for plain mode so a
        # later explicit invocation still restores context after intervening work.
        first_prompt = state.pop('execution_contract_first_prompt', False) is True
        if skip:
            return None
        unchanged = state.get('execution_contract_sha256') == digest
        if not session_start and unchanged and (not force or first_prompt):
            return None
        state['execution_contract_sha256'] = digest
        if session_start:
            state['execution_contract_first_prompt'] = True
        return body
