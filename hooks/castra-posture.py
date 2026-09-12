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
import hashlib
import json
import pathlib
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import os

HERE = pathlib.Path(__file__).resolve().parent
# CASTRA_HOME is what the installer honours, so the hook has to honour it too;
# otherwise a test or a second install reads a different pack than it writes.
_HOME = pathlib.Path(os.environ.get("CASTRA_HOME") or (pathlib.Path.home() / ".castra"))
CANDIDATES = (
    _HOME / "packs" / "execution-posture-pack.txt",
    HERE.parent / "packs" / "execution-posture-pack.txt",
)

HEADER = """<castra_execution_posture>
아래는 이 세션에 적용되는 실행 태세다. 세션 시작 훅이 넣은 것이며, 따로 파일을
열 필요가 없다. 안전 기준이 이보다 우선한다 — 팩 안 Precedence 절이 정본이다.
"""

FOOTER = """
## What runs on its own

아래는 훅이 알아서 한다. 부르지 않아도 되고, 부를 필요도 없다.

- 되돌리기 어려운 셸 명령은 실행 직전에 등급이 매겨진다. hand-off 면 거부되고,
  확인 등급이면 그 사유가 함께 온다. 분류기는 하한선이며 판단을 대신하지 않는다 —
  등급이 0 이어도 파괴적이라고 보이면 확인을 받는다.
- 코드 파일을 고치면 "실행·검사한 기록이 없음"이 미결로 적힌다. 그 파일을 실제로
  돌리면 지워진다. 미결이 남아 있으면 턴이 끝나지 않는다. 파일을 직접 편집해
  지우지 마라 — 확인하지 않은 것을 확인한 것으로 만드는 일이다.
- 컨텍스트 예산이 임계값에 닿으면 지시가 들어온다.

손으로 해야 하는 것은 하나뿐이다. 여러 창에 걸치거나 중단 후 재개할 작업이면
진행하면서 기록한다.

    python3 ~/.castra/scripts/castra_notes.py checkpoint --goal ... --progress ... --next ...

새 창에서 이어받을 때는 `read` 가 첫 명령이다.
</castra_execution_posture>"""


def drift_notice() -> str:
    """설치본이 정본보다 낡았으면 그 사실을 한 줄로 돌려준다.

    설치 시 남긴 manifest 의 해시를 원본 저장소의 현재 파일과 비교한다.
    실제로 태세 훅이 옛 팩을 읽는 동안 검사는 저장소 팩을 대조하고 있었고,
    두 판본이 다르다는 사실이 우연히 발견되기 전까지 드러나지 않았다.
    저장소가 이 기계에 없으면 조용히 넘어간다.
    """
    try:
        manifest = json.loads((_HOME / "manifest.json").read_text(encoding="utf-8"))
        source = pathlib.Path(manifest["source"])
        recorded = manifest["files"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return ""
    if not source.is_dir():
        return ""
    stale = []
    for rel, want in recorded.items():
        origin = source / rel
        try:
            got = hashlib.sha256(origin.read_bytes()).hexdigest()[:16]
        except OSError:
            continue
        if got != want:
            stale.append(rel)
    if not stale:
        return ""
    return ("\n[castra] 설치본이 정본보다 낡았다: " + ", ".join(sorted(stale)) +
            f"\n[castra] 지금 읽은 내용은 옛 판본이다. `python3 {source}/install.py` 로 맞춰라.\n")


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
    notice = drift_notice()
    if notice:
        print(notice)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
