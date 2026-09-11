#!/usr/bin/env python3
"""Stop hook: blocks a turn while open loops remain, and stays silent otherwise."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "castra-openloop.py"
PAYLOAD = json.dumps({"hook_event_name": "Stop", "stop_hook_active": False})


def run(cwd: pathlib.Path, encoding: str | None = None) -> dict:
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(cwd))
    if encoding:
        env["PYTHONIOENCODING"] = encoding
    proc = subprocess.run([sys.executable, str(HOOK)], input=PAYLOAD,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd, env=env)
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {"__unparsable__": proc.stdout}


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        cwd = pathlib.Path(tmp)
        (cwd / ".castra").mkdir()

        if run(cwd) != {}:
            failures.append("hook intervened with no open loops file")

        (cwd / ".castra" / "openloops").write_text("verify the deploy landed\n",
                                                   encoding="utf-8")
        out = run(cwd).get("hookSpecificOutput", {})
        if out.get("shouldContinue") is not True:
            failures.append("hook did not block the turn while a loop was open")
        if "verify the deploy landed" not in out.get("reason", ""):
            failures.append("block reason does not name the open item")

        # A legacy console code page must not kill the hook. Windows defaults to
        # one, and the failure mode is silence that reads like "nothing to do".
        legacy = run(cwd, encoding="cp1252").get("hookSpecificOutput", {})
        if legacy.get("shouldContinue") is not True:
            failures.append("hook died under a legacy console encoding")

        (cwd / ".castra" / "openloops").write_text("", encoding="utf-8")
        if run(cwd) != {}:
            failures.append("hook intervened on an empty open loops file")

    for f in failures:
        print("FAIL", f)
    print(f"{5 - len(failures)}/5 open-loop checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
