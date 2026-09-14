#!/usr/bin/env python3
"""Check available CI runs for the actual release target before publication.

Unknown or ambiguous targets request platform review; no implicit permission.
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

# See castra-guardian.py: in these modes an "ask" is the only thing that still
# opens a dialog, and every one observed was approved without changing the
# result. The reason is passed to the model instead. A CI-based "deny" is kept.
NO_PROMPT_MODES = {"auto", "bypassPermissions"}

# Commands that only print or search their arguments. Their segments are dropped
# before looking for publication, unless their output is piped onward.
PRINT_ONLY = ("echo", "printf", "rg", "grep")

# Publication inside a compound command, where arguments are not parsed:
# - `git tag` followed by a name or a creating flag, not a listing or delete
# - `git push` carrying a tag ref, --tags/--follow-tags, or a v<digit> name
# - `gh release create`
COMPOUND_PUBLICATION = re.compile(
    r"\bgit\s+(?:-C\s+\S+\s+)?tag"
    r"(?=\s+[^\s;|&])"
    r"(?!\s+(?:-l|--list|-d|--delete|-v|--verify|-n\d*|--contains|--no-contains|"
    r"--points-at|--merged|--no-merged|--sort|--format|--column)\b)"
    r"|\bgit\s+push\b[^;|&\n]*(?:refs/tags/|--tags\b|--follow-tags\b|\sv\d)"
    r"|\bgh\s+release\s+create\b")


def _segments(command):
    """따옴표를 존중해 셸 구분자로 나눈다. (구간, 뒤따르는 구분자) 목록."""
    out, buf, quote, i = [], [], None, 0
    while i < len(command):
        ch = command[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(command):
                buf.append(command[i + 1]); i += 2; continue
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch; buf.append(ch)
        elif ch in ";\n":
            out.append(("".join(buf), ch)); buf = []
        elif command.startswith("&&", i) or command.startswith("||", i):
            out.append(("".join(buf), command[i:i+2])); buf = []; i += 2; continue
        elif ch in "|&":
            out.append(("".join(buf), ch)); buf = []
        else:
            buf.append(ch)
        i += 1
    out.append(("".join(buf), ""))
    return out


def publication_text(command):
    """발행 여부를 판단할 텍스트. 출력만 하는 echo·printf 구간은 뺀다.

    `echo "== git tag exists?"` 같은 안내 문구가 태그 명령으로 오인돼, 조회만
    하는 명령에 승인 창이 뜬 사례가 있었다. 따옴표를 통째로 지우지는 않는다.
    `bash -c "git tag v1"` 처럼 따옴표 안이 실제로 실행되는 경우가 있기 때문이다.
    echo 출력이 파이프로 다른 명령에 들어가는 경우도 빼지 않는다.
    """
    kept = []
    for segment, sep in _segments(command):
        words = segment.strip().split()
        head = os.path.basename(words[0]) if words else ""
        if head in PRINT_ONLY and sep != "|":
            continue
        kept.append(segment)
    return " ; ".join(kept)


def release_target(command, cwd):
    """Return (active, repo cwd, revision). None revision requires human review.

    Only simple direct commands are resolved. Complex shell syntax is not
    interpreted; if it mentions publication, leave target unproven.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return bool(re.search(r"\b(git|gh)\b.*\b(tag|release|push)\b", command)), cwd, None
    if not tokens:
        return False, cwd, None
    executable = os.path.basename(tokens.pop(0))
    scan = publication_text(command)
    if executable not in ("git", "gh") or re.search(r"[;|&\n`]|\$\(", command):
        # One definition for every compound or non-git-led command. The branch for
        # commands led by `cd` used to match any `git push`, so the very common
        # `cd repo && git push origin feature` counted as a release; it also read
        # `git tag --list` and a bare `git tag` as creating a tag. Output-only and
        # search segments are already removed from scan, which is why there is no
        # blanket exclusion by first word: that let `echo "git tag v1" | bash` pass.
        return bool(COMPOUND_PUBLICATION.search(scan)), cwd, None
    if executable == "git":
        while tokens and tokens[0].startswith("-"):
            if tokens[0] == "-C" and len(tokens) >= 2:
                cwd = os.path.abspath(os.path.join(cwd or os.getcwd(), tokens[1]))
                tokens = tokens[2:]
                continue
            # Other git global options can alter the repository/configuration.
            # Recognize publication, but do not assume its target or authorization.
            return any(x in ("tag", "push") for x in tokens), cwd, None
        if not tokens:
            return False, cwd, None
        verb, args = tokens[0], tokens[1:]
        if verb == "tag":
            if not args or any(x in ("-l", "--list", "-d", "--delete", "-v", "--verify") for x in args):
                return False, cwd, None
            positional = []
            i = 0
            while i < len(args):
                x = args[i]
                if x in ("-m", "--message", "-F", "--file", "-u", "--local-user"):
                    i += 2
                    continue
                if x in ("-a", "--annotate", "-s", "--sign", "-f", "--force", "--"):
                    i += 1
                    continue
                if x.startswith("-"):
                    return True, cwd, None
                positional.append(x)
                i += 1
            return True, cwd, (positional[1] if len(positional) == 2 else "HEAD" if len(positional) == 1 else None)
        if verb == "push":
            if any(x in ("--tags", "--follow-tags", "--all", "--mirror") for x in args):
                return True, cwd, None
            options = [x for x in args if x.startswith("-")]
            if any(x in ("--delete", "-d") for x in options):
                return False, cwd, None  # destruction belongs to the guardian
            positional = [x for x in args if not x.startswith("-")]
            refs = positional[1:]  # first is remote
            if len(refs) == 2 and refs[0] == "tag":
                return True, cwd, "refs/tags/" + refs[1]
            tagged = []
            for ref in refs:
                src, _, dest = ref.lstrip("+").partition(":")
                if dest.startswith("refs/tags/") or src.startswith("refs/tags/") or re.match(r"v\d", src):
                    tagged.append(src)
                elif src and not dest:
                    # Explicit non-v tag names are still tags. Probe only the
                    # local ref namespace; no network and no command execution.
                    resolved = sh(tool("git") + ["show-ref", "--verify", "--hash", "refs/tags/" + src], cwd)
                    if resolved:
                        tagged.append("refs/tags/" + src)
            if len(tagged) == 1 and len(refs) == 1:
                return True, cwd, tagged[0] or None
            return bool(tagged) or "tag" in refs, cwd, None
        return False, cwd, None
    if tokens[:2] != ["release", "create"]:
        return "release" in tokens and "create" in tokens, cwd, None
    args = tokens[2:]
    if not args or args[0].startswith("-") or any(x in ("-R", "--repo") or x.startswith("--repo=") for x in args):
        return True, cwd, None
    if "--target" in args or any(x.startswith("--target=") for x in args):
        # gh uses --target only when creating a missing tag. An existing remote
        # tag can point elsewhere; without remote identity, do not approve it.
        return True, cwd, None
    return True, cwd, "refs/tags/" + args[0]


