---
name: castra
description: Castra development workflow for implementing, debugging, reviewing and resuming work with scoped runtime evidence. Use when the user requests Castra or its execution workflow.
argument-hint: "[run|review|verify|resume|status] [request]"
---

Use the supplied request: $ARGUMENTS. This skill works with the currently selected Claude model. It does not switch models or claim to reproduce another model's hidden reasoning.

Take the session id and script directory from the Castra runtime hint. If absent, inspect the installation before claiming automatic controls are active. Standalone scripts live under `${CASTRA_HOME:-$HOME/.castra}/scripts`; plugin scripts are beside the plugin's `skills/` directory. Resolve the actual path before use and quote shell arguments.

- **run** (default): Inspect the user's affected surface and current source. State outcome and the check that will demonstrate it. For a defect, obtain a reproduction or relevant runtime evidence, distinguish competing causes by an observation, make the smallest coherent repair, then rerun the discriminating check. Continue authorized work through the user's actual surface; obtain missing authority only for the dependent action.
- **review**: Read the requested diff and consumers; rank concrete defects by impact with paths and evidence. Do not edit unless requested. If requested findings are absent, say what you checked and what was not exercised.
- **verify**: Read runtime `status`, select the relevant checks and execute them through `verify`. Explicitly associate changed files with a check; mere path overlap is not coverage. Do not silently defer failures.
- **resume**: Read the current session's checkpoint and runtime status; verify referenced files and branch before continuing. For another session, use its explicitly supplied id. Restore the original objective plus later steering.
- **status**: Read runtime status and the latest checkpoint. Report observed, pending and deferred separately. A status question during active work does not cancel it.

Commands (replace SCRIPT_DIR and SESSION with the hint's actual values):

```sh
python3 SCRIPT_DIR/castra_runtime.py status --session SESSION
python3 SCRIPT_DIR/castra_runtime.py verify --session SESSION --file src/example.py -- python3 -m unittest tests.test_example
python3 SCRIPT_DIR/castra_notes.py checkpoint --session SESSION --goal 'user outcome' --progress 'observed evidence' --next 'next discriminating step'
python3 SCRIPT_DIR/castra_notes.py read --session SESSION
```

The verification command runs a real process with a timeout and records an exit result tied to file hashes. It is not a permission bypass or a semantic coverage oracle. A blocker can be recorded with the runtime `defer`/`block` command and an honest reason; it remains unresolved in the report. Never edit ledger JSON to manufacture success.

Keep the output focused on decisions and evidence, not private chain-of-thought. Do not promise background messages, fresh sessions, or deployment actions the current runtime cannot perform.
