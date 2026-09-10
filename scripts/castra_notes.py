#!/usr/bin/env python3
"""castra_notes — Astra의 notes/history/get_context_remaining 대체.

컨텍스트 창을 넘겨도 살아남는 체크포인트를 파일로 유지한다.
상태는 작업 디렉터리의 .astra/ 아래에 둔다(goals.py의 .fablize/와 같은 규약).

  checkpoint  목표·결정·진행·학습·다음단계를 한 항목으로 추가
  read        현재 체크포인트 전체를 출력 (컨텍스트 리셋 후 첫 명령)
  budget      대화 기록의 토큰 사용량을 추정해 잔여 예산을 알려준다
  search      과거 체크포인트에서 키워드로 찾는다
"""
import argparse, json, os, pathlib, subprocess, sys, time

def _state_root():
    """상태 폴더. .castra 를 쓰되, 이전 이름(.astra)이 이미 있으면 그것을 이어 쓴다."""
    env = os.environ.get("CASTRA_NOTES_DIR") or os.environ.get("ASTRA_NOTES_DIR")
    if env:
        return pathlib.Path(env)
    cwd = pathlib.Path.cwd()
    new_dir, old_dir = cwd / ".castra", cwd / ".astra"
    if not new_dir.exists() and old_dir.exists():
        return old_dir
    return new_dir


ROOT = _state_root()
NOTES = ROOT / "notes.jsonl"


def _ensure():
    ROOT.mkdir(parents=True, exist_ok=True)
    NOTES.touch(exist_ok=True)


def _entries():
    if not NOTES.exists():
        return []
    out = []
    for line in NOTES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def cmd_checkpoint(a):
    _ensure()
    entry = {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%d %H:%M:%S"),
        "goal": a.goal,
        "decision": a.decision,
        "progress": a.progress,
        "learned": a.learned,
        "next": a.next,
        "window": a.window,
    }
    with NOTES.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"checkpoint saved  seq={len(_entries())}  file={NOTES}")


def cmd_read(a):
    es = _entries()
    if not es:
        print("no checkpoints yet")
        return
    show = es if a.all else es[-a.limit:]
    print(f"# checkpoints {len(show)}/{len(es)}  ({NOTES})")
    for i, e in enumerate(show, start=len(es) - len(show) + 1):
        print(f"\n## [{i}] {e.get('iso','')}  window={e.get('window') or '-'}")
        for k in ("goal", "decision", "progress", "learned", "next"):
            v = e.get(k)
            if v:
                print(f"  {k}: {v}")


def cmd_search(a):
    q = a.query.lower()
    hits = [(i, e) for i, e in enumerate(_entries(), 1)
            if q in json.dumps(e, ensure_ascii=False).lower()]
    if not hits:
        print(f"no match: {a.query}")
        return
    print(f"# {len(hits)} match")
    for i, e in hits:
        print(f"\n## [{i}] {e.get('iso','')}")
        for k in ("goal", "decision", "progress", "learned", "next"):
            if e.get(k):
                print(f"  {k}: {e[k]}")


_USAGE_FIELDS = ("input_tokens", "cache_read_input_tokens",
                 "cache_creation_input_tokens", "output_tokens")


def read_window_usage(path: pathlib.Path) -> int:
    """기록에 남은 마지막 usage 값에서 현재 창 점유량을 읽는다.

    Claude Code 는 어시스턴트 턴마다 message.usage 를 남긴다. 그중 마지막 값의
    input + cache_read + cache_creation + output 합이 그 시점의 창 점유량이다.
    usage 가 없는 기록이면 0 을 돌려주고, 호출한 쪽이 근사치로 대체한다.
    """
    if not path.exists():
        return 0
    last = None
    try:
        fh = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    with fh:
        for line in fh:
            try:
                usage = (json.loads(line).get("message") or {}).get("usage")
            except Exception:
                continue
            if usage:
                last = usage
    if not last:
        return 0
    return sum(last.get(k) or 0 for k in _USAGE_FIELDS)


WINDOW_CACHE = pathlib.Path.home() / ".claude" / ".castra-windows.json"
KNOWN_WINDOWS = (200_000, 1_000_000)


def last_model(path: pathlib.Path) -> str:
    """기록에 남은 마지막 모델 이름."""
    if not path.exists():
        return ""
    name = ""
    try:
        fh = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    with fh:
        for line in fh:
            try:
                m = (json.loads(line).get("message") or {}).get("model")
            except Exception:
                continue
            if m and not m.startswith("<"):
                name = m
    return name


