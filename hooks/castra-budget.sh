#!/bin/bash
# castra-budget — Astra 의 token_budget 런타임 주입 재현.
#
# Astra 는 임계값에 도달하면 <context_window_reminder> 를 주입한다.
# 정적 규칙으로는 재현이 안 되므로 UserPromptSubmit 훅에서 예산을 재고
# 두 단계 임계값에 걸리면 지시문을 stdout 으로 주입한다.
#
# 정본 임계값 (gpt-6-astra model_messages.token_budget):
#   reminder_threshold_tokens            = 6144
#   auto_compact_fallback_buffer_tokens  = 16384
# 정본은 "남은 토큰" 기준이다. 여기서는 창 크기를 알 수 없으므로
# 잔여 비율로 환산해 같은 시점에 걸리도록 맞춘다.
#
# 2026-09-10 수정: 점유량 추정을 글자 수에서 기록의 usage 값으로 바꿨다.
#   이전 방식은 마지막 80줄의 글자 수만 셌기 때문에 점유량이 항상 0 에 가깝게
#   나왔고, 그 결과 어떤 세션에서도 임계값에 도달하지 못했다.

set -uo pipefail

WINDOW="${CASTRA_CONTEXT_WINDOW:-0}"   # 0 이면 기록에서 자동 감지한다
NOTES="$HOME/.castra/scripts/castra_notes.py"
[ -f "$NOTES" ] || exit 0

INPUT=$(cat 2>/dev/null || true)

# 훅 입력에 담긴 transcript_path 를 우선 쓰고, 없을 때만 최근 기록으로 대체한다.
TRANSCRIPT=$(printf '%s' "$INPUT" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("transcript_path") or "")
except Exception: print("")' 2>/dev/null)
if [ -z "$TRANSCRIPT" ] || [ ! -f "$TRANSCRIPT" ]; then
  TRANSCRIPT=$(ls -t "$HOME/.claude/projects/"*/*.jsonl 2>/dev/null | head -1)
fi
[ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ] || exit 0

# 점유량은 기록에 남은 마지막 usage 값에서 읽는다.
# input + cache_read + cache_creation + output 의 합이 그 시점의 창 점유량이다.
# 계산 본체는 castra_notes.read_window_usage 하나만 두고 여기서는 불러다 쓴다.
# 창 크기도 같은 자리에서 정한다. 기록의 모델 이름과 그 모델이 실제로
# 차지한 적 있는 최대치를 근거로 삼는다(castra_notes.detect_window).
READING=$(python3 -c 'import sys, pathlib
sys.path.insert(0, sys.argv[1])
import castra_notes as n
p = pathlib.Path(sys.argv[2])
print(n.read_window_usage(p), n.detect_window(p)[0])' \
  "$(dirname "$NOTES")" "$TRANSCRIPT" 2>/dev/null)
[ -n "$READING" ] || exit 0
USED=${READING% *}
DETECTED=${READING#* }
[ "$USED" -gt 0 ] 2>/dev/null || exit 0
[ "$WINDOW" -gt 0 ] 2>/dev/null || WINDOW="$DETECTED"
[ "$WINDOW" -gt 0 ] 2>/dev/null || exit 0

REMAIN=$(( WINDOW - USED ))

# 정본 임계값을 비율로 환산: 6144/272000 ≈ 2.3%, 16384/272000 ≈ 6.0%
WARN=$(( WINDOW * 6 / 100 ))
CRIT=$(( WINDOW * 2 / 100 ))

if [ "$REMAIN" -le "$CRIT" ]; then
  cat <<MSG
<context_window_reminder>
현재 컨텍스트 창이 사실상 고갈됐다(추정 잔여 ${REMAIN} 토큰). 이 창에서 작업을 계속하거나 최종 답변을 작성하지 마라.
지금 castra_notes.py checkpoint 를 정확히 한 번 호출해 목표·결정·진행·학습·다음단계와 아직 처리 중인 사용자 요청을 기록하라.
기록이 끝나면 그 사실만 알리고 새 창에서 이어가라. 잘린 답변보다 깨끗한 인계가 낫다.
</context_window_reminder>
MSG
elif [ "$REMAIN" -le "$WARN" ]; then
  cat <<MSG
<context_window_reminder>
컨텍스트 예산이 얼마 남지 않았다(추정 잔여 ${REMAIN} 토큰). 다음 큰 작업을 시작하기 전에
castra_notes.py checkpoint 로 현재 상태를 남겨라. 오래된 항목은 정리하라.
</context_window_reminder>
MSG
fi
exit 0
