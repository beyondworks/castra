#!/usr/bin/env python3
"""castra-release-gate — 태그·발행 직전에 이 커밋의 CI 결과를 직접 본다.

PreToolUse 훅. `git tag`, 태그 푸시, `gh release create` 를 가로채서 현재 HEAD 에
대한 CI 실행을 조회하고, 성공이 아니면 거부한다.

왜 필요한가. v0.5.0 을 3개 OS 검사 결과를 보기 전에 발행했고, 윈도우가 실패한
커밋에 태그가 붙었다. 그때 내가 본 것은 릴리스 워크플로의 리눅스 잡 하나였다.
"발행 전에 검사한다"는 규칙은 이미 있었고, 지키지 못한 것은 기억이 아니라
그 순간에 사실을 보지 않았기 때문이다. 그래서 그 순간에 사실을 보게 만든다.

판정 원칙: 모르면 막지 않고 확인으로 내린다. gh 가 없거나 네트워크가 죽었거나
아직 실행이 등록되지 않은 경우까지 거부하면, 만족시킬 수 없는 관문이 된다.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

# 태그를 만들거나 밀거나, 릴리스를 직접 만드는 명령
TRIGGER = re.compile(
    r"\bgit\s+tag\s+(-a|-s|-m|[^-])"          # git tag -a v1.2.3
    r"|\bgit\s+push\b[^|;]*\b(--tags|refs/tags/|\bv\d)"  # 태그 푸시
    r"|\bgh\s+release\s+create\b")


def tool(name: str) -> list:
    """실행할 명령의 앞부분. 환경변수로 덮어쓸 수 있다.

    훅은 exec 형식으로 실행되므로 사용자의 셸 PATH 를 그대로 물려받지 않는다.
    gh 가 PATH 에 없어 조회가 실패하면 게이트는 매번 확인으로 내려앉는다.
    그래서 CASTRA_GIT_BIN / CASTRA_GH_BIN 으로 실제 경로를 줄 수 있게 둔다.
    값은 인자를 포함해도 된다.
    """
    override = os.environ.get(f"CASTRA_{name.upper()}_BIN")
    if override:
        return shlex.split(override)
    return [shutil.which(name) or name]


def sh(args, cwd, timeout=25):
    try:
        p = subprocess.run(args, cwd=cwd or None, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def decide(cwd: str) -> tuple:
    """(판정, 사유). 판정은 allow / deny / confirm."""
    head = sh(tool("git") + ["rev-parse", "HEAD"], cwd)
    if not head:
        return "confirm", "git 저장소를 확인하지 못했다. 발행 대상 커밋을 직접 확인하라."

    raw = sh(tool("gh") + ["run", "list", "--limit", "25",
              "--json", "headSha,status,conclusion,workflowName"], cwd)
    if raw is None:
        return "confirm", ("이 커밋의 CI 결과를 조회하지 못했다(gh 부재·네트워크·권한). "
                           "검사 결과를 직접 확인한 뒤 진행하라.")
    try:
        runs = [r for r in json.loads(raw) if r.get("headSha") == head]
    except (json.JSONDecodeError, TypeError):
        return "confirm", "CI 조회 결과를 해석하지 못했다. 직접 확인하라."

    if not runs:
        return "confirm", (f"HEAD({head[:8]})에 대한 CI 실행이 아직 없다. "
                           "푸시가 끝났는지, 실행이 등록됐는지 확인하라.")

    pending = [r for r in runs if r.get("status") != "completed"]
    if pending:
        names = ", ".join(sorted({r.get("workflowName", "?") for r in pending}))
        return "deny", (f"HEAD({head[:8]})의 CI가 아직 끝나지 않았다: {names}. "
                        "끝난 뒤 결과를 보고 발행하라. 최신 실행이 아니라 "
                        "이 커밋의 실행인지 해시로 맞춰서 보라.")

    failed = [r for r in runs if r.get("conclusion") != "success"]
    if failed:
        detail = ", ".join(f"{r.get('workflowName','?')}={r.get('conclusion')}" for r in failed)
        return "deny", (f"HEAD({head[:8]})의 CI가 통과하지 않았다: {detail}. "
                        "실패를 고쳐 다시 통과시킨 뒤 발행하라.")

    names = ", ".join(sorted({r.get("workflowName", "?") for r in runs}))
    return "allow", f"HEAD({head[:8]}) CI 통과: {names}"


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return 0

    cmd = str((payload.get("tool_input") or {}).get("command", ""))
    if not TRIGGER.search(cmd):
        return 0

    verdict, reason = decide(payload.get("cwd") or "")
    if verdict == "deny":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "castra-release-gate: " + reason,
        }}))
    elif verdict == "confirm":
        print(json.dumps({"systemMessage": "castra-release-gate: " + reason}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
