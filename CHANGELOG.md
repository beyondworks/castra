# Changelog

All notable changes to Castra are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
