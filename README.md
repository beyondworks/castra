# Castra

**Your coding agent stops one step early. Castra is the step.**

Castra is an execution-posture harness for [Claude Code](https://claude.com/claude-code). It is one rule pack, five hooks, and two small scripts. It does not make the model smarter. It removes the four places where a capable model quietly stops short of finishing the job.

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

Four mechanisms, all of them hooks now, and the split of concerns is deliberate: **a rule the model can read cannot see runtime state.** Context pressure, command risk, and unfinished work at turn end are not knowable from a prompt, so they run as hooks.

### 1. The posture pack — injected, not referenced

A `SessionStart` hook prints the whole pack into context at the start of every session, including after a compaction. It is not a file the model is told to open.

That distinction was measured, not assumed. The first version put a line in `CLAUDE.md` naming the pack's path. Across ten sessions where that line was loaded, the number that actually opened the file was **zero**. A rule that depends on the model choosing to read a rule is not in force. So the content goes in first, and the three commands the model has to call by hand are printed alongside it rather than left in a file.

The cost is about 9,400 tokens per session. A summary would be cheaper, and a summary is exactly what already existed in `CLAUDE.md` while the read rate sat at zero.

The pack runs to twenty-nine sections covering stance, authorization, verification standard, reporting, and precedence. Some representative rules:

- **Request-shaped language is an instruction.** "Can you look at…" authorizes the work. Do not stop at confirming you can do it.
- **A missing capability is a thing to find, not a reason to stop.** Before declaring a capability absent, look where it would live: `~/.ssh/config`, `PATH`, the platform's own device listing, the config the tool itself reads. One command usually settles it.
- **Reproduce first, and keep observing.** Given a symptom, look at where the symptom lives before opening the code. A hypothesis from reading is a tool for picking the next observation; run the one that would break it. Ten minutes on one hypothesis with nothing moving means stop and list the layer the symptoms share.
- **Name where a fix reached.** Source, installed build, resident server, live database, edge, remote device. A change that has not reached the user's screen is not fixed, and merging is not arrival.
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

### 4. Open loops — recorded by the tooling, not by the model

A `PostToolUse` hook writes the open loops and a `Stop` hook refuses to end the turn while any remain. Editing a code file records "changed, never observed running". A command that actually runs that file clears it.

The first version asked the model to write those entries itself. Across ten sessions it wrote **zero**, so the `Stop` hook had nothing to block on and looked, from the outside, exactly like a hook that was working fine. The fix was not to detect the idleness. It was to remove the step that someone had to remember: the hook is now both the only author and the only reader of the file.

Documentation and config edits are excluded. A gate that fires on things nobody needs to verify is a gate people learn to route around, and there is a block cap for the same reason — a hook that can never be satisfied is worse than no hook.

**The rule this produced:** a capability that depends on the model choosing to invoke it is not a control. Bind it to an event, and derive its input from something that always exists — the tool call, the transcript — never from a file another party is supposed to fill in.

## Also included: the thinking-map skill

Castra is about the end of the work. One skill ships alongside it that is about the beginning, because the two failures are opposite and both are real.

Ask a model to open up a problem and you get a flat list. Ten plausible options, ordered roughly by how conventional they are, and then it picks one near the top. Nothing on that list came from combining two of the others. The model widened; it never connected.

`skills/thinking-map/SKILL.md` constrains four stages:

1. **Split into axes before writing any candidate.** One test decides the split: two items belong to the same axis only if they cannot both be true at once. "Free" and "subscription" are one axis. "Free" and "sold to enterprises" are two.
2. **Spread at least four per axis**, and make the last one a deliberate extreme or inversion. The unfamiliar candidates start at the fourth.
3. **Cross-link items from different axes, and write the mechanism for each pair in a sentence.** Two words side by side is not a connection, and a pair whose mechanism cannot be written gets discarded. Then ask what happens when two combinations are joined — second-order links are where something absent from every original list appears.
4. **Prune against a criterion fixed in advance**, and keep the near-miss with its reason.

Two rules carry the weight. The orthogonality test in stage 1 keeps the axes from collapsing into each other, without which stage 3 degenerates into re-grouping the same list. The mechanism sentence in stage 3 is what separates a synthesis from a list pretending to be one.

The skill installs to `~/.claude/skills/thinking-map/` and is invocable as `/thinking-map`. A Korean version sits beside it as `SKILL.ko.md`. If you already have a skill by that name, the installer leaves yours alone.

## Install

**macOS and Linux**

```bash
git clone https://github.com/beyondworks/castra.git
cd castra && ./install.sh
```

**Windows**

```powershell
git clone https://github.com/beyondworks/castra.git
cd castra
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Python 3 is the only requirement, and both scripts are thin wrappers around `install.py` so the two platforms run identical logic. The installer copies the pack and scripts to `~/.castra/`, copies three hooks to `~/.claude/hooks/`, registers them in settings without disturbing hooks you already have, and points you at a routing block for your `CLAUDE.md`. Restart Claude Code once so the registration is picked up. Add `--dry-run` to see what would change first.

Verify with `./tests/run.sh`, or `python install.py` and `python tests\run.py` on Windows.

### Why the hooks are Python, not shell

Claude Code runs a shell-form hook through `sh -c` on macOS and Linux, but on Windows through Git Bash — or PowerShell when Git Bash is not installed. A `.sh` hook is therefore not portable, and `$HOME` does not mean the same thing in each case.

Castra registers its hooks in **exec form** instead: Claude Code spawns the interpreter directly with an argument vector and no shell in between. That removes shell differences, quoting, and variable expansion from the path entirely. The installer writes an absolute interpreter path, deliberately unresolved, because resolving symlinks pins a version-specific directory that vanishes on the next patch upgrade and takes the hooks down silently.

The guardian classifier carries PowerShell rules alongside the POSIX ones for the same reason. `Remove-Item -Recurse -Force`, `Format-Volume`, `Set-ExecutionPolicy`, and `iwr … | iex` are the same dangers in a notation that no POSIX pattern matches.

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
