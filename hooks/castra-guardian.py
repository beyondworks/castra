#!/usr/bin/env python3
"""PreToolUse command-risk floor using documented permission decisions.

This is a local heuristic, not a model policy replica or authorization oracle.
"""
import json, pathlib, re, sys, os

# Windows consoles default to a legacy code page, so any non-ASCII byte written
# here raises UnicodeEncodeError and the hook dies without output — which looks
# exactly like a hook that decided to do nothing. Force UTF-8, and escape
# non-ASCII in the JSON as well so the output survives either way.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

# In these modes the user has chosen not to be interrupted. A hook returning
# "ask" is the one thing that still opens an approval dialog there, and across
# 356 sessions every such dialog was approved and the command ran unchanged, so
# the prompt cost attention without changing a single result. The reason goes
# to the model as context instead. A "deny" opens no dialog and is kept.
# dontAsk is left out on purpose: there an "ask" becomes a denial, which is
# the strict behaviour that mode exists for.
NO_PROMPT_MODES = {"auto", "bypassPermissions"}


def confirmation(payload, reason):
    """ask 판정을 권한 모드에 맞춰 낸다. 창을 띄우지 않는 모드면 참고로만 알린다."""
    mode = payload.get("permission_mode") if isinstance(payload, dict) else None
    if mode in NO_PROMPT_MODES:
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": f"Castra advisory, not prompted in {mode} mode: {reason}",
        }}
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "ask",
        "permissionDecisionReason": reason,
    }}


HERE = pathlib.Path(__file__).resolve().parent
for candidate in (HERE.parent / "scripts", pathlib.Path(os.environ.get("CASTRA_HOME") or pathlib.Path.home() / ".castra") / "scripts"):
    if (candidate / "castra_guardian.py").is_file():
        sys.path.insert(0, str(candidate))
        break
try:
    from castra_guardian import classify, ORDER
except ImportError:
    try:
        _payload = json.load(sys.stdin)
    except Exception:
        _payload = {}
    print(json.dumps(confirmation(_payload, "Castra classifier unavailable; inspect installation before risky execution.")))
    sys.exit(0)

HISTORY_N = 5          # bounded local history, advisory only
STATE = ORDER          # hand_off 3 > confirm_at_action 2 > pre_approval 1 > not_required 0


def recent_commands(transcript: str, limit: int = HISTORY_N):
    """세션 기록에서 최근 Bash 명령 N개를 시간 역순으로 뽑는다."""
    p = pathlib.Path(transcript)
    if not p.exists():
        return []
    out = []
    try:
        with p.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - 262144))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
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

    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        print(json.dumps({})); return

    inp = payload.get("tool_input")
    cmd = inp.get("command", "") if isinstance(inp, dict) else ""
    if not isinstance(cmd, str):
        print(json.dumps({})); return
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
        msg = f"castra-guardian: hand-off 등급. {reasons}."
        if secrets:
            msg += f" 시크릿 위험: {secrets}."
        msg += " 에이전트가 최종 단계를 수행하지 않는다. 사용자가 직접 실행해야 한다."
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": msg,
            }
        }))
        return

    if grade == "confirm_at_action":
        print(json.dumps(confirmation(payload,
            f"castra-guardian: {reasons}. Use the platform's permission decision for this exact action.")))
        return
    if grade == "pre_approval" or escalated:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": "Castra risk advisory: retain specific existing user authorization; this heuristic does not grant it. " + reasons,
        }}))
        return

    print(json.dumps({}))


if __name__ == "__main__":
    main()
