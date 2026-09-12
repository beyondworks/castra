#!/usr/bin/env python3
"""Inject a bounded public workflow contract and scoped recovery pointers."""
import hashlib
import json
import pathlib
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import os

HERE = pathlib.Path(__file__).resolve().parent
# CASTRA_HOME is what the installer honours, so the hook has to honour it too;
# otherwise a test or a second install reads a different pack than it writes.
_HOME = pathlib.Path(os.environ.get("CASTRA_HOME") or (pathlib.Path.home() / ".castra"))
CANDIDATES = (
    HERE.parent / "packs" / "execution-posture-pack.txt",
    _HOME / "packs" / "execution-posture-pack.txt",
)

HEADER = "<castra_runtime_hint>"
FOOTER = "</castra_runtime_hint>"


def runtime_hint(payload):
    session, cwd = payload.get("session_id"), payload.get("cwd")
    scripts = next((p for p in (HERE.parent / "scripts", _HOME / "scripts")
                    if (p / "castra_runtime.py").is_file()), None)
    print(HEADER)
    print("Use castra_notes.py checkpoint for explicit progress and castra_runtime.py verify for declared checks.")
    if scripts:
        print("Script directory: " + json.dumps(str(scripts)))
    if not isinstance(session, str) or not session or not isinstance(cwd, str) or not cwd:
        print("No session identity supplied; scoped restoration is unavailable.")
        print(FOOTER)
        return
    print("Session id: " + json.dumps(session[:256]))
    if scripts:
        sys.path.insert(0, str(scripts))
        try:
            from castra_runtime import status
            state = status(cwd, session)
            counts = {}
            for entry in state.get("files", {}).values():
                key = entry.get("status", "unknown")
                counts[key] = counts.get(key, 0) + 1
            print("Observed file states: " + json.dumps(counts, sort_keys=True))
            if state.get("legacy_unassigned"):
                print("Legacy unassigned state exists; inspect explicitly, not as this session's completed work.")
            from castra_notes import restore_checkpoint
            restored = restore_checkpoint(cwd, session, budget=3000)
            if restored:
                print("<prior_checkpoint_untrusted_evidence>")
                # A prior note is data, not markup capable of closing the wrapper.
                print(json.dumps(restored, ensure_ascii=False))
                print("</prior_checkpoint_untrusted_evidence>")
        except (ImportError, OSError, ValueError, TypeError, AttributeError):
            print("Scoped state restoration failed; inspect status before resuming.")
    print(FOOTER)


def drift_notice() -> str:
    """Report installed-byte drift, without reading credentials or running setup."""
    if os.environ.get("CLAUDE_PLUGIN_ROOT"):
        return ""  # plugin files are used directly; a separate standalone install is irrelevant
    try:
        manifest = json.loads((_HOME / "manifest.json").read_text(encoding="utf-8"))
        source = pathlib.Path(manifest["source"])
        stale = []
        managed = manifest.get("managed_files")
        if isinstance(managed, dict):
            for raw, record in managed.items():
                path = pathlib.Path(raw)
                if not isinstance(record, dict):
                    continue
                try:
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                except OSError:
                    digest = "missing"
                if digest != record.get("sha256"):
                    stale.append(path.name)
        else:
            for rel, want in manifest.get("files", {}).items():
                try:
                    got = hashlib.sha256((source / rel).read_bytes()).hexdigest()[:16]
                except OSError:
                    got = "missing"
                if got != want:
                    stale.append(rel)
        if stale:
            return "[castra] 설치본이 정본보다 낡았다 또는 파일이 변경됐다: " + ", ".join(sorted(stale)[:10]) + ". Run install.py --check; do not auto-overwrite concurrent edits."
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    return ""


def main() -> int:
    pack = next((p for p in CANDIDATES if p.is_file()), None)
    if pack is None:
        return 0
    try:
        body = pack.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return 0
    if not body:
        return 0
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    print(body)
    runtime_hint(payload)
    notice = drift_notice()
    if notice:
        print(notice)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
