#!/usr/bin/env python3
"""castra-guardian — guardian_v2 를 실행 계층으로 재현하는 PreToolUse 훅.

정본(gpt-6-astra model_messages.guardian_v2)의 판정 구조를 그대로 옮긴다:

  "Assess the current course of action, the previous five actions, and the
   likely next two actions."
  "Return high if ... any of the previous five actions had unknown
   authorization or critical risk."

정규식 한 줄 매칭이 아니라, 세션 기록(transcript_path)에서 직전 도구 호출을
읽어 이력을 함께 본다. 상태는 파일이 아니라 기록에서 매번 재구성하므로
세션이 바뀌어도 오염되지 않는다.

출력: hookSpecificOutput.permissionDecision = allow | deny
      deny 는 정본의 hand_off(에이전트가 최종 단계를 수행하지 않음)에만 쓴다.
      confirm 등급은 차단하지 않고 사유를 붙여 통과시킨다(권한 UI 가 별도로 있다).
"""
import json, pathlib, re, sys

sys.path.insert(0, str(pathlib.Path.home() / ".castra" / "scripts"))
try:
    from castra_guardian import classify, ORDER
except Exception:
    print(json.dumps({}))
    sys.exit(0)

HISTORY_N = 5          # 정본: previous five actions
STATE = ORDER          # hand_off 3 > confirm_at_action 2 > pre_approval 1 > not_required 0


def recent_commands(transcript: str, limit: int = HISTORY_N):
    """세션 기록에서 최근 Bash 명령 N개를 시간 역순으로 뽑는다."""
    p = pathlib.Path(transcript)
    if not p.exists():
        return []
    out = []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    for line in reversed(lines):
        if len(out) >= limit:
            break
        if '"Bash"' not in line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        for block in _content_blocks(obj):
            if block.get("type") == "tool_use" and block.get("name") == "Bash":
                cmd = (block.get("input") or {}).get("command")
                if cmd:
                    out.append(cmd)
                    break
    return out


def _content_blocks(obj):
    msg = obj.get("message")
    if isinstance(msg, dict):
        c = msg.get("content")
        if isinstance(c, list):
            return [b for b in c if isinstance(b, dict)]
    return []


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        print(json.dumps({})); return

    if payload.get("tool_name") != "Bash":
        print(json.dumps({})); return

    cmd = (payload.get("tool_input") or {}).get("command", "")
    if not cmd.strip():
        print(json.dumps({})); return

    verdict = classify(cmd)
    grade = verdict["verdict"]

    # 이력 반영: 직전 5개 중 hand_off 가 있었으면 경계를 한 단계 올린다
    history = recent_commands(payload.get("transcript_path", ""))
    hist_grades = [classify(c)["verdict"] for c in history]
    escalated = any(STATE[g] >= STATE["hand_off"] for g in hist_grades)

    reasons = "; ".join(r["reason"] for r in verdict["reasons"]) or "패턴 매칭 없음"
    secrets = ", ".join(verdict["secret_risk"])

    if grade == "hand_off":
        msg = f"guardian_v2: hand-off 등급. {reasons}."
        if secrets:
            msg += f" 시크릿 위험: {secrets}."
        msg += " 에이전트가 최종 단계를 수행하지 않는다. 사용자가 직접 실행해야 한다."
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": msg,
            }
        }, ensure_ascii=False))
        return

    if grade == "confirm_at_action" or escalated:
        note = f"guardian_v2: {grade}. {reasons}."
        if secrets:
            note += f" 시크릿 위험: {secrets}."
        if escalated:
            note += " 직전 5개 행동 중 hand-off 등급이 있었다. 경계를 유지하라."
        print(json.dumps({"systemMessage": note}, ensure_ascii=False))
        return

    print(json.dumps({}))


if __name__ == "__main__":
    main()
