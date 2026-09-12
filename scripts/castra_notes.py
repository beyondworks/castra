#!/usr/bin/env python3
"""Session-scoped, agent-authored checkpoints and bounded usage estimates.

Checkpoints preserve explicit notes, not model internals. Transcript usage is a
last-response estimate; it is not a measurement of the live context window.
"""
import argparse
import hashlib
import json
import os
import pathlib
import sys
import time

TAIL_BYTES = 512 * 1024
OUTPUT_BYTES = 8000
FIELDS = ("goal", "decision", "progress", "learned", "next")
_USAGE_FIELDS = ("input_tokens", "cache_read_input_tokens",
                 "cache_creation_input_tokens", "output_tokens")


def bounded(text, budget=OUTPUT_BYTES):
    budget = max(128, min(int(budget), OUTPUT_BYTES))
    data = text.encode("utf-8")
    marker = b"\n[truncated: bounded recent context]\n"
    return text if len(data) <= budget else data[:budget-len(marker)].decode("utf-8", "ignore") + marker.decode()


def _records(path):
    """Read at most a fixed tail; discard its first partial JSONL record."""
    try:
        with pathlib.Path(path).open("rb") as fh:
            fh.seek(0, 2)
            start = max(0, fh.tell() - TAIL_BYTES)
            fh.seek(start)
            data = fh.read(TAIL_BYTES)
            if start:
                _, _, data = data.partition(b"\n")
    except (OSError, ValueError):
        return []
    out = []
    for line in data.splitlines():
        try:
            item = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def _state_root(cwd=None):
    env = os.environ.get("CASTRA_NOTES_DIR") or os.environ.get("ASTRA_NOTES_DIR")
    if env:
        return pathlib.Path(env).expanduser()
    cwd = pathlib.Path(cwd or pathlib.Path.cwd())
    new_dir, old_dir = cwd / ".castra", cwd / ".astra"
    return old_dir if not new_dir.exists() and old_dir.exists() else new_dir


def notes_path(cwd=None, session_id=None):
    root = _state_root(cwd)
    session_id = session_id or os.environ.get("CLAUDE_SESSION_ID", "")
    if session_id:
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        return root / "sessions" / digest / "notes.jsonl"
    return root / "notes.jsonl"  # legacy location is never migrated or removed


def latest_checkpoint(cwd=None, session_id=None):
    entries = _records(notes_path(cwd, session_id))
    return entries[-1] if entries else None


def restore_checkpoint(cwd=None, session_id=None, budget=4000):
    entry = latest_checkpoint(cwd, session_id)
    if not entry:
        return ""
    parts = ["Agent-authored checkpoint (not independently verified runtime evidence):"]
    # Restore one checkpoint, reserving space so a long goal cannot hide next.
    fields = [field for field in ("goal", "progress", "next", "decision", "learned")
              if isinstance(entry.get(field), str) and entry[field]]
    share = max(8, (max(128, min(int(budget), OUTPUT_BYTES)) - 160) // max(1, len(fields)))
    for field in fields:
        value = entry[field]
        encoded = value.encode("utf-8")
        if len(encoded) > share:
            value = encoded[:max(0, share - 3)].decode("utf-8", "ignore") + "..."
        parts.append(f"{field}: {value}")
    return bounded("\n".join(parts), budget)


def cmd_checkpoint(a):
    path = notes_path(session_id=a.session)
    entry = {"ts": time.time(), "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
             "source": "agent-authored", "window": a.window,
             **{field: getattr(a, field) for field in FIELDS}}
    encoded = json.dumps(entry, ensure_ascii=False) + "\n"
    if len(encoded.encode("utf-8")) > 32000:
        raise SystemExit("checkpoint exceeds 32000 bytes; summarize and retain source pointers")
    path.parent.mkdir(parents=True, exist_ok=True)
    # One append write avoids interleaved buffered chunks for cooperating writers.
    with path.open("a", encoding="utf-8") as fh:
        fh.write(encoded)
    print(f"agent-authored checkpoint saved: {path}")


def _render(entries):
    parts = ["Agent-authored checkpoints; bounded recent-file search, not runtime verification."]
    for entry in entries:
        parts.append(f"\n[{entry.get('iso', '')}]")
        parts.extend(f"{k}: {entry[k]}" for k in FIELDS if isinstance(entry.get(k), str) and entry[k])
    return "\n".join(parts)


def cmd_read(a):
    entries = _records(notes_path(session_id=a.session))
    show = entries if a.all else entries[-max(1, min(a.limit, 100)):]
    print(bounded(_render(show) if show else "no checkpoints yet", a.budget))


def cmd_search(a):
    entries = _records(notes_path(session_id=a.session))
    hits = [e for e in entries if a.query.lower() in json.dumps(e, ensure_ascii=False).lower()]
    print(bounded(_render(hits[-max(1, min(a.limit, 100)):]) if hits else "no match in bounded recent checkpoints", a.budget))


def read_window_usage(path):
    """Last valid response usage after the most recent compaction boundary.

    Return zero (unknown) if no valid usage follows compaction. Never estimate
    usage from transcript characters or inspect another session's transcript.
    """
    last = 0
    for record in _records(path):
        if record.get("subtype") == "compact_boundary" or record.get("type") == "compact_boundary":
            last = 0
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        values = [usage.get(k, 0) for k in _USAGE_FIELDS]
        if all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in values):
            last = sum(values)
    return last


def detect_window(path=None, default=0):
    """Capacity is explicit only; model names and historical peaks prove none.

    The path/default parameters remain compatible with older callers; neither
    grants evidence of capacity. Hook payloads do not document such a field.
    """
    try:
        window = int(os.environ.get("CASTRA_CONTEXT_WINDOW", "0"))
    except ValueError:
        window = 0
    return (window, "CASTRA_CONTEXT_WINDOW explicit configuration") if window > 0 else (0, "unknown; set CASTRA_CONTEXT_WINDOW to verified capacity")


def cmd_budget(a):
    total, source = (a.window, "explicit --window") if a.window and a.window > 0 else detect_window()
    used = read_window_usage(pathlib.Path(a.transcript).expanduser()) if a.transcript else 0
    print(f"context_window: {total or 'unknown'} ({source})")
    print(f"last_response_usage_estimate: {used or 'unknown'}")
    if total and used:
        remaining = max(total - used, 0)
        print(f"estimated_remaining: {remaining} ({remaining / total:.1%})")
    else:
        print("estimated_remaining: unknown")
    print("Runtime-recorded last-response estimate only; intervening tools and pending input are not counted. Compaction invalidates earlier usage.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("checkpoint")
    for field in FIELDS:
        c.add_argument(f"--{field}", default="")
    c.add_argument("--window", default="")
    c.set_defaults(func=cmd_checkpoint)
    r = sub.add_parser("read")
    r.add_argument("--all", action="store_true", help="all records in bounded file tail")
    r.set_defaults(func=cmd_read)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.set_defaults(func=cmd_search)
    for command in (c, r, s):
        command.add_argument("--session", default=None, help="defaults to CLAUDE_SESSION_ID; omitted uses legacy unscoped notes")
    for command in (r, s):
        command.add_argument("--budget", type=int, default=OUTPUT_BYTES)
        command.add_argument("--limit", type=int, default=3)
    b = sub.add_parser("budget")
    b.add_argument("--window", type=int, default=None)
    b.add_argument("--transcript", default="")
    b.add_argument("--tail", type=int, default=0, help="legacy option; reads fixed bounded tail regardless")
    b.set_defaults(func=cmd_budget)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
