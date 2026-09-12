#!/usr/bin/env python3
"""Do not turn a Claude exit-zero API error into a valid behavioral trial."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Checks(unittest.TestCase):
    def trial(self, records):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name in ('run_model.py', 'create.py', 'score.py'):
                shutil.copy2(ROOT / 'evals/messenger' / name, base / name)
            fake = base / 'fake-claude'
            fake.write_text('#!' + sys.executable + '\nprint(' + repr('\n'.join(json.dumps(x) for x in records)) + ')\n')
            fake.chmod(0o700)
            proc = subprocess.run([sys.executable, str(base/'run_model.py'), '--label', 'case',
                                   '--model', 'fixture-model', '--harness', str(ROOT), '--cli', str(fake)],
                                  capture_output=True, text=True, timeout=30)
            result = json.loads((base/'case-run.json').read_text())
            return proc.returncode, result

    def test_exit_zero_api_error_is_invalid(self):
        code, result = self.trial([{'type': 'result', 'subtype': 'success', 'is_error': True,
                                    'result': 'API Error: unsupported model'}])
        self.assertEqual(code, 1)
        self.assertFalse(result['execution_valid'])

    def test_missing_result_is_invalid(self):
        code, result = self.trial([{'type': 'assistant', 'message': {'model': 'fixture-model'}}])
        self.assertEqual(code, 1)
        self.assertEqual(result['run_status'], 'invalid-or-incomplete')

    def test_model_mismatch_is_invalid(self):
        code, result = self.trial([{'type': 'assistant', 'message': {'model': 'different-model'}},
                                   {'type': 'result', 'subtype': 'success', 'is_error': False}])
        self.assertEqual(code, 1)
        self.assertFalse(result['execution_valid'])

    def test_complete_execution_is_distinct_from_functional_score(self):
        code, result = self.trial([{'type': 'assistant', 'message': {'model': 'fixture-model'}},
                                   {'type': 'result', 'subtype': 'success', 'is_error': False}])
        self.assertEqual(code, 0)
        self.assertTrue(result['execution_valid'])
        # The fake model did not repair the fixture. Completion is not a behavior pass.
        self.assertEqual(result['run_status'], 'completed')


if __name__ == '__main__':
    unittest.main()
