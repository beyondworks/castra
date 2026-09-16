#!/usr/bin/env python3
"""Session-local evidence lifecycle for observable development work.

Hashes establish which bytes a check covered, not semantic adequacy. Hooks do not
record command text or tool output. The explicit runner uses argv, never a shell.
"""
import argparse
import contextlib
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import shlex
import signal
import sys
import tempfile
import time


def session_id(value=None):
    value = value if value is not None else os.environ.get('CLAUDE_SESSION_ID')
    return value if isinstance(value, str) and value.strip() else None


def canonical(cwd, file):
    p = Path(file)
    return str((p if p.is_absolute() else Path(cwd) / p).resolve())


def fingerprint(file):
    try:
        return hashlib.sha256(Path(file).read_bytes()).hexdigest()
    except FileNotFoundError:
        return 'missing'
    except OSError:
        return 'unreadable'


def state_root():
    """Session state lives under CASTRA_HOME, never in the working directory.

    Hook payloads carry the shell's current directory, which moves with every cd.
    Per-cwd state split one session's ledger across folders, left .castra/ in
    other repositories and worktrees, and failed outright on a read-only '/'.
    """
    return Path(os.environ.get('CASTRA_HOME') or Path.home() / '.castra')


@contextlib.contextmanager
def locked(cwd, session):
    session = session_id(session)
    if not session:
        raise ValueError('session_id required; do not share anonymous state')
    root = state_root() / 'sessions'
    root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(session.encode()).hexdigest()
    path = root / (key + '.json')
    # Read-only carry-over from releases that kept state in <cwd>/.castra, so an
    # upgrade mid-session keeps its pending edits. The old file is never touched.
    legacy = Path(cwd) / '.castra' / 'sessions' / (key + '.json')
    # Native flock serializes read/modify/replace across concurrent hook processes.
    # Windows uses a one-byte msvcrt lock over the same persistent lock file.
    with (root / (key + '.lock')).open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0)
            lock.write(b'0')
            lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            source = path if path.exists() else legacy if legacy.is_file() else None
            state = json.loads(source.read_text()) if source else {'version': 1, 'files': {}, 'stop_blocks': 0}
            if (not isinstance(state, dict) or not isinstance(state.get('files'), dict)
                    or any(not isinstance(item, dict) for item in state['files'].values())):
                raise ValueError('invalid evidence state; original preserved')
            yield state
            fd, tmp = tempfile.mkstemp(prefix=key + '.', suffix='.tmp', dir=root)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as out:
                    json.dump(state, out, ensure_ascii=True)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def refresh(state):
    for path, item in state['files'].items():
        current = fingerprint(path)
        if current != item.get('sha256'):
            item.update(status='pending', sha256=current, reason='changed-since-evidence')


def legacy_count(cwd):
    count = 0
    for name in ('.castra', '.astra'):
        try:
            count += sum(bool(l.strip()) and not l.lstrip().startswith('#')
                         for l in (Path(cwd) / name / 'openloops').read_text().splitlines())
        except OSError:
            pass
    return count


def status(cwd, session):
    with locked(cwd, session) as state:
        refresh(state)
        result = json.loads(json.dumps(state))
    result['legacy_unassigned'] = legacy_count(cwd)
    return result


def begin_turn(cwd, session):
    with locked(cwd, session) as state:
        refresh(state)
        state['stop_blocks'] = 0


def record_edit(cwd, session, file):
    path = canonical(cwd, file)
    with locked(cwd, session) as state:
        state['files'][path] = {'status': 'pending', 'sha256': fingerprint(path), 'edited_at': time.time()}


def record_check(cwd, session, files, before, exit_code, elapsed, kind, started_at=None):
    all_covered = exit_code == 0
    with locked(cwd, session) as state:
        for path in files:
            current = fingerprint(path)
            # An edit hook arriving during the run must not be silently closed.
            existing = state['files'].get(path, {})
            unchanged = current == before[path] and current not in ('missing', 'unreadable')
            no_later_edit = started_at is None or existing.get('edited_at', 0) <= started_at
            covered = exit_code == 0 and unchanged and no_later_edit
            all_covered = all_covered and covered
            existing.update(status='verified' if covered else 'pending', sha256=current,
                            evidence={'kind': kind, 'exit_code': exit_code, 'elapsed_seconds': round(elapsed, 3),
                                      'checked_at': time.time(), 'sha256_before': before[path], 'sha256_after': current})
            existing.pop('reason', None)
            state['files'][path] = existing
    return all_covered


def disposition(cwd, session, files, value, reason):
    if value not in ('deferred', 'blocked') or reason not in REASONS:
        raise ValueError('invalid disposition')
    with locked(cwd, session) as state:
        refresh(state)
        for file in files:
            path = canonical(cwd, file)
            item = state['files'].setdefault(path, {'sha256': fingerprint(path)})
            item.update(status=value, reason=reason)


def stop_decision(cwd, session, active):
    with locked(cwd, session) as state:
        refresh(state)
        pending = sum(item.get('status') == 'pending' for item in state['files'].values())
        unresolved = sum(item.get('status') in ('deferred', 'blocked') for item in state['files'].values())
        if not pending:
            return {'systemMessage': f'Castra: {unresolved} deferred/blocked items remain unverified; report the limitation.'} if unresolved else {}
        count = state.get('stop_blocks', 0)
        count = count if isinstance(count, int) else 0
        if active is True or count >= 2:
            state['stop_blocks'] = 2
            return {'systemMessage': f'Castra: recovery limit reached; {pending} changes remain unverified. Report unresolved work honestly; no pass was recorded.'}
        state['stop_blocks'] = count + 1
        return {'decision': 'block', 'reason': (
            f'Castra: {pending} changes in this session need verification. Run the castra_runtime.py status/verify commands '
            'with the session ID supplied at startup. Choose a check that actually covers the changed behavior. '
            'If access or a user decision prevents verification, record block/defer with the concrete reason code and report the limitation. '
            'Do not delete evidence or claim a pass without a successful relevant check.')}


