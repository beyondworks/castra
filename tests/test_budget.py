#!/usr/bin/env python3
"""Budget hook: occupancy reading, window detection, and both thresholds.

This test builds a synthetic transcript instead of reading a real session, and
forces the window so that each threshold is actually crossed. A budget hook that
is merely registered proves nothing — the earlier version of this hook ran on
every prompt, exited 0, and could never reach its own thresholds.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import castra_notes  # noqa: E402

HOOK = ROOT / "hooks" / "castra-budget.sh"


def transcript(path: pathlib.Path, used: int, model: str = "test-model") -> None:
    """One assistant turn whose usage sums to `used`."""
    entry = {"message": {"model": model, "usage": {
        "input_tokens": 2,
        "cache_read_input_tokens": used - 2 - 1000,
        "cache_creation_input_tokens": 0,
        "output_tokens": 1000,
    }}}
    path.write_text(json.dumps(entry) + "\n", encoding="utf-8")


def run_hook(path: pathlib.Path, window: int, home: pathlib.Path) -> str:
    env = dict(os.environ, CASTRA_CONTEXT_WINDOW=str(window), HOME=str(home))
    payload = json.dumps({"transcript_path": str(path)})
    proc = subprocess.run(["bash", str(HOOK)], input=payload,
                          capture_output=True, text=True, env=env)
    return proc.stdout.strip()


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        home = tmp / "home"
        (home / ".castra" / "scripts").mkdir(parents=True)
        for f in (ROOT / "scripts").glob("castra_*.py"):
            (home / ".castra" / "scripts" / f.name).write_text(
                f.read_text(encoding="utf-8"), encoding="utf-8")

        t = tmp / "session.jsonl"
        transcript(t, 160_000)

        if castra_notes.read_window_usage(t) != 160_000:
            failures.append("occupancy is not read from the usage record")

        # a model observed at 160k cannot be running a 200k window once it passes it
        transcript(t, 400_000)
        os.environ["HOME"] = str(home)
        window, _ = castra_notes.detect_window(t)
        if window != 1_000_000:
            failures.append(f"window detection: expected 1000000, got {window}")
        transcript(t, 160_000)

        quiet = run_hook(t, 1_000_000, home)
        if quiet:
            failures.append("hook warned while the budget was healthy")

        warn = run_hook(t, 170_000, home)
        if "context_window_reminder" not in warn or "얼마 남지" not in warn:
            failures.append("hook did not warn at the warning threshold")

        crit = run_hook(t, 163_000, home)
        if "context_window_reminder" not in crit or "고갈" not in crit:
            failures.append("hook did not fire at the critical threshold")

        missing = run_hook(pathlib.Path("/nonexistent.jsonl"), 200_000, home)
        if missing:
            failures.append("hook produced output for a missing transcript")

        # an undersized window must not surface a negative token count
        overfull = run_hook(t, 100_000, home)
        if "-" in overfull.split("추정 잔여 ")[-1].split(" 토큰")[0]:
            failures.append("hook reported a negative remaining count")

    for f in failures:
        print("FAIL", f)
    print(f"{7 - len(failures)}/7 budget checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
