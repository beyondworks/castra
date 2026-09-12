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
    (binv / "git").write_text(
        "#!/usr/bin/env python3\nimport sys\n"
        f"print({head!r}) if sys.argv[1:3]==['rev-parse','HEAD'] else None\n",
        encoding="utf-8")
    if runs is None:
        body = "import sys; sys.exit(1)"
    else:
        body = f"import json; print(json.dumps({runs!r}))"
    (binv / "gh").write_text(f"#!/usr/bin/env python3\n{body}\n", encoding="utf-8")
    for f in binv.iterdir():
        f.chmod(0o755)
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
        # (설명, 명령, CI 상태, 기대)
        ("CI 통과 후 태그", "git tag -a v1.0.0 -m x", GREEN, "allow"),
        ("CI 실패인데 태그", "git tag -a v1.0.0 -m x", RED, "deny"),
        ("CI 진행 중인데 태그", "git tag -a v1.0.0 -m x", PENDING, "deny"),
        ("태그 푸시", "git push origin v1.0.0", RED, "deny"),
        ("릴리스 직접 생성", "gh release create v1.0.0", RED, "deny"),
        # 다른 커밋의 실행만 있는 경우: 최신 실행을 내 것으로 착각하지 않는다
        ("다른 커밋 실행만 있음", "git tag -a v1.0.0 -m x", OTHER, "confirm"),
        ("gh 사용 불가", "git tag -a v1.0.0 -m x", None, "confirm"),
        # 관계없는 명령은 건드리지 않는다
        ("일반 푸시", "git push origin main", RED, "allow"),
        ("목록 조회", "git tag --list", RED, "allow"),
        ("무관한 명령", "ls -al", RED, "allow"),
    ]
    for label, cmd, runs, want in cases:
        got = verdict(run(cmd, runs))
        if got != want:
            failures.append(f"{label}: {want} 기대, {got} 나옴")

    for f in failures:
        print("FAIL", f)
    print(f"{len(cases) - len(failures)}/{len(cases)} release-gate checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
