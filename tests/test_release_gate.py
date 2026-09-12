#!/usr/bin/env python3
"""PreToolUse gate: a tag or release must not go out ahead of this commit's CI."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "castra-release-gate.py"

HEAD = "a" * 40


def fake_bin(tmp: pathlib.Path, runs, head=HEAD) -> pathlib.Path:
    """git 과 gh 를 흉내내는 실행 파일을 PATH 앞에 둔다.

    네트워크나 실제 저장소 상태에 기대면 검사 자체가 환경에 따라 흔들린다.
    """
    binv = tmp / "bin"
    binv.mkdir()
    bodies = {
        "git": ("import sys\n"
                f"print({head!r}) if sys.argv[1:3]==['rev-parse','HEAD'] else None\n"),
        "gh": ("import sys; sys.exit(1)\n" if runs is None
               else f"import json; print(json.dumps({runs!r}))\n"),
    }
    for name, body in bodies.items():
        script = binv / f"{name}.py"
        script.write_text(body, encoding="utf-8")
        if os.name == "nt":
            # PATH lookup on Windows needs an executable extension; a shebang
            # script is not one, which is why this check passed on macOS and
            # failed on Windows.
            (binv / f"{name}.bat").write_text(
                f'@echo off\r\n"{sys.executable}" "%~dp0{name}.py" %*\r\n',
                encoding="utf-8")
        else:
            launcher = binv / name
            launcher.write_text(f"#!/bin/sh\nexec {sys.executable} \"$(dirname \"$0\")/{name}.py\" \"$@\"\n",
                                encoding="utf-8")
            launcher.chmod(0o755)
    return binv


def run(cmd: str, runs, head=HEAD) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        binv = fake_bin(tmp, runs, head)
        env = dict(os.environ, PATH=f"{binv}{os.pathsep}{os.environ['PATH']}")
        proc = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                              "tool_input": {"command": cmd}, "cwd": str(tmp)}),
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        try:
            return json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            return {"__unparsable__": proc.stdout}


def verdict(out: dict) -> str:
    hs = out.get("hookSpecificOutput") or {}
    if hs.get("permissionDecision") == "deny":
        return "deny"
    if out.get("systemMessage"):
        return "confirm"
    return "allow"


GREEN = [{"headSha": HEAD, "status": "completed", "conclusion": "success", "workflowName": "ci"}]
RED = [{"headSha": HEAD, "status": "completed", "conclusion": "failure", "workflowName": "ci"}]
PENDING = [{"headSha": HEAD, "status": "in_progress", "conclusion": None, "workflowName": "ci"}]
OTHER = [{"headSha": "b" * 40, "status": "completed", "conclusion": "success", "workflowName": "ci"}]


def main() -> int:
    failures = []
    cases = [
        # (label, command, CI state, expected)
        ("tag after green CI", "git tag -a v1.0.0 -m x", GREEN, "allow"),
        ("tag on failing CI", "git tag -a v1.0.0 -m x", RED, "deny"),
        ("tag while CI runs", "git tag -a v1.0.0 -m x", PENDING, "deny"),
        ("tag push", "git push origin v1.0.0", RED, "deny"),
        ("release create", "gh release create v1.0.0", RED, "deny"),
        # only another commit has a run: the newest row is not your row
        ("only another commit ran", "git tag -a v1.0.0 -m x", OTHER, "confirm"),
        ("gh unavailable", "git tag -a v1.0.0 -m x", None, "confirm"),
        # unrelated commands are untouched
        ("ordinary push", "git push origin main", RED, "allow"),
        ("tag listing", "git tag --list", RED, "allow"),
        ("unrelated command", "ls -al", RED, "allow"),
    ]
    for label, cmd, runs, want in cases:
        got = verdict(run(cmd, runs))
        if got != want:
            failures.append(f"{label}: expected {want}, got {got}")

    for f in failures:
        print("FAIL", f)
    print(f"{len(cases) - len(failures)}/{len(cases)} release-gate checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
