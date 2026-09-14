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
        f"print({head!r}) if sys.argv[1]=='rev-parse' else None\n",
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


def run(cmd: str, runs, head=HEAD, mode=None) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        env = dict(os.environ, **fake_env(tmp, runs, head))
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                   "tool_input": {"command": cmd}, "cwd": str(tmp)}
        if mode:
            payload["permission_mode"] = mode
        proc = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        try:
            return json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            return {"__unparsable__": proc.stdout}


def verdict(out: dict) -> str:
    hs = out.get("hookSpecificOutput") or {}
    if hs.get("permissionDecision") == "deny":
        return "deny"
    if hs.get("permissionDecision") == "ask":
        return "confirm"
    if "not prompted" in (hs.get("additionalContext") or ""):
        return "advise"
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
        ("leading gh repo", "gh --repo owner/repo release create v1", GREEN, "confirm"),
        ("push format flag", "git push --porcelain origin v1.0.0", RED, "deny"),
        ("push refspec", "git push origin HEAD:refs/tags/v1.0.0", RED, "deny"),
        ("push explicit tag", "git push origin tag release-2026", RED, "deny"),
        ("global config target uncertain", "git -c core.hooksPath=/tmp/empty tag v1", GREEN, "confirm"),
        ("compound read", "git status; git diff", RED, "allow"),
        ("empty tag listing", "git tag", RED, "allow"),
        ("tag delete is not publication", "git tag -d v1", RED, "allow"),
        ("quoted mention", "echo 'git tag v1'", RED, "allow"),
        ("multiple refs uncertain", "git push origin --tags", GREEN, "confirm"),
        ("target override", "gh release create v1 --target older", RED, "confirm"),
        ("newest rerun wins", "git tag v1", GREEN + RED, "allow"),
        ("latest failed wins", "git tag v1", RED + GREEN, "deny"),
        ("malformed runs", "git tag v1", [42], "confirm"),
    ]
    # A read-only command whose echo label mentions "git tag" opened an approval
    # dialog in a real session. Output-only segments are not publication, but a
    # quoted command that actually executes still is.
    cases += [
        ("echo label in compound read", 'cd x; gh release view v1 -R o/r; echo "== git tag exists?"', RED, "allow"),
        ("printf label in compound read", "git status; printf 'git push origin v1\\n'", RED, "allow"),
        ("echo piped into a shell still counts", 'echo "git tag v1" | bash', GREEN, "confirm"),
        ("bash -c executes its quoted tag", 'cd x; bash -c "git tag v1"', GREEN, "confirm"),
        # A compound led by cd matched every git push, so ordinary branch pushes
        # were read as releases; listings and bare `git tag` were read as creation.
        ("cd then branch push", "cd repo && git push -u origin feature/x", RED, "allow"),
        ("cd then branch push, multi-line", "cd repo\ngit add a.py\ngit push -q -u origin fix/y", RED, "allow"),
        ("cd then tag listing", "cd repo; git tag --list", RED, "allow"),
        ("cd then bare git tag", "cd repo; git tag", RED, "allow"),
        ("cd then tag creation", "cd repo; git tag -a v1.2.3 -m release", GREEN, "confirm"),
        ("cd then tag push", "cd repo && git push origin v1.2.3", GREEN, "confirm"),
        ("cd then push --tags", "cd repo && git push --tags", GREEN, "confirm"),
    ]

    for label, cmd, runs, want in cases:
        got = verdict(run(cmd, runs))
        if got != want:
            failures.append(f"{label}: expected {want}, got {got}")

    # In auto and bypass modes nothing may open a dialog: a would-be "ask" becomes
    # advice to the model. A CI-based "deny" opens no dialog and must survive.
    # dontAsk and the default mode keep asking.
    mode_cases = [
        ("uncertain target, bypass", "git push origin --tags", GREEN, "bypassPermissions", "advise"),
        ("uncertain target, auto", "git push origin --tags", GREEN, "auto", "advise"),
        ("uncertain target, default", "git push origin --tags", GREEN, "default", "confirm"),
        ("uncertain target, dontAsk", "git push origin --tags", GREEN, "dontAsk", "confirm"),
        ("failing CI, bypass still denied", "git tag -a v1.0.0 -m x", RED, "bypassPermissions", "deny"),
        ("pending CI, auto still denied", "git tag -a v1.0.0 -m x", PENDING, "auto", "deny"),
        ("green CI, bypass allowed", "git tag -a v1.0.0 -m x", GREEN, "bypassPermissions", "allow"),
    ]
    for label, cmd, runs, mode, want in mode_cases:
        got = verdict(run(cmd, runs, mode=mode))
        if got != want:
            failures.append(f"{label}: expected {want}, got {got}")
    cases += [(c[0], c[1], c[2], c[4]) for c in mode_cases]

    for f in failures:
        print("FAIL", f)
    print(f"{len(cases) - len(failures)}/{len(cases)} release-gate checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
