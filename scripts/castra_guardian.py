#!/usr/bin/env python3
"""Local command classifier: known hazardous patterns and authorization reminders.

A heuristic floor, not a sandbox, full shell parser, or model policy replica.
Exit codes: 0 ordinary; 1 existing authority required; 2 platform confirmation; 3 deny.
"""
import argparse, json, re, sys

# (정규식, 등급, 사유) — 위에서부터 먼저 맞는 것이 이긴다
RULES = [
    # hand_off: 에이전트가 최종 실행을 하지 않는다
    (r"\bgit\s+push\b.*(--force\b|-f\b)",        "hand_off", "강제 푸시는 원격 히스토리를 되돌릴 수 없게 덮어쓴다"),
    (r"\bgit\s+filter-(repo|branch)\b",          "hand_off", "히스토리 재작성"),
    (r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b",      "hand_off", "스키마 삭제"),
    (r"\bTRUNCATE\s+TABLE\b",                    "hand_off", "테이블 전체 삭제"),
    (r"\b(mkfs|fdisk|diskutil\s+erase)\b",       "hand_off", "디스크 포맷"),
    (r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\s+/(\s|$)", "hand_off", "루트 삭제"),
    (r"\b(passwd|security\s+add-generic-password)\b", "hand_off", "자격증명 변경"),

    # confirm_at_action: 미리 승인받았어도 실행 시점에 다시 확인
    (r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?\b",         "confirm_at_action", "재귀 삭제는 복구가 어렵다"),
    (r"\bgit\s+reset\s+--hard\b",                "confirm_at_action", "미커밋 변경 소실"),
    (r"\bgit\s+clean\s+-[a-zA-Z]*[fd]",          "confirm_at_action", "추적되지 않은 파일 삭제"),
    (r"\bDELETE\s+FROM\b(?!.*\bWHERE\b)",        "confirm_at_action", "WHERE 없는 DELETE"),
    (r"\bUPDATE\b(?!.*\bWHERE\b).*\bSET\b",      "confirm_at_action", "WHERE 없는 UPDATE"),
    (r"curl[^|]*\|\s*(sudo\s+)?(ba)?sh",         "confirm_at_action", "원격 스크립트 즉시 실행"),
    (r"\bsudo\b",                                "confirm_at_action", "권한 상승"),
    (r"\bchmod\s+(-R\s+)?777\b",                 "confirm_at_action", "권한 전면 개방"),
    (r"\b(launchctl|systemctl)\s+(disable|unload)\b", "confirm_at_action", "서비스 비활성화"),
    (r"\btccutil\s+reset\b",                     "confirm_at_action", "보안 권한 초기화"),
    (r"\bnpm\s+publish\b|\bgh\s+release\s+create\b", "confirm_at_action", "외부 배포"),

    # pre_approval: 세션에서 구체적으로 승인했으면 진행
    (r"\bgit\s+push\b",                          "pre_approval", "원격 반영"),
    (r"\bgh\s+pr\s+(create|merge)\b",            "pre_approval", "PR 생성·병합"),
    (r"\b(mail|sendmail|slack)\b.*\bsend\b",     "pre_approval", "외부 발송"),
    (r"\bbrew\s+(install|upgrade)\b|\bnpm\s+i(nstall)?\s+-g\b", "pre_approval", "소프트웨어 설치"),
    (r"\bdocker\s+(rm|rmi|system\s+prune)\b",    "pre_approval", "컨테이너·이미지 삭제"),
    (r"\bgit\s+(commit|add)\b",                  "pre_approval", "커밋"),

    # 시크릿 노출 — security.md: .env 계열은 읽어서 출력 금지
    (r"\b(cat|less|more|head|tail|bat|open|grep|rg)\b[^|;]*\.env(\.|\b)",
     "hand_off", "security.md: .env 파일은 읽어서 출력하지 않는다"),
    (r"\b(cat|less|more|head|tail|bat)\b[^|;]*\b(id_rsa|\.pem|credentials)\b",
     "hand_off", "비밀키·자격증명 출력"),
    (r"\bgit\s+add\s+(\.|-A|--all)(\s|$)",
     "confirm_at_action", "security.md: git add . / -A 금지, 파일을 명시하라"),

    # PowerShell — 윈도우에서 Git Bash 가 없으면 셸이 PowerShell 로 떨어진다.
    # 같은 위험이 전혀 다른 표기로 들어오므로 POSIX 규칙이 하나도 걸리지 않는다.
    (r"\bFormat-Volume\b|\bClear-Disk\b|\bInitialize-Disk\b",
     "hand_off", "디스크 포맷"),
    (r"\bSet-ExecutionPolicy\b",
     "hand_off", "스크립트 실행 정책 변경"),
    (r"\bRemove-Item\b[^|;]*(-Recurse|-r\b)[^|;]*(-Force|-f\b)|"
     r"\bRemove-Item\b[^|;]*(-Force|-f\b)[^|;]*(-Recurse|-r\b)",
     "confirm_at_action", "재귀 삭제는 복구가 어렵다"),
    (r"\b(iwr|irm|Invoke-WebRequest|Invoke-RestMethod)\b[^|;]*\|\s*(iex|Invoke-Expression)\b",
     "confirm_at_action", "원격 스크립트 즉시 실행"),
    (r"\bStop-(Service|Process)\b|\bSet-Service\b[^|;]*-StartupType\s+Disabled\b",
     "confirm_at_action", "서비스·프로세스 중단"),
    (r"\bStart-Process\b[^|;]*-Verb\s+RunAs\b",
     "confirm_at_action", "권한 상승"),
    (r"\b(Get-Content|type|gc)\b[^|;]*\.env(\.|\b)",
     "hand_off", "security.md: .env 파일은 읽어서 출력하지 않는다"),
]

# 시크릿 노출 위험 (등급과 별개로 항상 경고)
SECRET_HINTS = [
    (r"\.env\b",                       "환경변수 파일"),
    (r"\b(sk|re|npg|ghp|xox[baprs])[-_][A-Za-z0-9]{8,}", "API 키 형태 문자열"),
    (r"postgres(ql)?://[^\s]+:[^\s]+@", "DB 접속 문자열"),
    (r"\bcat\b.*\b(id_rsa|\.pem|credentials)\b", "비밀키 출력"),
]

ORDER = {"hand_off": 3, "confirm_at_action": 2, "pre_approval": 1, "not_required": 0}
EXIT = {"hand_off": 3, "confirm_at_action": 2, "pre_approval": 2, "not_required": 0}

ACTION = {
    "hand_off": "사용자가 직접 실행해야 한다. 에이전트가 최종 단계를 수행하지 않는다.",
    "confirm_at_action": "실행 직전에 확인을 받아라. 사전 승인이 있어도 다시 확인한다.",
    "pre_approval": "세션에서 이 행위를 구체적으로 승인했으면 진행하고, 아니면 직전에 확인하라.",
    "not_required": "확인 없이 진행한다.",
}


# 인자를 읽거나 출력만 하고 실행하지는 않는 명령.
# 이 명령들만으로 이루어진 명령줄에 한해 따옴표 안을 검사에서 뺀다.
# 위험한 단어를 "검색하는 일"과 "실행하는 일"을 가르기 위한 것이다.
INERT = {"grep", "egrep", "fgrep", "rg", "ag", "ack", "echo", "printf"}

QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _split_segments(cmd: str):
    """따옴표 안을 건드리지 않고 셸 구분자로 명령줄을 나눈다."""
    segments, buf = [], []
    quote = None
    i = 0
    while i < len(cmd):
        ch = cmd[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(cmd):
                buf.append(cmd[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch in "|;&\n":
            segments.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    segments.append("".join(buf))
    return [s for s in (seg.strip() for seg in segments) if s]


def _head_command(segment: str) -> str:
    """구간의 실행 파일 이름. 앞에 붙은 환경변수 대입은 건너뛴다."""
    for word in segment.split():
        if ENV_ASSIGN.match(word):
            continue
        return word.rsplit("/", 1)[-1]
    return ""


def _quoted_args_are_inert(cmd: str) -> bool:
    """명령줄 전체가 읽기·출력 전용 명령으로만 이루어졌는가.

    한 구간이라도 다른 명령이면 예외를 적용하지 않는다. 그래야
    `grep "x" f | bash` 처럼 뒤에서 실행이 일어나는 형태를 놓치지 않는다.
    """
    segments = _split_segments(cmd)
    return bool(segments) and all(_head_command(s) in INERT for s in segments)


def classify(cmd: str) -> dict:
    ignored = _quoted_args_are_inert(cmd)
    scan = QUOTED.sub(" ", cmd) if ignored else cmd
    verdict, reasons = "not_required", []
    for pat, grade, why in RULES:
        if re.search(pat, scan, re.IGNORECASE):
            reasons.append({"grade": grade, "reason": why, "matched": pat})
            if ORDER[grade] > ORDER[verdict]:
                verdict = grade
    secrets = [w for pat, w in SECRET_HINTS if re.search(pat, scan, re.IGNORECASE)]
    return {
        "command": cmd,
        "verdict": verdict,
        "action": ACTION[verdict],
        "reasons": reasons,
        "secret_risk": secrets,
        "exit_code": EXIT[verdict],
        "quoted_args_ignored": ignored,
    }


def render(r: dict):
    mark = {"hand_off": "HAND-OFF", "confirm_at_action": "CONFIRM",
            "pre_approval": "PRE-APPROVAL", "not_required": "OK"}[r["verdict"]]
    print(f"[{mark}] {r['command']}")
    print(f"  → {r['action']}")
    for x in r["reasons"]:
        print(f"  · {x['grade']}: {x['reason']}")
    for s in r["secret_risk"]:
        print(f"  ! 시크릿 위험: {s} — 값을 출력하거나 커밋에 넣지 마라")


def main():
    p = argparse.ArgumentParser(prog="castra_guardian", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", nargs="?", default="")
    p.add_argument("--json", action="store_true")
    p.add_argument("--stdin", action="store_true", help="여러 줄 입력을 각각 판정")
    a = p.parse_args()

    cmds = [l.strip() for l in sys.stdin if l.strip()] if a.stdin else ([a.command] if a.command else [])
    if not cmds:
        p.error("명령을 인자나 --stdin 으로 주어라")

    results = [classify(c) for c in cmds]
    if a.json:
        print(json.dumps(results if len(results) > 1 else results[0], ensure_ascii=False, indent=2))
    else:
        for r in results:
            render(r)
    sys.exit(max(r["exit_code"] for r in results))


if __name__ == "__main__":
    main()
