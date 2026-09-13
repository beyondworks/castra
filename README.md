# Castra

A development workflow and runtime support package for Claude Code. Castra helps a capable model carry an authorized request from observation to a verified result, retaining scoped state across interruptions. It does not copy private system prompts, change model weights, or establish equivalence to another model.

## Workflow

Use `/castra run <request>` after standalone installation, or `/castra:castra run <request>` in plugin mode. `castra: run <request>` also routes explicitly through UserPromptSubmit. Modes: `run`, `review`, `verify`, `reframe`, `finish`, `resume`, `status`; `castra: plain` skips workflow routing without disabling permissions or erasing evidence.

The contract starts with the user's affected surface and a discriminating check. It preserves current authorization and steering, uses independent work where useful, distinguishes source edits from installed/runtime outcomes, and stops after relevant work is verified. It requests decisions and evidence, not a private reasoning transcript. Fable and Opus use the same contract and selected model; no family-based capability or window-size guesses.

`castra: reframe <symptom>` restores the current contract and revisits the actual runtime and shared failure boundary. `castra: finish <task>` closes directly related omissions and relevant state/reload/failure transitions. Both preserve the original scope and authority. The ordinary run contract already uses these standards; the commands are recovery cues, not prerequisites for careful work.

## Runtime support

| Mechanism | Actual behavior | Limit |
|---|---|---|
| SessionStart | Injects a compact contract, script path, session id, scoped state and checkpoint | Restored notes are prior evidence, not new authority |
| UserPromptSubmit | Resets recovery, refreshes changed contract once per session and routes anchored `castra:` requests | Unchanged ordinary turns add no pack; hash records emission, not compliance |
| PostToolUse | Tracks supported edits; direct-script exits are observations only | Arbitrary shell writes and semantic coverage cannot be inferred |
| Stop | Blocks once on the ordinary recovery path; reentry allows an honest unresolved report | Circuit breaker is not success; user cancellation remains authoritative |
| Budget | Reads a bounded tail of this transcript, checks explicit capacity on prompts/tools | Last-response usage is an estimate; unknown capacity stays unknown |
| Guardian | Known risky syntax yields denial, platform confirmation or an authority reminder | Heuristic floor, not a sandbox or permission oracle |
| Release gate | Resolves a simple publication target and checks available CI runs for that commit | Ambiguous/multiple targets or unavailable CI require review; not branch-protection completeness |

Hooks run automatically. The explicit verification runner connects a declared file set to a relevant check, including files changed through an unrecognized shell tool:

```sh
python3 ~/.castra/scripts/castra_runtime.py status --session SESSION_ID
python3 ~/.castra/scripts/castra_runtime.py verify --session SESSION_ID --file src/example.py -- python3 -m unittest tests.test_example
python3 ~/.castra/scripts/castra_notes.py checkpoint --session SESSION_ID --goal 'user outcome' --progress 'observed evidence' --next 'next step'
python3 ~/.castra/scripts/castra_notes.py read --session SESSION_ID
```

Use the actual session id/script directory from the runtime hint. Plugin scripts live under the plugin root. `verify` runs argv without a shell, caps runtime, stores hashes/exit/time and returns a bounded diagnostic tail. Recognizable secrets are redacted best-effort; do not run credential-dumping checks. Commands/output are not retained in the evidence ledger. A green result establishes execution over the declared bytes, not semantic test adequacy. `defer` and `block` retain an explicit unresolved state with a reason code.

State lives under the working directory's `.castra/`, separated by a hash of the session id. Legacy `.castra/openloops`, `.astra/openloops` and unscoped checkpoints are preserved. For cross-session handoff, explicitly select the old session id; neighboring sessions are never automatically adopted.

Set `CASTRA_CONTEXT_WINDOW` only when the actual capacity is known. Castra cannot increase that capacity, create a new context window, send a message during a blocked call, or supply an absent tool. The installed Claude CLI may expose `--brief`/SendUserMessage; use it only when actually available, not as an assumed harness feature.

## Installation

Python 3.10+ is required. Choose one mode:

**Standalone (existing-user upgrade):**

```sh
python3 install.py --dry-run
python3 install.py
python3 install.py --check
```

This copies managed scripts/hooks/packs/skills and merges only Castra registrations. Existing unowned `thinking-map` skills are preserved. Modified/unowned managed destinations and symlinks are refused rather than overwritten. Backups and a rollback map are retained under `~/.castra/backups/`. v0.7 manifests omitted hooks: before migrating them, compare each installed hook with the previously committed source and add only those verified ownership hashes; do not adopt arbitrary files.

Restart Claude Code for new hook registrations. Sessions that already registered the route hook receive a changed contract at the next prompt; missing registrations cannot be hot-installed by a prompt. The managed block in `templates/claude-md-block.md` can replace a previous Castra block; it is not another full pack. `--check` tests installation integrity and isolated hook payloads, **not actual Claude events or model behavior**.

**Plugin (separate session):**

```sh
claude plugin validate .
claude --plugin-dir /absolute/path/to/castra
```

Do not load plugin mode in a profile that already has standalone Castra hooks. The installer refuses an enabled registered Castra plugin; a transient `--plugin-dir` remains the caller's responsibility. Plugin hooks use Python from PATH and `${CLAUDE_PLUGIN_ROOT}`; standalone hooks use an absolute interpreter/path with documented exec `args`. No MCP server, subscription change or permission bypass is required.

`install.sh` and `install.ps1` remain thin wrappers. This change's installed-event probes were run on macOS; Windows/Linux runtime behavior needs their own evidence, even where portable fixtures pass.

## Verification and boundaries

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tests/run.py
claude plugin validate .
```

Regression checks cover failed/unknown tool results, path collisions, concurrent writes, two sessions, modified-after-check state, bounded Stop recovery, scoped compaction, unknown capacity, byte budgets, installation ownership/rollback and real hook response shapes. Small live probes establish event connectivity, not comparative model quality. Do not turn a successful fixture into a general performance claim.

Contracts: [Claude Code hooks](https://code.claude.com/docs/en/hooks), [plugins](https://code.claude.com/docs/en/plugins), [plugin reference](https://code.claude.com/docs/en/plugins-reference). MIT; see [LICENSE](LICENSE).

Automatic tracking includes common code files, CSS/SCSS/HTML/Vue/Svelte, notebooks, CI workflow YAML and migration SQL/YAML. Ordinary Markdown/JSON/config edits remain excluded; explicitly verify them when behavior depends on them.