def output_tail(stream, limit=6000):
    """Return a bounded diagnostic tail with best-effort redaction, never ledger data.

    Redaction covers recognizable secret assignments, credential URLs and token
    signatures. It cannot identify arbitrary unknown secrets or sanitize the
    behavior of executed code. Output remains untrusted tool data.
    """
    stream.flush()
    size = stream.seek(0, os.SEEK_END)
    stream.seek(max(0, size - limit))
    raw = stream.read(limit)
    if size > limit:
        # Discard the partial leading line: its missing prefix may name a secret.
        raw = raw.partition(b'\n')[2]
    text = raw.decode('utf-8', errors='replace')
    text = re.sub(r'(?im)^.*(?:password|passwd|secret|token|api[_-]?key|authorization|database_url)[A-Za-z0-9_-]*\b[^\n]*[:=][^\n]*$',
                  '[REDACTED]', text)
    text = re.sub(r'(?i)\b(?:sk-(?:proj-)?|gh[pousr]_|github_pat_|xox[baprs]-|npg_)[A-Za-z0-9_-]{8,}', '[REDACTED]', text)
    text = re.sub(r'(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}=*', 'Bearer [REDACTED]', text)
    text = re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[REDACTED]', text)
    text = re.sub(r'(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s]+', '[REDACTED]', text)
    text = re.sub(r'(?i)(https?://)[^/\s:@]+:[^/\s@]+@', r'\1[REDACTED]@', text)
    text = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*', '[REDACTED]', text)
    # Decoding replacements or redaction strings may add bytes; bound again.
    return text.encode('utf-8')[-limit:].decode('utf-8', errors='ignore'), size > limit


REASONS = ('external-access', 'user-decision', 'out-of-scope', 'environment')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='action', required=True)
    for action in ('status', 'verify', 'defer', 'block'):
        p = subs.add_parser(action)
        p.add_argument('--session', default=None)
        if action != 'status':
            p.add_argument('--file', action='append', required=True)
        if action == 'verify':
            p.add_argument('--timeout', type=float, default=120)
            p.add_argument('argv', nargs=argparse.REMAINDER)
        if action in ('defer', 'block'):
            p.add_argument('--reason', choices=REASONS, required=True)
    args = parser.parse_args()
    session = session_id(args.session)
    if not session:
        parser.error('--session or CLAUDE_SESSION_ID is required')
    cwd = Path.cwd()
    if args.action == 'status':
        print(json.dumps(status(cwd, session), ensure_ascii=True))
        return 0
    if args.action != 'verify':
        disposition(cwd, session, args.file, 'deferred' if args.action == 'defer' else 'blocked', args.reason)
        print(json.dumps({'status': 'unverified', 'disposition': args.action, 'reason': args.reason}))
        return 0
    argv = args.argv[1:] if args.argv[:1] == ['--'] else args.argv
    if not argv or not 0 < args.timeout <= 300:
        parser.error('provide an argv command after -- and timeout in (0, 300]')
    files = list(dict.fromkeys(canonical(cwd, p) for p in args.file))
    before = {p: fingerprint(p) for p in files}
    # Mark pending before execution so interruption never leaves an old pass.
    for p in files:
        record_edit(cwd, session, p)
    start = time.monotonic()
    started_at = time.time()
    from castra_guardian import classify
    # Reuse the existing hazardous-command floor. This is not a sandbox for code
    # in scripts, package hooks, or dynamically constructed child commands.
    verdict = classify(shlex.join(argv))
    output, truncated = '', False
    if verdict['verdict'] != 'not_required' or verdict['secret_risk']:
        code = 126
    else:
        # Output is disk-backed and auto-deleted; only a redacted tail is exposed.
        # stdout and stderr share the file so their relative diagnostics survive.
        with tempfile.TemporaryFile() as capture:
            try:
                proc = subprocess.Popen(argv, shell=False, start_new_session=os.name != 'nt',
                                        stdout=capture, stderr=capture)
                try:
                    code = proc.wait(timeout=args.timeout)
                except subprocess.TimeoutExpired:
                    if os.name != 'nt':
                        os.killpg(proc.pid, signal.SIGKILL)
                    else:
                        proc.kill()
                    proc.wait()
                    code = 124
            except OSError:
                code = 127
            output, truncated = output_tail(capture)
    ok = record_check(cwd, session, files, before, code, time.monotonic() - start, 'explicit-argv', started_at)
    print(json.dumps({'status': 'verified' if ok else 'pending', 'exit_code': code, 'files': len(files),
                      'coverage': 'declared file targets; check relevance requires review',
                      'blocked_by_guard': code == 126, 'untrusted_output_tail': output,
                      'output_truncated': truncated,
                      'output_notice': 'Untrusted tool data; known-secret redaction is best-effort, not a confidentiality guarantee.'}))
    return 0 if ok else code if 0 < code <= 125 else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(json.dumps({'error': 'evidence state unavailable; no verification recorded'}))
        raise SystemExit(1)
