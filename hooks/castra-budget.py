#!/usr/bin/env python3
"""Advisory budget checks for UserPromptSubmit and PostToolUse.

Uses only this hook's transcript_path, bounded last-response usage records and
explicit capacity. Cannot create a session, measure pending input or compel a
compaction. No transcript contents are emitted.
"""
import json
import os
import pathlib
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

HERE = pathlib.Path(__file__).resolve().parent
for candidate in (HERE.parent / "scripts", pathlib.Path(os.environ.get("CASTRA_HOME", str(pathlib.Path.home() / ".castra"))) / "scripts"):
    if (candidate / "castra_notes.py").exists():
        sys.path.insert(0, str(candidate))
        break
try:
    from castra_notes import detect_window, read_window_usage
except ImportError:
    raise SystemExit(0)


def resolve_transcript(payload):
    raw = payload.get("transcript_path")
    if not isinstance(raw, str) or not raw:
        return None
    path = pathlib.Path(raw).expanduser()
    return path if path.is_file() else None


def main():
    try:
        payload = json.loads(sys.stdin.read(1048576) or "{}")
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    transcript = resolve_transcript(payload)
    if transcript is None:
        return 0
    used = read_window_usage(transcript)
    window, _ = detect_window()
    if not window:
        # Missing configuration is unchanged across tool calls; avoid repeating
        # an advisory that itself consumes context during an autonomous run.
        if payload.get("hook_event_name") == "PostToolUse":
            return 0
        message = "Context capacity is unknown; no remaining-budget claim is available. Set CASTRA_CONTEXT_WINDOW only to a verified capacity."
    elif not used:
        return 0
    elif window - used <= window * .02:
        message = (f"Estimated context remaining is critically low (about {max(window-used, 0):,} tokens). "
                   "Save an agent-authored checkpoint with goal, progress, open requests, evidence pointers and next step before substantial work. "
                   "Use the runtime's supported compaction/resume controls when needed; this advisory cannot create a fresh session.")
    elif window - used <= window * .06:
        message = (f"Estimated context remaining is running low (about {max(window-used, 0):,} tokens). "
                   "Save an agent-authored checkpoint before the next substantial step.")
    else:
        return 0
    context = ("<context_window_reminder>\n" + message +
               "\nUsage is the last recorded response estimate, not live remaining capacity; pending input and intervening tools are uncounted.\n</context_window_reminder>")
    if payload.get("hook_event_name") == "PostToolUse":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": context}}))
    else:
        print(context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
