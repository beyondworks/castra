#!/usr/bin/env python3
"""Install standalone Castra hooks, or inspect their integrity with --check.

Use either this installer OR Claude Code's --plugin-dir mode, never both.
Settings and managed files are validated before any installation writes.
"""
import argparse
import copy
import datetime
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

SRC = pathlib.Path(__file__).resolve().parent
HOOK_SCRIPTS = {
    "SessionStart": [(None, "castra-posture.py")],
    "UserPromptSubmit": [(None, "castra-budget.py"), (None, "castra-route.py")],
    "PreToolUse": [("Bash", "castra-guardian.py"), ("Bash", "castra-release-gate.py")],
    "PostToolUse": [("Edit|Write|NotebookEdit|Bash", "castra-trace.py"),
                    ("Edit|Write|NotebookEdit|Bash", "castra-budget.py")],
    "Stop": [(None, "castra-openloop.py")],
}


def claude_dir():
    return pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR") or pathlib.Path.home() / ".claude").absolute()


def castra_home():
    return pathlib.Path(os.environ.get("CASTRA_HOME") or pathlib.Path.home() / ".castra").absolute()


def interpreter():
    found = (shutil.which("python3") or shutil.which("python")) if os.name != "nt" else None
    return str(pathlib.Path(found or sys.executable).absolute())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(path):
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError(f"refusing symlink destination: {item}")
    if path.exists() and not path.is_file():
        raise ValueError(f"destination is not a regular file: {path}")


def read_snapshot(path):
    safe_path(path)
    return path.read_bytes() if path.exists() else None


def json_snapshot(content, path):
    data = json.loads(content.decode("utf-8")) if content is not None else {}
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def read_json(path):
    return json_snapshot(read_snapshot(path), path)


def validate_settings(settings):
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("settings.hooks must be an object")
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            raise ValueError(f"settings.hooks.{event} must be an array")
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise ValueError(f"invalid hook group: {event}")
            if any(not isinstance(h, dict) for h in group["hooks"]):
                raise ValueError(f"invalid hook handler: {event}")


def registrations(hook_dir):
    result = {}
    for event, entries in HOOK_SCRIPTS.items():
        groups = []
        for matcher, name in entries:
            group = {"hooks": [{"type": "command", "command": interpreter(),
                                "args": [str(hook_dir / name)]}]}
            if matcher:
                group["matcher"] = matcher
            groups.append(group)
        result[event] = groups
    return result


def owned_hook(handler, hook_dir):
    if handler.get("type") != "command":
        return False
    command, args = handler.get("command"), handler.get("args")
    if not isinstance(command, str):
        return False
    if args is None:
        try:
            tokens = shlex.split(command)
        except ValueError:
            return False
        if len(tokens) != 2:
            return False
        command, arg = tokens
    elif isinstance(args, list) and len(args) == 1 and isinstance(args[0], str):
        arg = args[0]
    else:
        return False
    if not re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", pathlib.Path(command).name):
        return False
    names = {name for entries in HOOK_SCRIPTS.values() for _, name in entries}
    return pathlib.Path(arg).expanduser() in {hook_dir / name for name in names}


def merged_settings(settings, hook_dir):
    result = copy.deepcopy(settings)
    hooks = result.setdefault("hooks", {})
    # Remove exact Castra script invocations only; mentions in foreign commands stay.
    for event, groups in list(hooks.items()):
        kept = []
        for group in groups:
            handlers = [h for h in group["hooks"] if not owned_hook(h, hook_dir)]
            if handlers or not group["hooks"]:
                kept.append({**group, "hooks": handlers})
        hooks[event] = kept
    for event, groups in registrations(hook_dir).items():
        hooks.setdefault(event, []).extend(groups)
    return result


def source_files(home, cdir):
    files = []
    for dirname, pattern, destination in (("scripts", "castra_*.py", home / "scripts"),
                                           ("packs", "*.txt", home / "packs"),
                                           ("hooks", "castra-*.py", cdir / "hooks")):
        for source in sorted((SRC / dirname).glob(pattern)):
            files.append((source, destination / source.name))
    for skill in ("thinking-map", "castra"):
        for source in sorted((SRC / "skills" / skill).rglob("*")):
            if source.is_file() and "__pycache__" not in source.parts:
                files.append((source, cdir / "skills" / skill / source.relative_to(SRC / "skills" / skill)))
    required = {name for entries in HOOK_SCRIPTS.values() for _, name in entries}
    if not required.issubset({s.name for s, _ in files}):
        raise ValueError("source is incomplete: a registered hook is missing")
    if not (SRC / "skills/castra/SKILL.md").is_file():
        raise ValueError("source is incomplete: skills/castra/SKILL.md is missing")
    return files


