#!/usr/bin/env python3
"""Offline regression checks for bounded, session-local usage advisories."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import castra_notes as notes
HOOK = ROOT / "hooks" / "castra-budget.py"


def usage(used, model="unknown-future-model"):
    return {"message": {"model": model, "usage": {"input_tokens": used-100, "output_tokens": 100}}}


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = pathlib.Path(self.tmp.name) / "session.jsonl"
        self.write(usage(95000))

    def write(self, *records):
        self.path.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    def hook(self, window="100000", payload=None):
        env = dict(os.environ, CASTRA_CONTEXT_WINDOW=window, HOME=self.tmp.name)
        data = payload if payload is not None else {"transcript_path": str(self.path)}
        proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(data), env=env,
                              text=True, capture_output=True, check=True)
        self.assertEqual(proc.stderr, "")
        return proc.stdout

    def test_last_response_estimate(self):
        self.write(usage(50000), usage(95000))
        self.assertEqual(notes.read_window_usage(self.path), 95000)

    def test_unknown_capacity_never_inferred(self):
        with patch.dict(os.environ, {"CASTRA_CONTEXT_WINDOW": ""}):
            self.assertEqual(notes.detect_window(self.path, default=1000000)[0], 0)
        self.assertIn("capacity is unknown", self.hook(""))
        self.assertIn("capacity is unknown", self.hook("garbage"))

    def test_warning_critical_and_healthy(self):
        self.assertIn("running low", self.hook())
        self.write(usage(99000))
        result = self.hook()
        self.assertIn("critically low", result)
        self.assertNotIn("do not compose a final", result)
        self.assertIn("cannot create a fresh session", result)
        self.assertEqual(self.hook("1000000"), "")
        self.assertIn("about 0 tokens", self.hook("1"))

    def test_invalid_payload_and_no_fallback(self):
        for data in (None, [], "bad", 3, {"transcript_path": 123}, {"transcript_path": "/missing"}, {}):
            # Create a nearby newest transcript to ensure it is never selected.
            data = {} if data is None else data
            self.assertEqual(self.hook(payload=data), "")

    def test_compaction_invalidates_usage(self):
        self.write(usage(99000), {"type": "system", "subtype": "compact_boundary"})
        self.assertEqual(notes.read_window_usage(self.path), 0)
        self.assertEqual(self.hook(), "")
        self.write(usage(99000), {"type": "system", "subtype": "compact_boundary"}, usage(10000))
        self.assertEqual(notes.read_window_usage(self.path), 10000)

    def test_malformed_usage_does_not_crash(self):
        self.write({"message": "bad"}, {"message": {"usage": {"input_tokens": "secret"}}})
        self.assertEqual(notes.read_window_usage(self.path), 0)
        self.assertEqual(self.hook(), "")

    def test_bounded_tail_does_not_read_ancient_usage(self):
        self.path.write_text(json.dumps(usage(99000)) + "\n" + "x" * (notes.TAIL_BYTES + 5))
        self.assertEqual(notes.read_window_usage(self.path), 0)
        with self.path.open("a") as fh:
            fh.write("\n" + json.dumps(usage(12000)) + "\n")
        self.assertEqual(notes.read_window_usage(self.path), 12000)

    def test_unknown_capacity_is_quiet_on_posttool(self):
        payload = {"transcript_path": str(self.path), "hook_event_name": "PostToolUse"}
        self.assertEqual(self.hook("", payload), "")
        self.assertEqual(self.hook("invalid", payload), "")
        payload["hook_event_name"] = "UserPromptSubmit"
        self.assertIn("capacity is unknown", self.hook("", payload))

    def test_posttool_json_contract(self):
        result = json.loads(self.hook(payload={"transcript_path": str(self.path), "hook_event_name": "PostToolUse"}))
        specific = result["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "PostToolUse")
        self.assertIn("running low", specific["additionalContext"])

    def test_raw_invalid_json(self):
        proc = subprocess.run([sys.executable, str(HOOK)], input="{bad", capture_output=True, text=True)
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, "", ""))

    def test_source_import_wins_and_explicit_home_fallback(self):
        custom = pathlib.Path(self.tmp.name) / "custom"
        (custom / "scripts").mkdir(parents=True)
        (custom / "scripts/castra_notes.py").write_text(
            "def detect_window(): return (100, 'fixture')\ndef read_window_usage(path): return 99\n")
        env = dict(os.environ, CASTRA_HOME=str(custom), CASTRA_CONTEXT_WINDOW="1000000")
        payload = json.dumps({"transcript_path": str(self.path)})
        source = subprocess.run([sys.executable, str(HOOK)], input=payload, text=True,
                                env=env, capture_output=True, check=True)
        self.assertEqual(source.stdout, "")  # source sibling, not fixture
        standalone = pathlib.Path(self.tmp.name) / "standalone/hook.py"
        standalone.parent.mkdir()
        standalone.write_text(HOOK.read_text())
        fallback = subprocess.run([sys.executable, str(standalone)], input=payload, text=True,
                                  env=env, capture_output=True, check=True)
        self.assertIn("critically low", fallback.stdout)

    def test_cli_budget_no_default_million(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/castra_notes.py"), "budget", "--transcript", str(self.path)],
                                env=dict(os.environ, CASTRA_CONTEXT_WINDOW=""), text=True, capture_output=True, check=True)
        self.assertIn("context_window: unknown", result.stdout)
        self.assertIn("estimated_remaining: unknown", result.stdout)


if __name__ == "__main__":
    unittest.main()
