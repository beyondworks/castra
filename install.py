#!/usr/bin/env python3
"""Castra installer. Runs the same way on macOS, Linux and Windows.

Copies the pack, scripts, hooks and skill into place, then registers the hooks
in Claude Code settings without disturbing hooks that are already there.

Hooks are registered in exec form — Claude Code spawns the interpreter directly
with no shell involved. Shell form would run through `sh -c` on macOS and Linux
but through Git Bash on Windows, falling back to PowerShell when Git Bash is
absent, so a shell-form registration is not portable. Exec form performs no
variable expansion either, so every path written here is absolute.

  python3 install.py            install
  python3 install.py --dry-run  report what would change and touch nothing
"""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import sys

SRC = pathlib.Path(__file__).resolve().parent
HOOK_SCRIPTS = {
    # SessionStart has no matcher on purpose: the posture has to be re-injected
    # after a compaction, which replaces earlier context with a summary.
    "SessionStart": (None, "castra-posture.py"),
    "UserPromptSubmit": (None, "castra-budget.py"),
    "PreToolUse": ("Bash", ("castra-guardian.py", "castra-release-gate.py")),
    # Open loops are recorded from tool use itself. Asking the model to write
    # them produced a call rate of zero, which left the Stop hook with nothing
    # to block on.
    "PostToolUse": ("Edit|Write|NotebookEdit|Bash", "castra-trace.py"),
    "Stop": (None, "castra-openloop.py"),
}


def claude_dir() -> pathlib.Path:
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    return pathlib.Path(override) if override else pathlib.Path.home() / ".claude"


def castra_home() -> pathlib.Path:
    override = os.environ.get("CASTRA_HOME")
    return pathlib.Path(override) if override else pathlib.Path.home() / ".castra"


def interpreter() -> str:
    """Absolute path to the python that will run the hooks.

    Exec form performs no PATH lookup, so this has to be a real path rather than
    the name "python3". It must also be a path that survives a python upgrade:
    resolving symlinks would pin something like
    /opt/homebrew/Cellar/python@3.14/3.14.6/... which disappears on the next
    patch release and takes the hooks down silently. So prefer the stable
    PATH entry and fall back to the running interpreter, unresolved.

    On Windows the PATH entry is often a Microsoft Store alias stub that cannot
    be spawned, so the running interpreter is the safer choice there.
    """
    if os.name != "nt":
        found = shutil.which("python3") or shutil.which("python")
        if found:
            return str(pathlib.Path(found).absolute())
    return str(pathlib.Path(sys.executable).absolute())


def copy_tree(files, dest: pathlib.Path, dry: bool) -> None:
    if not dry:
        dest.mkdir(parents=True, exist_ok=True)
    for f in files:
        if dry:
            continue
        shutil.copy2(f, dest / f.name)
        if f.suffix == ".py":
            target = dest / f.name
            target.chmod(target.stat().st_mode | 0o111)


def install_files(dry: bool) -> tuple:
    home, cdir = castra_home(), claude_dir()
    if not cdir.exists() and not dry:
        raise SystemExit(f"error: {cdir} not found. Install Claude Code first.")

    copy_tree(sorted((SRC / "scripts").glob("castra_*.py")), home / "scripts", dry)
    copy_tree(sorted((SRC / "packs").glob("*.txt")), home / "packs", dry)
    hook_dir = cdir / "hooks"
    copy_tree(sorted((SRC / "hooks").glob("castra-*.py")), hook_dir, dry)
    print(f"{'would install' if dry else 'installed'}: {home}")
    print(f"{'would install' if dry else 'installed'}: {hook_dir}")

    skill_dir = cdir / "skills" / "thinking-map"
    if (skill_dir / "SKILL.md").exists():
        print(f"skipped: {skill_dir / 'SKILL.md'} already exists, left untouched")
    else:
        copy_tree(sorted((SRC / "skills" / "thinking-map").glob("SKILL*.md")), skill_dir, dry)
        print(f"{'would install' if dry else 'installed'}: {skill_dir}")
    return hook_dir, cdir / "settings.json"


def register(hook_dir: pathlib.Path, settings_path: pathlib.Path, dry: bool) -> None:
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    except json.JSONDecodeError:
        raise SystemExit("error: settings.json is not valid JSON; not touching it.")

    pybin = interpreter()
    hooks = settings.setdefault("hooks", {})
    added = []
    for event, (matcher, scripts) in HOOK_SCRIPTS.items():
        names = (scripts,) if isinstance(scripts, str) else scripts
        wanted = [{"type": "command", "command": pybin, "args": [str(hook_dir / n)]}
                  for n in names]
        groups = hooks.setdefault(event, [])
        present = [h for g in groups for h in g.get("hooks", [])]
        if all(w in present for w in wanted):
            continue
        # Drop any earlier Castra registration for this event, shell form included.
        for g in groups:
            g["hooks"] = [h for h in g.get("hooks", [])
                          if "castra-" not in h.get("command", "") + " ".join(h.get("args", []))]
        groups[:] = [g for g in groups if g.get("hooks")]
        group = {"hooks": wanted}
        if matcher:
            group["matcher"] = matcher
        groups.append(group)
        added.append(event)

    if not added:
        print("hooks already registered; settings.json untouched")
        return
    if dry:
        print("would register hooks:", ", ".join(added))
        return
    if settings_path.exists():
        backup = settings_path.with_suffix(".json.castra-backup")
        backup.write_text(settings_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"backed up: {backup}")
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    print("registered hooks:", ", ".join(added))


def write_manifest(dry: bool) -> None:
    """설치본이 어느 저장소에서 왔는지와 그때의 파일 해시를 남긴다.

    이게 없으면 설치본이 정본보다 낡아도 아무도 모른다. 실제로 태세 훅이 옛 팩을
    읽는 동안 검사는 저장소 팩을 대조하고 있었고, 우연히 발견하기 전까지
    두 판본이 다르다는 사실이 드러나지 않았다.
    """
    if dry:
        return
    home = castra_home()
    files = {}
    for rel in sorted(list((SRC / "packs").glob("*.txt"))
                      + list((SRC / "scripts").glob("castra_*.py"))):
        files[f"{rel.parent.name}/{rel.name}"] = hashlib.sha256(rel.read_bytes()).hexdigest()[:16]
    try:
        (home / "manifest.json").write_text(
            json.dumps({"source": str(SRC), "files": files}, indent=2) + "\n",
            encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without writing anything")
    args = parser.parse_args()

    hook_dir, settings_path = install_files(args.dry_run)
    write_manifest(args.dry_run)
    register(hook_dir, settings_path, args.dry_run)

    block = SRC / "templates" / "claude-md-block.md"
    print(f"""
Next, add the routing block to your CLAUDE.md:
    {block}

Then restart Claude Code once so the hook registration is picked up.
Verify with: {interpreter()} {SRC / 'tests' / 'run.py'}""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
