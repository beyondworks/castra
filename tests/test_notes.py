#!/usr/bin/env python3
"""Session isolation, restoration, legacy preservation and bounded output."""
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
CLI = ROOT / "scripts/castra_notes.py"


class NotesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cwd = pathlib.Path(self.tmp.name)
        self.env = dict(os.environ, CASTRA_NOTES_DIR=str(self.cwd / "notes"), CLAUDE_SESSION_ID="alpha")

    def cli(self, *args, session="alpha"):
        return subprocess.run([sys.executable, str(CLI), *args], cwd=self.cwd,
                              env=dict(self.env, CLAUDE_SESSION_ID=session), text=True, capture_output=True, check=True).stdout

    def test_session_separation_and_explicit_override(self):
        self.cli("checkpoint", "--goal", "Alpha", "--next", "Test")
        self.cli("checkpoint", "--goal", "Beta", "--session", "beta")
        self.assertIn("Alpha", self.cli("read"))
        self.assertNotIn("Beta", self.cli("read"))
        self.assertIn("Beta", self.cli("read", "--session", "beta"))
        self.assertIn("no checkpoints", self.cli("read", session="gamma"))

    def test_restore_latest_explicit_checkpoint(self):
        self.cli("checkpoint", "--goal", "old", "--next", "old-next")
        self.cli("checkpoint", "--goal", "new", "--progress", "done", "--next", "verify")
        with patch.dict(os.environ, self.env):
            entry = notes.latest_checkpoint(self.cwd, "alpha")
            result = notes.restore_checkpoint(self.cwd, "alpha")
            self.assertEqual(entry["source"], "agent-authored")
            self.assertIn("goal: new", result)
            self.assertIn("next: verify", result)
            self.assertNotIn("old-next", result)
            self.assertEqual(notes.restore_checkpoint(self.cwd, "beta"), "")

    def test_preserve_legacy_unscoped(self):
        legacy = self.cwd / "notes/notes.jsonl"
        legacy.parent.mkdir()
        original = json.dumps({"goal": "legacy"}) + "\n"
        legacy.write_text(original)
        self.cli("checkpoint", "--goal", "new session")
        self.assertEqual(legacy.read_text(), original)
        self.assertIn("legacy", self.cli("read", session=""))
        self.assertNotIn("legacy", self.cli("read"))

    def test_bounded_read_search_and_restore(self):
        self.cli("checkpoint", "--goal", "한" * 3000, "--next", "inspect")
        for args in (("read", "--all", "--budget", "600"), ("search", "한", "--budget", "600")):
            result = self.cli(*args)
            self.assertLessEqual(len(result.encode()), 601)
            self.assertIn("truncated", result)
        with patch.dict(os.environ, self.env):
            restored = notes.restore_checkpoint(self.cwd, "alpha", budget=600)
            self.assertLessEqual(len(restored.encode()), 600)
            self.assertIn("next: inspect", restored)

    def test_malformed_records_and_oversized_checkpoint(self):
        with patch.dict(os.environ, self.env):
            path = notes.notes_path(self.cwd, "alpha")
            path.parent.mkdir(parents=True)
            path.write_text('{bad\n[]\nnull\n' + json.dumps({"goal": "valid"}) + '\n')
            self.assertEqual(notes.latest_checkpoint(self.cwd, "alpha")["goal"], "valid")
        before = path.read_bytes()
        proc = subprocess.run([sys.executable, str(CLI), "checkpoint", "--goal", "x" * 33000],
                              cwd=self.cwd, env=self.env, text=True, capture_output=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(path.read_bytes(), before)

    def test_session_identifier_cannot_escape_root(self):
        with patch.dict(os.environ, self.env):
            path = notes.notes_path(self.cwd, "../../unsafe")
            self.assertTrue(path.is_relative_to(self.cwd / "notes/sessions"))
            self.assertNotIn("..", path.parts)

    def test_legacy_astra_directory_is_preserved(self):
        (self.cwd / ".astra").mkdir()
        with patch.dict(os.environ, {"CASTRA_NOTES_DIR": "", "ASTRA_NOTES_DIR": "", "CLAUDE_SESSION_ID": ""}):
            self.assertEqual(notes.notes_path(self.cwd), self.cwd / ".astra/notes.jsonl")


if __name__ == "__main__":
    unittest.main()
