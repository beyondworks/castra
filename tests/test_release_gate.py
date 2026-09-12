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


def fake_env(tmp: pathlib.Path, runs, head=HEAD) -> dict:
    """git 과 gh 를 스크립트로 대체해 환경변수로 주입한다.

    PATH 앞에 셰임을 두는 방식은 Windows 에서 통하지 않는다. CreateProcess 는
    PATHEXT 를 적용하지 않아 .bat 셰임을 건너뛰고 실제 git.exe 를 잡는다.
    실제 저장소나 네트워크에 기대지 않으려면 주입이 유일하게 이식되는 방법이다.
    """
    (tmp / "git.py").write_text(
        "import sys\n"
        f"print({head!r}) if sys.argv[1:3]==['rev-parse','HEAD'] else None\n",
        encoding="utf-8")
    (tmp / "gh.py").write_text(
        "import sys; sys.exit(1)\n" if runs is None
        else f"import json; print(json.dumps({runs!r}))\n",
        encoding="utf-8")
    quote = lambda p: f'"{p}"'  # always quote: an unquoted Windows path loses its separators
    return {
        "CASTRA_GIT_BIN": f"{quote(sys.executable)} {quote(tmp / 'git.py')}",
        "CASTRA_GH_BIN": f"{quote(sys.executable)} {quote(tmp / 'gh.py')}",
    }


def run(cmd: str, runs, head=HEAD) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        env = dict(os.environ, **fake_env(tmp, runs, head))
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
