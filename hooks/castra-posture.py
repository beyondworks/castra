#!/usr/bin/env python3
"""castra-posture — 실행 태세 팩을 세션 시작 시 컨텍스트에 직접 넣는다.

SessionStart 훅. 평문을 stdout 으로 내보내면 그대로 모델의 컨텍스트가 된다.

왜 이렇게 하는가. 원래는 CLAUDE.md 에 "이 팩을 따른다"는 한 줄과 파일 경로만
두었다. 실측해 보니 그 파일을 실제로 여는 세션이 없었다. 규칙이 주입된 세션
10개 중 팩을 읽은 세션은 0개였다. 읽으라고 적어 두는 방식은 실패했으므로,
읽지 않아도 되도록 내용을 먼저 넣는다.

매처를 두지 않아 startup·resume·clear·compact·fork 에서 모두 실행된다.
압축 직후가 특히 중요하다. 압축은 앞 내용을 요약으로 갈아치우므로 팩이
사라지는데, 그 시점에 다시 넣어야 태세가 유지된다.

비용은 약 8,600 토큰이다. 요약본을 넣는 선택지도 있었으나, 요약은 이미
CLAUDE.md 에 있었고 그것으로는 동작하지 않는다는 것이 측정으로 드러났다.
"""
import pathlib
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

HERE = pathlib.Path(__file__).resolve().parent
CANDIDATES = (
    pathlib.Path.home() / ".castra" / "packs" / "execution-posture-pack.txt",
    HERE.parent / "packs" / "execution-posture-pack.txt",
)

HEADER = """<castra_execution_posture>
아래는 이 세션에 적용되는 실행 태세다. 세션 시작 훅이 넣은 것이며, 따로 파일을
열 필요가 없다. 안전 기준이 이보다 우선한다 — 팩 안 Precedence 절이 정본이다.
"""

FOOTER = """
## Operative commands

이 태세를 실제로 쓰려면 아래 세 가지를 직접 호출해야 한다. 규칙으로만 적어
두었을 때 호출률이 0 이었으므로 명령을 여기에 그대로 둔다.

- 여러 창에 걸치거나 중단 후 재개할 작업이면, 진행하면서 기록한다.
  `python3 ~/.castra/scripts/castra_notes.py checkpoint --goal ... --progress ... --next ...`
  새 창에서 이어받을 때는 `read` 가 첫 명령이다.
- 되돌리기 어려운 셸 명령을 실행하기 직전에 등급을 확인한다.
  `python3 ~/.castra/scripts/castra_guardian.py "<명령>"`
  exit 3 은 사용자가 직접, 2 는 실행 직전 확인, 0 은 진행이다. 이 분류기는
  하한선이며 판단을 대신하지 않는다.
- 턴 안에 끝내지 못한 일이 생기면 한 줄로 적는다.
  `echo "<항목>" >> .castra/openloops`
  미확인 결과, 반영 여부를 못 본 변경, 기다리는 중인 것이 여기 해당한다.
  처리하면 그 줄을 지운다. 적지 않으면 Stop 훅은 막을 것이 없다.
</castra_execution_posture>"""


def main() -> int:
    pack = next((p for p in CANDIDATES if p.is_file()), None)
    if pack is None:
        return 0
    try:
        body = pack.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return 0
    if not body:
        return 0
    print(HEADER)
    print(body)
    print(FOOTER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
