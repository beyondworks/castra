#!/usr/bin/env python3
"""castra-trace — 미결 항목을 도구 사용에서 직접 적는다.

PostToolUse 훅. 코드 파일을 고치면 "고쳤으나 동작을 본 적 없음"을 미결로
남기고, 그 파일이 실제로 실행·검사된 흔적이 보이면 그 줄을 지운다.

왜 이렇게 바꿨는가. 이전 설계는 모델에게 `.castra/openloops` 에 직접 적으라고
지시했다. 실측 결과 그 호출은 0회였고, 그래서 Stop 훅은 막을 것이 없었다.
모델이 적어 주기로 한 파일에 의존하는 설계는 그 자체가 실패 지점이다.

여기서는 입력이 항상 존재한다. 도구 호출은 반드시 일어나고, 훅은 그 입력을
그대로 받는다. 적는 주체와 읽는 주체가 모두 훅이므로 빠질 구멍이 없다.
"""
import json
import os
import pathlib
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

# 고쳐 놓고 안 돌려 보면 곤란한 것들. 문서·설정은 넣지 않는다 —
# 막을 이유가 없는 항목으로 턴을 막으면 관문 자체가 무시당한다.
CODE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go",
                 ".rb", ".sh", ".bash", ".zsh", ".java", ".kt", ".swift", ".c", ".cpp"}
PREFIX = "미검증 변경: "

# 무언가를 실제로 돌린 흔적. 이 중 하나가 그 파일을 가리키면 확인된 것으로 본다.
RUNNERS = re.compile(
    r"\b(pytest|python3?|node|deno|bun|cargo|go|ruby|bash|sh|zsh|make|npm|pnpm|yarn|"
    r"jest|vitest|mocha|rspec|gradle|mvn|swift|dotnet)\b")


def state_dir(cwd: str) -> pathlib.Path:
    base = pathlib.Path(cwd) if cwd else pathlib.Path.cwd()
    new, old = base / ".castra", base / ".astra"
    return old if (not new.exists() and old.exists()) else new


def read_lines(path: pathlib.Path) -> list:
    if not path.exists():
        return []
    try:
        return [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return []


def write_lines(path: pathlib.Path, lines: list) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if lines:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        elif path.exists():
            path.unlink()
    except OSError:
        pass


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0

    tool = payload.get("tool_name") or ""
    inp = payload.get("tool_input") or {}
    loops = state_dir(payload.get("cwd") or "")/"openloops"
    lines = read_lines(loops)

    if tool in ("Edit", "Write", "NotebookEdit"):
        raw = inp.get("file_path") or inp.get("notebook_path") or ""
        p = pathlib.Path(str(raw))
        if p.suffix.lower() not in CODE_SUFFIXES:
            return 0
        entry = PREFIX + str(p) + " — 고친 뒤 실행·검사한 기록이 없다"
        if entry not in lines:
            lines.append(entry)
            write_lines(loops, lines)
        return 0

    if tool == "Bash":
        cmd = str(inp.get("command", ""))
        if not RUNNERS.search(cmd):
            return 0
        # 이 명령이 가리키는 파일의 미결을 지운다. 경로 전체든 파일명이든 맞으면 된다.
        kept = []
        for line in lines:
            if line.startswith(PREFIX):
                target = line[len(PREFIX):].split(" — ")[0]
                name = pathlib.Path(target).name
                if target in cmd or name in cmd:
                    continue
            kept.append(line)
        if len(kept) != len(lines):
            write_lines(loops, kept)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
