#!/usr/bin/env python3
"""Record edits and execution observations without inferring verification coverage.

Shell writes cannot be fully inferred from command strings. This hook deliberately
tracks Edit/Write plus narrow direct-script runs; use the explicit verify CLI for
builds, migrations and other checks. Text mentioning a runner never counts.
"""
import json
import os
from pathlib import Path
import shlex
import sys

# Source/plugin sibling scripts take precedence over a standalone installation.
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts'),
                str(Path(os.environ.get('CASTRA_HOME', str(Path.home() / '.castra'))).expanduser() / 'scripts')]
import castra_runtime as runtime

CODE_SUFFIXES = {'.py', '.js', '.ts', '.tsx', '.jsx', '.rs', '.go', '.rb', '.sh', '.bash', '.zsh', '.java', '.kt', '.swift', '.c', '.cpp', '.css', '.scss', '.html', '.vue', '.svelte', '.ipynb'}
PATH_MARKERS = (('/.github/workflows/', ('.yml', '.yaml')), ('/migrations/', ('.sql', '.yml', '.yaml')))
DIRECT = {'python': {'.py'}, 'python3': {'.py'}, 'node': {'.js'}, 'ruby': {'.rb'}, 'bash': {'.sh', '.bash'}, 'sh': {'.sh'}, 'zsh': {'.sh', '.zsh'}}


def is_tracked(path):
    return path.suffix.lower() in CODE_SUFFIXES or any(marker in path.as_posix() and path.suffix.lower() in endings for marker, endings in PATH_MARKERS)


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return
        session = runtime.session_id(payload.get('session_id'))
        cwd = payload.get('cwd') or os.getcwd()
        inp, response = payload.get('tool_input'), payload.get('tool_response')
        if not session or not isinstance(cwd, str) or not isinstance(inp, dict) or not isinstance(response, dict):
            return
        if payload.get('hook_event_name', 'PostToolUse') != 'PostToolUse':
            return
        if response.get('is_error') or response.get('error') or response.get('interrupted') or response.get('success') is False:
            return
        tool = payload.get('tool_name')
        if tool in ('Edit', 'Write', 'NotebookEdit'):
            raw = inp.get('file_path') or inp.get('notebook_path')
            if isinstance(raw, str) and raw:
                path = Path(runtime.canonical(cwd, raw))
                if is_tracked(path):
                    runtime.record_edit(cwd, session, path)
            return
        if tool != 'Bash':
            return
        code = response.get('exit_code', response.get('exitCode'))
        if type(code) is not int or code != 0:
            return
        command = inp.get('command')
        if not isinstance(command, str) or any(c in command for c in '\n;|&><`$'):
            return
        args = shlex.split(command)
        if len(args) != 2 or args[1].startswith('-'):
            return
        suffixes = DIRECT.get(Path(args[0]).name)
        path = runtime.canonical(cwd, args[1])
        if not suffixes or Path(path).suffix not in suffixes:
            return
        state = runtime.status(cwd, session)
        item = state['files'].get(path)
        if item and item.get('status') == 'pending' and item.get('sha256') == runtime.fingerprint(path):
            print(json.dumps({'hookSpecificOutput': {
                'hookEventName': 'PostToolUse',
                'additionalContext': 'Castra observed a successful direct-script exit, but no pre-run file snapshot was available. The change remains pending; use castra_runtime.py verify for a hash-correlated check.',
            }}))
    except (OSError, ValueError, TypeError):
        # Fail open on malformed hook input, without claiming a verification.
        return


if __name__ == '__main__':
    main()
