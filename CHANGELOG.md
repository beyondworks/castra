# Changelog

All notable changes to Castra are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-09-11

Three features had a measured call rate of zero because they were instructions
to call something rather than events. Detecting that they were idle would have
been the wrong fix. They are now events.

### Added
- `castra-trace.py`, a `PostToolUse` hook that records open loops from tool use
  itself. Editing a code file records "changed, never observed running"; a command
  that actually runs that file clears it. The hook is both the only author and the
  only reader of the file, so there is no step that someone has to remember.
  Documentation and config edits are excluded — a gate that fires on things nobody
  needs to verify is a gate people learn to ignore.

### Changed
- The pack no longer tells the model to invoke the risk classifier. A `PreToolUse`
  hook already classifies every command and the verdict arrives as a tool result.
- `CLAUDE.md` no longer asks the model to write open loops or to call the guard.
- `castra-posture.py` honours `CASTRA_HOME`, which the installer already honoured.
  Without it a check could read a different pack than the one it asserts against.

### Design rule this release establishes
A capability that depends on the model choosing to invoke it is not a control.
Bind it to an event, and derive its input from something that always exists — the
tool call, the transcript — never from a file another party is supposed to fill in.

## [0.4.0] - 2026-09-11

The pack was never being read. Measured across ten sessions where the routing
line was loaded, the number that actually opened the pack file was zero. A rule
that depends on the model choosing to read a rule is not in force.

### Added
- `castra-posture.py`, a `SessionStart` hook that prints the whole pack into
  context. No matcher, so it also fires after a compaction — which replaces
  earlier context with a summary and would otherwise drop the posture entirely.
- The three commands the model has to call by hand (checkpoint, guardian,
  open-loop entry) are printed alongside the pack. Their call rate was also zero
  while they lived only in a referenced file.
- Posture check that fails if any pack section is missing from the hook output,
  so a summary can never quietly replace the pack.

### Changed
- The harness is now four hooks rather than three, and the `CLAUDE.md` routing
  line says the pack is injected rather than telling the model to open it.

### Cost
About 8,600 tokens per session. A summary would be cheaper and a summary is
exactly what was already in place while nothing read the pack.

## [0.3.1] - 2026-09-11

### Fixed
- Hooks no longer die on a legacy console code page. Windows defaults to one, and
  writing a non-ASCII byte there raised `UnicodeEncodeError`, killing the hook
  before it produced output — indistinguishable from a hook that decided to do
  nothing. Hook output is now forced to UTF-8 and JSON escapes non-ASCII as well,
  so it survives either way. Caught by the Windows CI job added in 0.3.0.

### Added
- Open-loop check that runs the hook under a legacy encoding and fails if it dies.

## [0.3.0] - 2026-09-11

Windows support. Nothing about the harness was portable before this: the budget
hook was a shell script, registrations were shell form, and the guardian only
knew POSIX command shapes.

### Changed
- The budget hook is now `castra-budget.py`. Claude Code runs a shell-form hook
  through `sh -c` on macOS and Linux but through Git Bash on Windows, falling back
  to PowerShell when Git Bash is absent, so `.sh` could not work there.
- Hooks register in **exec form**, spawning the interpreter directly with an
  argument vector and no shell in between. This removes shell selection, quoting
  and variable expansion from the path entirely.
- The installer writes an absolute but deliberately unresolved interpreter path.
  Resolving symlinks pinned a version-specific directory such as
  `.../Cellar/python@3.14/3.14.6/...`, which disappears on the next patch upgrade
  and takes every hook down without a word.

### Added
- `install.ps1` for Windows and `install.sh` for macOS and Linux, both thin
  wrappers over a single `install.py` so every platform runs identical logic.
  `--dry-run` reports what would change without writing.
- PowerShell rules in the guardian: recursive `Remove-Item`, `Format-Volume`,
  `Clear-Disk`, `Set-ExecutionPolicy`, `iwr | iex`, `Start-Process -Verb RunAs`,
  service stops, and reading `.env` with `Get-Content`.
- `tests/run.py`, so the suite runs without a shell. CI now runs on Linux, macOS
  and Windows, and installs into a throwaway config directory on each.

## [0.2.0] - 2026-09-10

### Added
- `thinking-map` skill. Castra governs how work ends; this covers how it starts.
  Four stages: split the subject into orthogonal axes before writing any candidate,
  spread at least four per axis with the last one an inversion, cross-link items from
  different axes with a written mechanism per pair, then prune against a criterion
  fixed in advance. Two rules do the work — the orthogonality test that keeps axes
  from collapsing, and the mechanism sentence that separates a synthesis from a list
  pretending to be one. English and Korean versions ship together.
- The installer places the skill in `~/.claude/skills/thinking-map/` and leaves an
  existing skill of that name untouched.

## [0.1.1] - 2026-09-10

### Fixed
- Budget hook no longer prints a negative remaining-token count. When the assumed
  window is smaller than actual occupancy the threshold still fires, but the number
  shown to the model is clamped at zero instead of reading like a corrupted value.
- `castra_notes.py budget` explains an over-full result correctly: the window
  argument is too small, and omitting it lets detection choose. The previous message
  blamed transcript accumulation, which no longer applies now that occupancy is read
  from usage records.

### Added
- Regression check that fails if a negative remaining count reaches the output.

## [0.1.0] - 2026-09-10

First public release.

### Added
- Execution posture pack: 27 sections covering stance, authorization, verification
  standard, reporting, and precedence, including a per-model clause that weights
  the rule matching each model's own failure mode.
- Budget hook (`UserPromptSubmit`): reads real context occupancy from the session
  transcript's `usage` records and injects a reminder at a warning and a critical
  threshold.
- Automatic context window detection from the model id and the largest occupancy
  that model has been observed to reach, cached in `~/.castra-windows.json`.
- Guardian hook (`PreToolUse`): classifies shell commands into four verdicts before
  execution, with a read-only exemption narrow enough that a command containing any
  executing segment is still classified whole.
- Open-loop hook (`Stop`): refuses to end a turn while `.castra/openloops` has items.
- `castra_notes.py`: checkpoints that survive a context window reset.
- `castra_guardian.py`: the classifier, usable standalone.
- Installer that registers hooks without disturbing existing ones, and backs up
  `settings.json` before writing.
- 26 checks across three test files, each forcing the condition it verifies.
