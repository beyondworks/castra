#!/usr/bin/env python3
"""Session isolation, restoration, legacy preservation and bounded output."""
import hashlib
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
                              env=dict(self.env, CLAUDE_SESSION_ID=session), text=True, encoding="utf-8",
                              errors="replace", capture_output=True, check=True).stdout

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

    @unittest.skipIf(os.name == "nt" or os.geteuid() == 0, "needs POSIX permissions")
    def test_unwritable_cwd_falls_back_to_castra_home(self):
        # A desktop session can start at '/', which macOS mounts read-only.
        locked = self.cwd / "readonly"
        locked.mkdir()
        locked.chmod(0o500)
        self.addCleanup(locked.chmod, 0o700)
        env = dict(os.environ, CASTRA_HOME=str(self.cwd / "home"), CLAUDE_SESSION_ID="alpha")
        env.pop("CASTRA_NOTES_DIR", None)
        env.pop("ASTRA_NOTES_DIR", None)

        def cli(*args):
            return subprocess.run([sys.executable, str(CLI), *args], cwd=locked, env=env, text=True,
                                  encoding="utf-8", errors="replace", capture_output=True, check=True).stdout

        cli("checkpoint", "--goal", "root cwd")
        self.assertIn("root cwd", cli("read"))
        self.assertFalse((locked / ".castra").exists())

    def test_session_notes_live_in_castra_home_and_legacy_is_read(self):
        home, work = self.cwd / "home", self.cwd / "work"
        work.mkdir()
        legacy = work / ".castra/sessions" / hashlib.sha256(b"old").hexdigest() / "notes.jsonl"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(json.dumps({"goal": "before upgrade"}) + "\n")
        env = dict(os.environ, CASTRA_HOME=str(home), CLAUDE_SESSION_ID="alpha")
        env.pop("CASTRA_NOTES_DIR", None)
        env.pop("ASTRA_NOTES_DIR", None)

        def cli(*args):
            return subprocess.run([sys.executable, str(CLI), *args], cwd=work, env=env, text=True,
                                  encoding="utf-8", errors="replace", capture_output=True, check=True).stdout

        cli("checkpoint", "--goal", "after upgrade")
        self.assertEqual(len(list(home.glob("sessions/*/notes.jsonl"))), 1)
        self.assertEqual([p for p in (work / ".castra").rglob("*") if p.is_file()], [legacy])
        self.assertIn("after upgrade", cli("read"))
        self.assertIn("before upgrade", cli("read", "--session", "old"))

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
        # Over the 32,000-byte limit while staying under the Windows command-line
        # limit of 32,767 characters: 11,000 three-byte characters are 33,000 bytes.
        proc = subprocess.run([sys.executable, str(CLI), "checkpoint", "--goal", "\uac00" * 11000],
                              cwd=self.cwd, env=self.env, text=True, encoding="utf-8",
                              errors="replace", capture_output=True)
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
