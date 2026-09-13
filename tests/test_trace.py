#!/usr/bin/env python3
"""Evidence and session isolation regression checks."""
import json
import os
import shutil
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import castra_runtime as runtime


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cwd = pathlib.Path(self.tmp.name).resolve()
        self.file = self.cwd / 'app.py'
        self.file.write_text('print(1)\n')

    def fire(self, tool='Edit', inp=None, response=None, session='a'):
        payload = {'session_id': session, 'cwd': str(self.cwd), 'hook_event_name': 'PostToolUse',
                   'tool_name': tool, 'tool_input': inp or {'file_path': str(self.file)},
                   'tool_response': {'success': True} if response is None else response}
        p = subprocess.run([sys.executable, str(ROOT / 'hooks/castra-trace.py')],
                           input=json.dumps(payload), text=True, capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    def item(self, session='a'):
        return runtime.status(self.cwd, session)['files'][str(self.file)]

    def test_ui_and_notebook_edits_are_pending(self):
        for suffix in ('.css', '.html', '.vue', '.ipynb'):
            path = self.cwd / ('surface' + suffix)
            path.write_text('fixture')
            self.fire('NotebookEdit' if suffix == '.ipynb' else 'Edit', {'notebook_path' if suffix == '.ipynb' else 'file_path': str(path)})
            self.assertEqual(runtime.status(self.cwd, 'a')['files'][str(path)]['status'], 'pending')
        config = self.cwd / 'ordinary.json'
        config.write_text('{}')
        self.fire('Write', {'file_path': str(config)})
        self.assertNotIn(str(config), runtime.status(self.cwd, 'a')['files'])

    def test_sessions_and_failed_response(self):
        self.fire()
        self.assertEqual(self.item()['status'], 'pending')
        self.assertEqual(runtime.status(self.cwd, 'b')['files'], {})
        self.fire('Bash', {'command': 'python3 app.py'}, {'exit_code': 1})
        self.assertEqual(self.item()['status'], 'pending')

    def test_echo_inline_and_path_collision_do_not_verify(self):
        self.fire()
        for command in ('echo python3 app.py', 'python3 -c "print(1)" app.py',
                        'python3 other/app.py', 'python3 app.py; echo done'):
            self.fire('Bash', {'command': command}, {'exit_code': 0})
            self.assertEqual(self.item()['status'], 'pending', command)

    def test_direct_success_cannot_close_without_prerun_snapshot(self):
        self.fire()
        self.fire('Bash', {'command': 'python3 app.py'}, {'exit_code': 0})
        self.assertEqual(self.item()['status'], 'pending')
        self.file.write_text('print(2)\n')
        self.fire()
        self.assertEqual(self.item()['status'], 'pending')

    def test_old_run_cannot_verify_a_concurrent_new_edit(self):
        self.fire()
        self.file.write_text('raise RuntimeError("new failing bytes")\n')
        self.fire()
        self.fire('Bash', {'command': 'python3 app.py'}, {'exit_code': 0})
        self.assertEqual(self.item()['status'], 'pending')

    def test_unknown_response_never_verifies(self):
        self.fire()
        self.fire('Bash', {'command': 'python3 app.py'}, {'stdout': 'ok'})
        self.assertEqual(self.item()['status'], 'pending')

    def test_explicit_verify_failure_and_success(self):
        self.fire()
        base = [sys.executable, str(ROOT / 'scripts/castra_runtime.py'), 'verify', '--session', 'a', '--file', 'app.py', '--']
        for code, expected in [('raise SystemExit(2)', 'pending'), ('pass', 'verified')]:
            p = subprocess.run(base + [sys.executable, '-c', code], cwd=self.cwd, capture_output=True)
            self.assertEqual(p.returncode, 2 if expected == 'pending' else 0)
            self.assertEqual(self.item()['status'], expected)
        self.assertNotIn('SystemExit', json.dumps(runtime.status(self.cwd, 'a')))

    def test_explicit_verify_changed_during_check(self):
        self.fire()
        p = subprocess.run([sys.executable, str(ROOT / 'scripts/castra_runtime.py'), 'verify',
                            '--session', 'a', '--file', 'app.py', '--', sys.executable, '-c',
                            "from pathlib import Path; Path('app.py').write_text('changed')"], cwd=self.cwd, capture_output=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.item()['status'], 'pending')

    def test_concurrent_edit_hooks_preserve_all_files(self):
        processes = []
        for i in range(12):
            file = self.cwd / f'module{i}.py'
            file.write_text('pass')
            p = subprocess.Popen([sys.executable, str(ROOT / 'hooks/castra-trace.py')], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            payload = {'session_id': 'a', 'cwd': str(self.cwd), 'tool_name': 'Edit',
                       'tool_input': {'file_path': str(file)}, 'tool_response': {'success': True}}
            p.stdin.write(json.dumps(payload))
            p.stdin.close()
            processes.append(p)
        for p in processes:
            self.assertEqual(p.wait(timeout=10), 0)
            p.stdout.close()
            p.stderr.close()
        self.assertEqual(len(runtime.status(self.cwd, 'a')['files']), 12)

    def test_timeout_and_guard_keep_pending(self):
        self.fire()
        base = [sys.executable, str(ROOT / 'scripts/castra_runtime.py'), 'verify', '--session', 'a',
                '--file', 'app.py', '--timeout', '0.05', '--']
        p = subprocess.run(base + [sys.executable, '-c', 'import time; time.sleep(10)'], cwd=self.cwd, capture_output=True)
        self.assertEqual(p.returncode, 124)
        self.assertEqual(self.item()['status'], 'pending')
        p = subprocess.run(base + ['rm', '-rf', str(self.file)], cwd=self.cwd, capture_output=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertTrue(self.file.exists())
        self.assertTrue(json.loads(p.stdout)['blocked_by_guard'])

    def test_later_same_bytes_edit_cannot_close(self):
        self.fire()
        digest = runtime.fingerprint(self.file)
        runtime.record_check(self.cwd, 'a', [str(self.file)], {str(self.file): digest}, 0, 1, 'test', started_at=0)
        self.assertEqual(self.item()['status'], 'pending')

    def test_copied_hooks_find_installed_runtime(self):
        home = self.cwd / 'fake-home'
        hooks = home / '.claude/hooks'
        scripts = home / '.castra/scripts'
        hooks.mkdir(parents=True)
        scripts.mkdir(parents=True)
        for name in ('castra-trace.py', 'castra-openloop.py'):
            shutil.copy2(ROOT / 'hooks' / name, hooks / name)
        shutil.copy2(ROOT / 'scripts/castra_runtime.py', scripts / 'castra_runtime.py')
        # Path.home() reads USERPROFILE on Windows and HOME elsewhere.
        env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
        env.pop('CASTRA_HOME', None)
        for custom in (False, True):
            if custom:
                env['CASTRA_HOME'] = str(home / '.castra')
            payload = {'session_id': 'copied', 'cwd': str(self.cwd), 'tool_name': 'Edit',
                       'tool_input': {'file_path': str(self.file)}, 'tool_response': {'success': True}}
            p = subprocess.run([sys.executable, str(hooks / 'castra-trace.py')], env=env,
                               input=json.dumps(payload), text=True, capture_output=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            payload['stop_hook_active'] = False
            p = subprocess.run([sys.executable, str(hooks / 'castra-openloop.py')], env=env,
                               input=json.dumps(payload), text=True, capture_output=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(p.stdout)['decision'], 'block')

    def test_verify_diagnostics_bounded_redacted_not_persisted(self):
        check = self.cwd / 'check.py'
        sentinel = 'fixture-sensitive-value'
        check.write_text("print('x' * 20000)\nprint('TEST_API_TOKEN=" + sentinel + "')\nassert False, 'diagnostic-visible'\n")
        p = subprocess.run([sys.executable, str(ROOT / 'scripts/castra_runtime.py'), 'verify', '--session', 'a',
                            '--file', 'app.py', '--', sys.executable, str(check)], cwd=self.cwd, capture_output=True)
        self.assertNotEqual(p.returncode, 0)
        result = json.loads(p.stdout)
        tail = result['untrusted_output_tail']
        self.assertIn('diagnostic-visible', tail)
        self.assertNotIn(sentinel, tail)
        self.assertIn('[REDACTED]', tail)
        self.assertLessEqual(len(tail.encode()), 6000)
        self.assertTrue(result['output_truncated'])
        ledger = json.dumps(runtime.status(self.cwd, 'a'))
        self.assertNotIn('diagnostic-visible', ledger)
        self.assertNotIn(sentinel, ledger)
        self.assertNotIn(str(check), ledger)

    def test_malformed_payload(self):
        for payload in ('[]', 'null', '{', '{"tool_input": []}'):
            p = subprocess.run([sys.executable, str(ROOT / 'hooks/castra-trace.py')], input=payload, text=True, capture_output=True)
            self.assertEqual(p.returncode, 0, p.stderr)

    def test_failed_edit_does_not_register(self):
        self.fire(response={'is_error': True})
        self.assertEqual(runtime.status(self.cwd, 'a')['files'], {})


if __name__ == '__main__':
    unittest.main()
