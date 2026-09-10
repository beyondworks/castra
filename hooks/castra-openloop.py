#!/usr/bin/env python3
"""castra-openloop — persistent_instructions 를 실행 계층으로 재현하는 Stop 훅.

정본(gpt-6-astra model_messages.persistent_instructions):

  "Because a `final` answer immediately ends the turn, use
   send_user_message_async to deliver answers while useful work remains.
   Only send a `final` message after concluding that no follow-up or
   proactive work could be a useful continuation."

이 하네스에는 send_user_message_async 가 없어 최종 답변이 곧 턴 종료다.
그래서 반대 방향으로 구현한다: 열린 루프가 남아 있으면 Stop 을 막는다.

열린 루프의 근거는 추측이 아니라 파일이다. 작업 디렉터리의
.castra/openloops 에 한 줄씩 적힌 항목이 있으면 턴을 끝내지 않는다.
닫을 때는 해당 줄을 지운다. 파일이 없거나 비면 정상 종료한다.

무한 루프 방지: 같은 프롬프트에서 연속 차단은 MAX_BLOCK 회로 제한한다.
"""
import json
import os
import pathlib
import sys

MAX_BLOCK = 2
COUNTER = ".castra/.stop_blocks"


def loops_file(cwd):
    base = pathlib.Path(cwd)
    new_dir, old_dir = base / ".castra", base / ".astra"
    root = old_dir if (not new_dir.exists() and old_dir.exists()) else new_dir
    return root / "openloops"


def read_loops(path):
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        print(json.dumps({}))
        return

    cwd = payload.get("cwd") or os.getcwd()
    prompt_id = payload.get("prompt_id") or ""
    lf = loops_file(cwd)
    loops = read_loops(lf)

    if not loops:
        print(json.dumps({}))
        return

    counter_path = pathlib.Path(cwd) / COUNTER
    prev_id, count = "", 0
    if counter_path.exists():
        try:
            prev_id, raw = counter_path.read_text(encoding="utf-8").split("\n", 1)
            count = int(raw.strip() or 0)
        except Exception:
            prev_id, count = "", 0
    count = count + 1 if prev_id == prompt_id else 1
    counter_path.parent.mkdir(parents=True, exist_ok=True)
    counter_path.write_text(prompt_id + "\n" + str(count), encoding="utf-8")

    if count > MAX_BLOCK:
        msg = (
            "열린 루프 " + str(len(loops)) + "건이 남아 있으나 연속 차단 한도("
            + str(MAX_BLOCK) + ")에 도달해 종료를 허용한다. 남은 항목: "
            + "; ".join(loops[:3])
        )
        print(json.dumps({"systemMessage": msg}, ensure_ascii=False))
        return

    items = "\n".join("  - " + l for l in loops)
    reason = (
        "열린 루프가 " + str(len(loops)) + "건 남아 있다. 턴을 끝내기 전에 처리하라.\n"
        + items
        + "\n\n각 항목은 알려진 미결을 닫거나, 기다리던 결과를 확정하거나, 변경이 "
        "실제로 반영됐는지 확인하는 일이다. 처리한 항목은 "
        + str(lf)
        + " 에서 해당 줄을 지워라. 지금 당장 할 일이 없다는 것은 끝낼 이유가 못 된다. "
        "새 권한이 필요하면 그것만 요청하고 나머지는 진행하라."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "shouldContinue": True,
            "reason": reason,
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