def plan_install():
    home, cdir = castra_home(), claude_dir()
    settings_path, manifest_path = cdir / "settings.json", home / "manifest.json"
    originals = {settings_path: read_snapshot(settings_path), manifest_path: read_snapshot(manifest_path)}
    settings = json_snapshot(originals[settings_path], settings_path)
    validate_settings(settings)
    enabled = settings.get("enabledPlugins", {})
    if isinstance(enabled, dict) and any(value is True and (name == "castra" or name.startswith("castra@"))
                                         for name, value in enabled.items()):
        raise ValueError("Castra plugin is enabled; choose plugin mode or disable it before standalone installation")
    manifest = json_snapshot(originals[manifest_path], manifest_path)
    managed = manifest.get("managed_files", {})
    if not isinstance(managed, dict) or any(not isinstance(value, dict) for value in managed.values()):
        raise ValueError("manifest.managed_files must contain file metadata objects")
    legacy = manifest.get("files", {})
    files, skipped = {}, []
    source_list = source_files(home, cdir)
    # An unowned thinking-map is a user's skill, including translated companions.
    thinking_dir = cdir / "skills/thinking-map"
    preserve_thinking = thinking_dir.exists() and not any(
        str(thinking_dir / p.relative_to(SRC / "skills/thinking-map")) in managed
        for p in (SRC / "skills/thinking-map").rglob("*") if p.is_file())
    for source, target in source_list:
        if preserve_thinking and target.is_relative_to(thinking_dir):
            skipped.append(str(target))
            continue
        originals[target] = read_snapshot(target)
        content = source.read_bytes()
        if originals[target] is not None and originals[target] != content:
            old_hash = digest(originals[target])
            expected = managed.get(str(target), {}).get("sha256")
            legacy_hash = legacy.get(str(source.relative_to(SRC))) if isinstance(legacy, dict) else None
            if old_hash != expected and not (isinstance(legacy_hash, str) and len(legacy_hash) >= 16
                                               and old_hash.startswith(legacy_hash)):
                raise ValueError(f"unowned or modified file would be overwritten: {target}")
        files[target] = content
    merged = merged_settings(settings, cdir / "hooks")
    files[settings_path] = (json.dumps(merged, ensure_ascii=False, indent=2) + "\n").encode()
    new_manifest = {
        "schema_version": 2, "mode": "standalone", "source": str(SRC),
        "version": (SRC / "VERSION").read_text().strip(),
        "managed_files": {str(p): {"sha256": digest(data)} for p, data in files.items()
                          if p != settings_path},
        "registrations": registrations(cdir / "hooks"),
        "skipped_unowned": skipped,
    }
    files[manifest_path] = (json.dumps(new_manifest, indent=2) + "\n").encode()
    for path in files:
        safe_path(path)
    changes = {p: data for p, data in files.items() if originals[p] != data}
    return changes, new_manifest, originals


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".castra-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_changes(changes, expected):
    if not set(changes).issubset(expected):
        raise ValueError("installation changes require preflight snapshots")
    # Compare against the same bytes used for validation and settings merge,
    # before creating backups or writing any target. Re-reading here as the
    # baseline would silently overwrite a user's edit made after planning.
    for path, before in expected.items():
        if read_snapshot(path) != before:
            raise ValueError(f"destination changed since preflight: {path}")
    if not changes:
        print("Castra is already installed; no files changed.")
        return
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = castra_home() / "backups" / stamp
    safe_path(backup / "rollback.json")
    originals = {path: expected[path] for path in changes}
    report = {"status": "prepared", "files": []}
    for number, (path, content) in enumerate(originals.items()):
        saved = backup / f"{number:04d}.before"
        if content is not None:
            atomic_write(saved, content)
        report["files"].append({"path": str(path), "backup": str(saved) if content is not None else None,
                                "before_sha256": digest(content) if content is not None else None,
                                "after_sha256": digest(changes[path])})
    report_path = backup / "rollback.json"
    atomic_write(report_path, (json.dumps(report, indent=2) + "\n").encode())
    applied = []
    try:
        for path, content in changes.items():
            safe_path(path)
            # Avoid overwriting an edit made since preflight/backup.
            observed = path.read_bytes() if path.exists() else None
            if observed != originals[path]:
                raise ValueError(f"destination changed during install: {path}")
            atomic_write(path, content)
            applied.append(path)
    except Exception:
        conflicts = []
        for path in reversed(applied):
            current = path.read_bytes() if path.is_file() and not path.is_symlink() else None
            if path.is_symlink() or current != changes[path]:
                conflicts.append(str(path))
                continue
            if originals[path] is None:
                path.unlink()
            else:
                atomic_write(path, originals[path])
        report["status"] = "rollback_conflict" if conflicts else "rolled_back"
        report["preserved_concurrent_changes"] = conflicts
        atomic_write(report_path, (json.dumps(report, indent=2) + "\n").encode())
        print(f"Installation failed; rollback status {report['status']}; report: {report_path}", file=sys.stderr)
        raise
    report["status"] = "installed"
    atomic_write(report_path, (json.dumps(report, indent=2) + "\n").encode())
    print(f"Installed {len(changes)} changed files. Backup and rollback map: {report_path}")



