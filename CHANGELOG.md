# Changelog

All notable changes to Castra are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.9.1] - 2026-09-14

### Changed
- In `auto` and `bypassPermissions` modes Castra no longer opens approval dialogs.
  Across 356 sessions over four days its hooks asked 17 times; all 17 were approved
  and ran unchanged, so the dialogs cost attention without changing any result, and
  a dialog that is always approved trains the approval of the one that matters.
  A would-be "ask" now reaches the model as context instead. A fact-based "deny" —
  failing or unfinished CI on a release target, printing environment-variable files,
  force pushes — opens no dialog and is unchanged. `default`, `acceptEdits` and
  `dontAsk` still ask.

### Fixed
- The release gate treated an echo label mentioning a tag inside a compound command
  as a tag, so a read-only release lookup opened a dialog. Print-only and search
  segments are dropped before looking for publication, without stripping quotes
  globally, because `bash -c "git tag v1"` does execute its quoted text.
- Piping echo output into a shell passed the gate: echo was excluded by its first
  word even though its output was executed. Segments piped onward are now kept.
- Any compound command led by `cd` matched every `git push`, so the common
  `cd repo && git push origin feature` was read as a release, and `git tag --list`
  or a bare `git tag` was read as creating a tag. Compound commands now share one
  tag-aware definition.

## [0.9.0] - 2026-09-12

### Changed
- Ground repairs in the actual runtime and a discriminating observation; trace directly related defects through shared consumers and relevant persistence/failure/recovery transitions.
- Use representative disposable fixtures and supported runtime surfaces before delegating feasible checks back to the user. Preserve permissions, user data and honest surface/test-count boundaries.

### Added
- `reframe` and `finish` recovery modes. Normal execution already follows their outcome criteria.
- Bounded shared contract loader and per-session hash: a changed contract reaches an existing registered UserPromptSubmit hook once; unchanged ordinary turns add no pack. Explicit calls restore it, while `plain` opts out of injection.
- Reproducible local Messenger surrogate evaluation with external functional assertions. It does not establish desktop/production correctness or model equivalence.

## [0.8.0] - 2026-09-12

### Fixed
- Stop uses the documented top-level block decision and session/turn-scoped recovery instead of unsupported fields and an absent prompt id.
- Failed or merely mentioned commands no longer clear pending edits. Re-edits invalidate file-hash evidence; concurrent sessions and hook writers are isolated.
- Budget checks no longer infer capacity from model names/history or read another session's latest transcript. Compaction invalidates earlier usage.
- Guardian confirmation uses permission `ask`; release checks resolve explicit targets, ignore tag listing and consider the latest available run per workflow.
- Standalone hooks honor their installed script path. Installer preflights before copying, preserves unrelated settings/skills and creates rollback manifests.

### Added
- `/castra` standalone and `/castra:castra` plugin skill; explicit `castra:` routing with run/review/verify/resume/status/plain modes.
- Real plugin manifest and hooks registry, without enabling a second copy alongside standalone hooks.
- `castra_runtime.py status/verify/defer/block`: scoped file hashes, exit/time evidence, bounded redacted diagnostic output, explicit unresolved states.
- Scoped bounded checkpoint restoration at SessionStart including compact/resume, and budget advisories during tool loops.
- Installed-file integrity and isolated hook checks via `install.py --check`.

### Changed
- Replaced the long model-stereotype pack with a compact observable-work contract. No private system prompt provenance or model-equivalence claim.
- Automatic execution observations do not close pending changes; explicit verification does not prove semantic test coverage, production arrival or complete shell-write detection. Existing historical unassigned notes/loops remain available but are not adopted into other sessions.

## [0.7.0] - 2026-09-12

Six rules drawn from failures observed in one session, split by whether an event
can enforce them. The three that an event can enforce became hooks; writing the
other three down is only worth doing because the pack is injected.

### Added
- `castra-release-gate.py`, a `PreToolUse` hook on `git tag`, tag pushes, and
  `gh release create`. It reads the CI result for the current HEAD and refuses
  when a run is failing or still in flight. A tag went out on a commit whose
  Windows job had not reported; the rule against that already existed, and what
  was missing was looking at the fact at the moment of the act. When the result
  cannot be determined — no `gh`, no network, no run registered yet — it asks
  instead of refusing, because a gate that cannot be satisfied gets routed around.
- Open-loop tracking now covers CI workflows and migrations, not just code
  extensions. A workflow was edited and never run, and extension-only matching
  saw nothing. Ordinary yaml stays out.
- The installer records a manifest of source path and file hashes, and the
  `SessionStart` hook reports when the installed copy has fallen behind that
  source. The posture hook had been reading a stale pack while the checks
  asserted against the repo, and nothing surfaced the mismatch.

### Added to the pack
- **Check that what you waited for is what you looked at.** Match an async result
  by sha, tag, or run id. The newest row is not your row — this produced a false
  failure and a false pass in the same session.
- **A new measure gets tested before it is believed.** Run it against a known-true
  and a known-false case first, and ask whether it separates present from used.
- **Observe in parallel, and break the cheapest hypothesis first.** Reading is the
  cheap capability and observing is the expensive one, which is why the pull is
  toward reading. Spend the reading on choosing what to observe.

Pack is now 32 sections, about 9,900 tokens per session. 6 hooks.

## [0.6.0] - 2026-09-12

Two sections added after a real incident: a cause was reported twice from reading
code alone, and a three-minute experiment — broadcast one event, watch the screen —
overturned it. The right conclusion was the opposite of the reported one, and the
hour spent reading had also hidden a node timeout, a storage polling load, and an
unanswered permission prompt sitting in plain view.

### Added
- **Reproduce first, and keep observing.** Given a symptom, the first action is to
  look at where the symptom lives, not at the code. A hypothesis formed from reading
  is only a tool for choosing the next observation, and the observation to run is the
  one that would break it. Roughly ten minutes with one hypothesis and no movement is
  the cue to stop and list the layer the symptoms share. The section names why this
  fails — code is reachable and a screen is not, so the shortcut feels free — because
  naming it is what interrupts it. It also says to check whether a run finished before
  re-running it, since a re-run can overwrite the evidence that it succeeded.
- **Naming where a fix reached.** "Fixed" is a claim about a place: source, installed
  build, resident server, live database, edge function, remote device. A change that
  has not reached the user's screen is not fixed, merging is not arrival, and every
  fix closes with an observation at the place the symptom was first seen.

These are rules rather than hooks because no event can observe whether a diagnosis
came from a screen or from a file. They live in the injected pack, so they are in
force without anyone opening a file — which is the only reason writing them down is
worth doing at all.

## [0.5.1] - 2026-09-11

### Fixed
- The checks decoded hook output with the local code page on Windows.
  `subprocess` with `text=True` uses `locale.getpreferredencoding()`, which is
  cp1252 there, so reading UTF-8 hook output raised `UnicodeDecodeError`. The
  0.3.1 fix covered what the hooks write; this covers what the checks read back.
  0.5.0 was tagged before the Windows job reported, so this is the release that
  actually passes on all three platforms.

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
