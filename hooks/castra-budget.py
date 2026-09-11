#!/usr/bin/env python3
"""castra-budget — inject a context-budget reminder at two thresholds.

A UserPromptSubmit hook. Reads the session transcript, works out how much of
the context window is occupied, and prints an instruction when the remaining
budget crosses a threshold. Silence means the budget is healthy.

Occupancy comes from the transcript's own usage records rather than a character
estimate, and the window size is detected from the model id and the largest
occupancy that model has been observed to reach. Set CASTRA_CONTEXT_WINDOW to
override the detected window.

Thresholds mirror a two-stage budget policy: warn with room to act, then stop.

Written in Python rather than shell so the same file runs on macOS, Linux and
Windows. Claude Code runs shell-form hooks through Git Bash on Windows, or
PowerShell when Git Bash is absent, so a .sh hook is not portable.
"""
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
for candidate in (pathlib.Path.home() / ".castra" / "scripts", HERE.parent / "scripts"):
    if (candidate / "castra_notes.py").exists():
        sys.path.insert(0, str(candidate))
        break

try:
    from castra_notes import detect_window, read_window_usage
except ImportError:
    raise SystemExit(0)

WARN_RATIO = 0.06   # remaining share at which to checkpoint before the next step
CRIT_RATIO = 0.02   # remaining share at which to stop and hand off

WARN_MESSAGE = """<context_window_reminder>
The context budget is running low (about {shown:,} tokens left). Write a
checkpoint with castra_notes.py before starting the next substantial step, and
prune entries that have gone stale while you are there.
</context_window_reminder>"""

CRIT_MESSAGE = """<context_window_reminder>
The context window is effectively gone (about {shown:,} tokens left). Do not
continue the task in this window and do not compose a final answer here.
Call castra_notes.py checkpoint exactly once, recording the goal, decisions,
progress, what you learned, the next step, and enough of a pointer to each open
user request that a fresh window could pick it up cold. Then say only that you
have done so and continue in a new window. A clean handoff beats a truncated
answer.
</context_window_reminder>"""


def newest_transcript() -> pathlib.Path | None:
    root = pathlib.Path.home() / ".claude" / "projects"
    files = [p for p in root.glob("*/*.jsonl")] if root.exists() else []
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def resolve_transcript(payload: dict) -> pathlib.Path | None:
    raw = payload.get("transcript_path") or ""
    if raw:
        path = pathlib.Path(raw).expanduser()
        if path.is_file():
            return path
    return newest_transcript()


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, OSError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    transcript = resolve_transcript(payload)
    if transcript is None:
        return 0

    used = read_window_usage(transcript)
    if used <= 0:
        return 0

    override = os.environ.get("CASTRA_CONTEXT_WINDOW", "").strip()
    try:
        window = int(override) if override else 0
    except ValueError:
        window = 0
    if window <= 0:
        window = detect_window(transcript)[0]
    if window <= 0:
        return 0

    remaining = window - used
    # An undersized window estimate makes this negative. The comparison uses the
    # raw figure; the number shown never drops below zero.
    shown = max(remaining, 0)

    if remaining <= window * CRIT_RATIO:
        print(CRIT_MESSAGE.format(shown=shown))
    elif remaining <= window * WARN_RATIO:
        print(WARN_MESSAGE.format(shown=shown))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