def detect_window(path: pathlib.Path, default: int = 200_000) -> tuple:
    """모델별 관측 최대 점유량으로 창 크기를 추정한다.

    창 크기를 직접 알려주는 값은 기록에 없다. 대신 그 모델이 실제로 얼마나
    차지한 적이 있는지를 보면 하한이 나온다. 90만 토큰을 채운 적이 있으면
    20만 창일 수 없다. 관측치는 홈의 .castra-windows.json 에 모델별로 쌓아
    다음 세션에서 다시 쓴다. 돌려주는 값은 (창 크기, 근거) 짝이다.
    """
    model = last_model(path)
    cache = {}
    try:
        cache = json.loads(WINDOW_CACHE.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    peak = read_window_usage(path)
    if model:
        prior = cache.get(model) or 0
        if peak > prior:
            cache[model] = peak
            try:
                WINDOW_CACHE.parent.mkdir(parents=True, exist_ok=True)
                WINDOW_CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
            except OSError:
                pass
        peak = max(peak, prior)
    if not peak:
        return default, "관측치 없음, 기본값"
    for w in KNOWN_WINDOWS:
        if peak <= w:
            return w, f"{model or '모델 불명'} 관측 최대 {peak:,}"
    return KNOWN_WINDOWS[-1], f"{model or '모델 불명'} 관측 최대 {peak:,} (최대 창 초과)"


def _count_tokens(path: pathlib.Path, tail_lines: int = 0) -> int:
    """대화 기록(jsonl)의 토큰 사용량.

    usage 기록이 있으면 그 값을 쓴다. 실제 창 점유량이라 근사치보다 정확하다.
    usage 가 없는 기록에서만 문자수/3.5 근사로 물러선다. 이때 tail_lines>0 이면
    마지막 N줄만 센다. 세션 파일에는 컨텍스트 압축으로 이미 창에서 빠진 과거
    기록까지 누적되므로, 전체를 세면 현재 창 사용량을 크게 넘는 값이 나온다.
    """
    if not path.exists():
        return 0
    exact = read_window_usage(path)
    if exact:
        return exact
    if tail_lines <= 0:
        return int(len(path.read_text(encoding="utf-8", errors="replace")) / 3.5)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return int(sum(len(l) for l in lines[-tail_lines:]) / 3.5)


def cmd_budget(a):
    total = a.window
    used = 0
    src = "none"
    exact = False
    if a.transcript:
        p = pathlib.Path(a.transcript).expanduser()
        used = _count_tokens(p, a.tail)
        exact = bool(read_window_usage(p))
        how = "usage 실측" if exact else (
            f"문자수 근사, tail {a.tail}줄" if a.tail else "문자수 근사, 전체")
        src = f"{p} ({how})"
    remaining = total - used
    pct = (remaining / total * 100) if total else 0
    if remaining < 0:
        print("WARN: 추정 사용량이 창 크기를 넘었다. 세션 파일에 압축으로 빠진")
        print("      과거 기록이 누적된 경우다. --tail 로 최근 구간만 세라.\n")
    print(f"context_window : {total:,}")
    print(f"estimated_used : {used:,}   (source: {src})")
    print(f"remaining      : {remaining:,}  ({pct:.1f}%)")
    if pct < 20:
        print("ACTION: 예산이 20% 미만이다. 지금 checkpoint 를 남겨라.")
    elif pct < 40:
        print("NOTE: 40% 미만. 다음 큰 작업 전에 checkpoint 를 권한다.")
    if exact:
        print("\nnote: 기록의 마지막 usage 값을 읽은 실측치다. 창 크기(--window)는 "
              "여전히 가정값이므로 잔여 비율은 그만큼만 믿어라.")
    else:
        print("\nnote: usage 기록이 없어 문자수/3.5 근사로 계산했다. "
              "정확한 값이 아니라 예산 신호로만 써라.")


def main():
    p = argparse.ArgumentParser(prog="castra_notes", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("checkpoint", help="체크포인트 추가")
    for f in ("goal", "decision", "progress", "learned", "next"):
        c.add_argument(f"--{f}", default="")
    c.add_argument("--window", default="", help="컨텍스트 창 식별자(선택)")
    c.set_defaults(func=cmd_checkpoint)

    r = sub.add_parser("read", help="체크포인트 읽기")
    r.add_argument("--limit", type=int, default=3)
    r.add_argument("--all", action="store_true")
    r.set_defaults(func=cmd_read)

    s = sub.add_parser("search", help="체크포인트 검색")
    s.add_argument("query")
    s.set_defaults(func=cmd_search)

    b = sub.add_parser("budget", help="잔여 컨텍스트 예산 추정")
    b.add_argument("--window", type=int, default=1000000)
    b.add_argument("--transcript", default="", help="대화 기록 jsonl 경로")
    b.add_argument("--tail", type=int, default=0,
                   help="마지막 N줄만 계산(압축 이후 구간 추정). 0=전체")
    b.set_defaults(func=cmd_budget)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
