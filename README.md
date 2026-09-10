# Castra

**Your coding agent stops one step early. Castra is the step.**

Castra is an execution-posture harness for [Claude Code](https://claude.com/claude-code). It is one rule pack, three hooks, and two small scripts. It does not make the model smarter. It removes the four places where a capable model quietly stops short of finishing the job.

```
The fix is written but not deployed          → "deploying is part of verifying"
The context window fills mid-task            → a checkpoint survives the window
An irreversible command is one keystroke away → classified before it runs
The turn ends with work still open           → the turn does not end
```

---

## The problem

Ask a strong model to fix a bug and you usually get a correct diagnosis. Then you get a sentence like this:

> The root cause is in the queue handler. This will take effect once #469 is deployed to the resident server.

The diagnosis is right. The bug is still live. The session ends, and the next session inherits a fix nobody has watched work.

This is not a reasoning failure. The model knew what to do. It classified the last step as *someone else's*, and every one of those judgments is defensible on its own:

| What the model says | What is actually true |
|---|---|
| "This needs to be deployed first" | Deploying is a task, not a boundary |
| "I have no Windows machine to verify on" | There is an SSH host in `~/.ssh/config` |
| "The tests pass" | The test passed while the defect was live |
| "I'll hand this to the next session" | The next session inherits an unproven fix |

Castra turns each of those from a stopping point into a step.

## What it actually does

Four mechanisms. Two are text, two are code, and the split is deliberate: **a rule the model can read cannot see runtime state.** Context pressure, command risk, and unfinished work at turn end are not knowable from a prompt, so they run as hooks.

### 1. The posture pack — static rules

A single pack loaded on every task. Twenty-seven sections covering stance, authorization, verification standard, reporting, and precedence. Some representative rules:

- **Request-shaped language is an instruction.** "Can you look at…" authorizes the work. Do not stop at confirming you can do it.
- **A missing capability is a thing to find, not a reason to stop.** Before declaring a capability absent, look where it would live: `~/.ssh/config`, `PATH`, the platform's own device listing, the config the tool itself reads. One command usually settles it.
- **Green is a claim, and claims get audited.** Ask what would have happened if the code were still broken. If the check would have passed anyway, it proved nothing.
- **Which failure mode is yours.** The pack is read by different models and they do not drift the same way. A model whose native failure is over-restraint gets a different clause than one whose failure is over-narration.

Nothing in the pack lowers a safety bar. The `Precedence` section is explicit: destructive actions still require confirmation, secret rules apply in full, and unverified claims stay labeled.

### 2. Budget hook — a checkpoint that survives the window

A `UserPromptSubmit` hook reads the real occupancy of the context window and injects a reminder at two thresholds. Below the warning line it tells the model to checkpoint before the next large step. Below the critical line it tells the model to stop, write exactly one checkpoint, and continue in a fresh window.

Occupancy is read from the session transcript's own `usage` records, not estimated from character counts:

```
input_tokens + cache_read + cache_creation + output_tokens
```

The window size is **auto-detected**. Nothing in the transcript states it, so Castra reads the model id and the largest occupancy that model has ever reached across your history. A model that has held 967,396 tokens is not running a 200,000-token window. Observations accumulate in `~/.castra-windows.json` and get reused.

### 3. Guardian hook — classify before it runs

A `PreToolUse` hook classifies every shell command into four verdicts before execution.

| Verdict | Exit | Meaning |
|---|---|---|
| `hand_off` | 3 | The agent does not run it. You do. |
| `confirm_at_action` | 2 | Ask immediately before running, even with prior approval |
| `pre_approval` | 1 | Proceed if the session authorized this specific action |
| `not_required` | 0 | Proceed |

Force-push, history rewrite, `DROP TABLE`, disk format, and reading `.env` are hand-off. Recursive delete, `reset --hard`, `WHERE`-less `DELETE`, piping a remote script into a shell, and privilege escalation are confirm-at-action.

The classifier is deliberately a **floor, not a ceiling**. It matches known-dangerous shapes and cannot see intent or blast radius, and the pack says so in the same breath as invoking it.

**Searching for a dangerous pattern is not running one.** `grep -rn "rm -rf" scripts/` is a read. `psql -c "DROP TABLE users"` is not. Castra separates them by an exemption narrow enough to be safe: quoted arguments are ignored only when *every* segment of the command line is a read-only tool. One segment that executes, and the exemption is gone.

```
grep -rn "rm -rf" scripts/        → not_required   (exemption applied)
grep -rn "x" f | bash             → no exemption; the pipeline is classified whole
psql -c "DROP TABLE users"        → hand_off
bash -c "rm -rf ~/Code"           → confirm_at_action
```

This matters more than it looks. Stripping quotes globally would have made every SQL rule permanently dead, because a database command is *always* quoted in a shell — and it would have handed the model a one-character bypass.

### 4. Open-loop hook — the turn does not end on unfinished work

A `Stop` hook reads `.castra/openloops`. If any line remains, the turn does not end. Unverified results, changes whose effect was never observed, and things still running go there one per line; a line is deleted when it is closed.

There is a block cap, because a hook that can never be satisfied is worse than no hook.

## Install

```bash
git clone https://github.com/beyondworks/castra.git
cd castra && ./install.sh
```

The installer copies the pack and scripts to `~/.castra/`, copies three hooks to `~/.claude/hooks/`, registers them in `~/.claude/settings.json` without disturbing hooks you already have, and prints a routing block to paste into your `CLAUDE.md`. Restart Claude Code once so the hook registration is picked up.

Verify:

```bash
./tests/run.sh
```

## What this is not

- **Not a benchmark result.** The rules are stated; their effect sizes are unmeasured. Castra makes claims about what it instructs, not about how much it improves anything.
- **Not a jailbreak or a safety bypass.** It raises the bias toward action on reversible work. It lowers no confirmation requirement, and it adds one.
- **Not model-specific magic.** The pack is plain English rules and the hooks are ~300 lines of Python and shell. Read all of it before you install it.

## Design notes

Three things fell out of building this that are worth stating, because each cost a real bug.

**A dead hook looks exactly like a working one.** The budget hook was registered, ran on every prompt, exited 0 — and could never fire, because it estimated occupancy from the last 80 lines of the transcript against a 1,000,000-token window. Registration is not operation. Every hook here ships with a test that forces its threshold.

**A hook nobody writes to is decoration.** The open-loop hook read a file that no rule ever told the model to create. It passed every test, because the test created the file. The fix was a routing line, not code.

**A guard that over-blocks gets bypassed by hand.** The first guardian matched patterns anywhere in the command string, so a command that merely *mentioned* a dangerous pattern was denied. The cost of a false positive is a detour; the cost of a missed detection is unrecoverable. The exemption above is the narrowest thing that fixes the first without touching the second.

## License

MIT. See [LICENSE](LICENSE).