def validate_output(output, event, name):
    if not output:
        return
    if not output.startswith("{"):
        if event == "SessionStart":
            return
        raise ValueError(f"unexpected non-JSON hook output: {event}/{name}")
    parsed = json.loads(output)
    if not isinstance(parsed, dict):
        raise ValueError(f"hook output must be an object: {name}")
    for key in ("continue", "suppressOutput"):
        if key in parsed and not isinstance(parsed[key], bool):
            raise ValueError(f"invalid {key} output: {name}")
    for key in ("reason", "stopReason", "systemMessage"):
        if key in parsed and not isinstance(parsed[key], str):
            raise ValueError(f"invalid {key} output: {name}")
    if "decision" in parsed and parsed["decision"] not in ("approve", "block"):
        raise ValueError(f"invalid decision output: {name}")
    specific = parsed.get("hookSpecificOutput")
    if specific is not None:
        if not isinstance(specific, dict) or specific.get("hookEventName") != event:
            raise ValueError(f"wrong hook output event schema: {name}/{event}")
        for key in ("additionalContext", "permissionDecisionReason"):
            if key in specific and not isinstance(specific[key], str):
                raise ValueError(f"invalid {key} output: {name}")
        if "permissionDecision" in specific and (event != "PreToolUse" or
                                                  specific["permissionDecision"] not in ("allow", "deny", "ask")):
            raise ValueError(f"invalid permissionDecision output: {name}")


def check_install():
    home, cdir = castra_home(), claude_dir()
    manifest = read_json(home / "manifest.json")
    managed = manifest.get("managed_files", {})
    if manifest.get("schema_version") != 2 or not managed:
        raise ValueError("no complete installation manifest; reinstall after checking local modifications")
    errors = []
    for entries in HOOK_SCRIPTS.values():
        for _, name in entries:
            if str(cdir / "hooks" / name) not in managed:
                errors.append(f"registered hook absent from managed manifest: {name}")
    for name, metadata in managed.items():
        if not isinstance(metadata, dict):
            raise ValueError(f"invalid managed manifest metadata: {name}")
        path = pathlib.Path(name)
        safe_path(path)
        if not path.is_file() or digest(path.read_bytes()) != metadata.get("sha256"):
            errors.append(f"missing or modified managed file: {path}")
    settings = read_json(cdir / "settings.json")
    validate_settings(settings)
    for event, groups in manifest.get("registrations", {}).items():
        for group in groups:
            if group not in settings.get("hooks", {}).get(event, []):
                errors.append(f"registration missing or changed: {event}")
    if errors:
        raise ValueError("\n".join(errors))
    # Only our allowlisted installed entry points run. State lives in a temporary
    # home, never the user's current session. Foreign hooks are never executed.
    with tempfile.TemporaryDirectory(prefix="castra-doctor-") as directory:
        tmp = pathlib.Path(directory)
        env = {**os.environ, "HOME": directory, "USERPROFILE": directory,
               "CLAUDE_CONFIG_DIR": str(tmp / "claude"), "CASTRA_HOME": str(tmp / "castra"),
               "PYTHONDONTWRITEBYTECODE": "1"}
        for sub in ("scripts", "packs"):
            shutil.copytree(home / sub, tmp / "castra" / sub)
        payload = {"session_id": "castra-doctor", "cwd": directory,
                   "prompt": "plain: show status only", "tool_name": "Bash",
                   "tool_input": {"command": "pwd"}, "tool_response": {"stdout": directory, "exit_code": 0},
                   "stop_hook_active": False}
        count = 0
        for event, entries in HOOK_SCRIPTS.items():
            for _, name in entries:
                payload["hook_event_name"] = event
                result = subprocess.run([interpreter(), str(cdir / "hooks" / name)],
                                        input=json.dumps(payload), capture_output=True, text=True,
                                        cwd=directory, env=env, timeout=15)
                if result.returncode:
                    raise ValueError(f"harmless payload failed: {event}/{name} (exit {result.returncode})")
                validate_output(result.stdout.strip(), event, name)
                count += 1
    print(f"PASS: {len(managed)} installed file hashes, registrations, {count} isolated hook payloads.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--check", action="store_true", help="read-only installed integrity and isolated hook checks")
    args = parser.parse_args()
    try:
        if args.check:
            check_install()
        else:
            changes, manifest, originals = plan_install()
            if args.dry_run:
                print(f"Would change {len(changes)} files; no writes performed.")
                for path in changes:
                    print(path)
            else:
                apply_changes(changes, originals)
            for path in manifest["skipped_unowned"]:
                print(f"Preserved unowned skill: {path}")
            print("Standalone mode: do not also load this directory as a plugin. Restart Claude Code after installation.")
        return 0
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