def tool(name: str) -> list:
    """실행할 명령의 앞부분. 환경변수로 덮어쓸 수 있다.

    훅은 exec 형식으로 실행되므로 사용자의 셸 PATH 를 그대로 물려받지 않는다.
    gh 가 PATH 에 없어 조회가 실패하면 게이트는 매번 확인으로 내려앉는다.
    그래서 CASTRA_GIT_BIN / CASTRA_GH_BIN 으로 실제 경로를 줄 수 있게 둔다.
    값은 인자를 포함해도 된다.
    """
    override = os.environ.get(f"CASTRA_{name.upper()}_BIN")
    if override:
        # posix=True treats a backslash as an escape, so an unquoted Windows path
        # comes back with every separator removed: C:\tools\gh.exe becomes
        # C:toolsgh.exe. Split in Windows mode there and drop the quoting.
        parts = shlex.split(override, posix=(os.name != "nt"))
        return [t.strip('"') for t in parts]
    return [shutil.which(name) or name]


def sh(args, cwd, timeout=25):
    try:
        p = subprocess.run(args, cwd=cwd or None, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def decide(cwd: str, revision="HEAD") -> tuple:
    """(판정, 사유). 판정은 allow / deny / confirm."""
    if not revision or revision.startswith("-"):
        return "confirm", "발행 대상을 하나의 로컬 커밋으로 확인할 수 없다. 대상별 CI를 확인하라."
    head = sh(tool("git") + ["rev-parse", "--verify", "--end-of-options", revision + "^{commit}"], cwd)
    if not head:
        return "confirm", "git 저장소를 확인하지 못했다. 발행 대상 커밋을 직접 확인하라."

    raw = sh(tool("gh") + ["run", "list", "--commit", head, "--limit", "100",
              "--json", "headSha,status,conclusion,workflowName"], cwd)
    if raw is None:
        return "confirm", ("이 커밋의 CI 결과를 조회하지 못했다(gh 부재·네트워크·권한). "
                           "검사 결과를 직접 확인한 뒤 진행하라.")
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, list) or any(not isinstance(r, dict) for r in parsed):
            raise TypeError("invalid run list")
        # gh returns newest first; an earlier failed attempt must not override
        # the latest completed rerun of that same workflow.
        latest = {}
        for r in parsed:
            if r.get("headSha") == head:
                latest.setdefault(r.get("workflowName", "?"), r)
        runs = list(latest.values())
    except (json.JSONDecodeError, TypeError):
        return "confirm", "CI 조회 결과를 해석하지 못했다. 직접 확인하라."

    if not runs:
        return "confirm", (f"target({head[:8]})에 대한 CI 실행이 아직 없다. "
                           "푸시가 끝났는지, 실행이 등록됐는지 확인하라.")

    pending = [r for r in runs if r.get("status") != "completed"]
    if pending:
        names = ", ".join(sorted({r.get("workflowName", "?") for r in pending}))
        return "deny", (f"target({head[:8]})의 CI가 아직 끝나지 않았다: {names}. "
                        "끝난 뒤 결과를 보고 발행하라. 최신 실행이 아니라 "
                        "이 커밋의 실행인지 해시로 맞춰서 보라.")

    failed = [r for r in runs if r.get("conclusion") != "success"]
    if failed:
        detail = ", ".join(f"{r.get('workflowName','?')}={r.get('conclusion')}" for r in failed)
        return "deny", (f"target({head[:8]})의 CI가 통과하지 않았다: {detail}. "
                        "실패를 고쳐 다시 통과시킨 뒤 발행하라.")

    names = ", ".join(sorted({r.get("workflowName", "?") for r in runs}))
    return "allow", f"target({head[:8]}) CI 통과: {names}"


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return 0

    inp = payload.get("tool_input")
    cmd = str(inp.get("command", "")) if isinstance(inp, dict) else ""
    active, cwd, revision = release_target(cmd, payload.get("cwd") or "")
    if not active:
        return 0

    verdict, reason = decide(cwd, revision)
    if verdict == "deny":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "castra-release-gate: " + reason,
        }}))
    elif verdict == "confirm":
        mode = payload.get("permission_mode")
        if mode in NO_PROMPT_MODES:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": f"Castra advisory, not prompted in {mode} mode: castra-release-gate: {reason}",
            }}))
        else:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "ask",
                "permissionDecisionReason": "castra-release-gate: " + reason,
            }}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
