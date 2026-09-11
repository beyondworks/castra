#!/usr/bin/env python3
"""PostToolUse hook: open loops are written by the hook, never by the model."""
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
TRACE = ROOT / "hooks" / "castra-trace.py"
STOP = ROOT / "hooks" / "castra-openloop.py"


def fire(cwd: pathlib.Path, tool: str, tool_input: dict) -> None:
    subprocess.run([sys.executable, str(TRACE)],
                   input=json.dumps({"hook_event_name": "PostToolUse",
                                     "tool_name": tool, "tool_input": tool_input,
                                     "cwd": str(cwd)}),
                   capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd)


def loops(cwd: pathlib.Path) -> list:
    f = cwd / ".castra" / "openloops"
    return f.read_text(encoding="utf-8").splitlines() if f.exists() else []


def stop_blocks(cwd: pathlib.Path) -> bool:
    proc = subprocess.run([sys.executable, str(STOP)],
                          input=json.dumps({"hook_event_name": "Stop"}),
                          capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd)
    try:
        out = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return False
    return out.get("hookSpecificOutput", {}).get("shouldContinue") is True


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        cwd = pathlib.Path(tmp)

        # editing code with nobody watching it run must record an open loop
        fire(cwd, "Edit", {"file_path": str(cwd / "app.py")})
        if len(loops(cwd)) != 1:
            failures.append("editing a code file did not record an open loop")
        if not stop_blocks(cwd):
            failures.append("the turn was allowed to end on an unverified edit")

        # a command that actually runs the file closes it
        fire(cwd, "Bash", {"command": f"python3 {cwd / 'app.py'}"})
        if loops(cwd):
            failures.append("running the file did not close its open loop")
        if stop_blocks(cwd):
            failures.append("the turn was still blocked after verification")

        # documentation is not code; it must not wedge a turn
        fire(cwd, "Write", {"file_path": str(cwd / "README.md")})
        if loops(cwd):
            failures.append("a markdown edit was recorded as an open loop")

        # a command that runs something else must not close an unrelated loop
        fire(cwd, "Edit", {"file_path": str(cwd / "worker.py")})
        fire(cwd, "Bash", {"command": "python3 other.py"})
        if len(loops(cwd)) != 1:
            failures.append("an unrelated command closed the wrong open loop")

        # the model is never asked to write the file: the hook is the only author
        fire(cwd, "Bash", {"command": "ls -al"})
        if len(loops(cwd)) != 1:
            failures.append("a non-runner command changed the open loops")

    for f in failures:
        print("FAIL", f)
    print(f"{6 - len(failures)}/6 trace checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
