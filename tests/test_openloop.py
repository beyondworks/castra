#!/usr/bin/env python3
"""Supported Stop protocol, bounded reentry, legacy evidence preservation."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import castra_runtime as runtime


class StopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cwd = pathlib.Path(self.tmp.name).resolve()
        self.file = self.cwd / 'app.py'
        self.file.write_text('pass')

    def run_hook(self, session='a', active=False, payload=None):
        p = subprocess.run([sys.executable, str(ROOT / 'hooks/castra-openloop.py')],
                           input=payload if payload is not None else json.dumps({'cwd': str(self.cwd), 'session_id': session, 'stop_hook_active': active}),
                           text=True, capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def test_supported_block_and_session_isolation(self):
        runtime.record_edit(self.cwd, 'a', self.file)
        self.assertEqual(self.run_hook()['decision'], 'block')
        self.assertNotIn('decision', self.run_hook('b'))
        self.assertNotIn('hookSpecificOutput', self.run_hook())

    def test_reentry_does_not_loop_and_begin_turn_resets(self):
        runtime.record_edit(self.cwd, 'a', self.file)
        self.assertEqual(self.run_hook()['decision'], 'block')
        self.assertNotIn('decision', self.run_hook(active=True))
        self.run_hook()
        self.assertNotIn('decision', self.run_hook())
        runtime.begin_turn(self.cwd, 'a')
        self.assertEqual(self.run_hook()['decision'], 'block')

    def test_legacy_preserved_not_cross_session_block(self):
        old = self.cwd / '.castra/openloops'
        old.parent.mkdir()
        old.write_text('legacy evidence\n')
        self.assertNotIn('decision', self.run_hook())
        self.assertEqual(old.read_text(), 'legacy evidence\n')

    def test_honest_deferral_not_verified(self):
        runtime.record_edit(self.cwd, 'a', self.file)
        runtime.disposition(self.cwd, 'a', [self.file], 'blocked', 'external-access')
        self.assertNotIn('decision', self.run_hook())
        self.assertEqual(runtime.status(self.cwd, 'a')['files'][str(self.file)]['status'], 'blocked')

    def test_malformed(self):
        for payload in ('null', '[]', '{', '{"session_id": []}'):
            self.assertNotIn('decision', self.run_hook(payload=payload))


if __name__ == '__main__':
    unittest.main()
