#!/usr/bin/env bash
# Castra installer. Copies the pack, scripts and hooks into place and registers
# the hooks in Claude Code settings without disturbing hooks you already have.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CASTRA_HOME="${CASTRA_HOME:-$HOME/.castra}"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
HOOK_DIR="$CLAUDE_DIR/hooks"
SETTINGS="$CLAUDE_DIR/settings.json"

if [ ! -d "$CLAUDE_DIR" ]; then
  echo "error: $CLAUDE_DIR not found. Install Claude Code first." >&2
  exit 1
fi

mkdir -p "$CASTRA_HOME/scripts" "$CASTRA_HOME/packs" "$HOOK_DIR"
cp "$SRC"/scripts/castra_*.py "$CASTRA_HOME/scripts/"
cp "$SRC"/packs/*.txt          "$CASTRA_HOME/packs/"
cp "$SRC"/hooks/castra-*       "$HOOK_DIR/"
chmod +x "$CASTRA_HOME"/scripts/*.py "$HOOK_DIR"/castra-*
echo "installed: $CASTRA_HOME"
echo "installed: $HOOK_DIR/castra-{budget.sh,guardian.py,openloop.py}"

python3 - "$SETTINGS" <<'PY'
import json, pathlib, sys

path = pathlib.Path(sys.argv[1])
try:
    settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
except json.JSONDecodeError:
    print("error: settings.json is not valid JSON; not touching it.", file=sys.stderr)
    raise SystemExit(1)

WANTED = {
    "UserPromptSubmit": (None, 'bash "$HOME/.claude/hooks/castra-budget.sh" 2>/dev/null || true'),
    "PreToolUse": ("Bash", 'python3 "$HOME/.claude/hooks/castra-guardian.py" 2>/dev/null || printf "{}\\n"'),
    "Stop": (None, 'python3 "$HOME/.claude/hooks/castra-openloop.py" 2>/dev/null || printf "{}\\n"'),
}

hooks = settings.setdefault("hooks", {})
added = []
for event, (matcher, command) in WANTED.items():
    groups = hooks.setdefault(event, [])
    if any(h.get("command") == command for g in groups for h in g.get("hooks", [])):
        continue
    # drop a previous Castra registration for this event before adding the new one
    for g in groups:
        g["hooks"] = [h for h in g.get("hooks", []) if "castra-" not in h.get("command", "")]
    groups[:] = [g for g in groups if g.get("hooks")]
    group = {"hooks": [{"type": "command", "command": command}]}
    if matcher:
        group["matcher"] = matcher
    groups.append(group)
    added.append(event)

if added:
    backup = path.with_suffix(".json.castra-backup")
    if path.exists():
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"backed up: {backup}")
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("registered hooks:", ", ".join(added))
else:
    print("hooks already registered; settings.json untouched")
PY

cat <<'MSG'

Next, paste the routing block into your CLAUDE.md:

    cat templates/claude-md-block.md >> ~/.claude/CLAUDE.md

Then restart Claude Code once so the hook registration is picked up.
Verify with ./tests/run.sh
MSG
