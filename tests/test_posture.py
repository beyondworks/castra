#!/usr/bin/env python3
"""SessionStart hook: injects the pack, so no session has to open the file."""
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "castra-posture.py"
PACK = ROOT / "packs" / "execution-posture-pack.txt"


def run(payload: str = '{"hook_event_name":"SessionStart","source":"startup"}',
        cwd: pathlib.Path | None = None) -> str:
    proc = subprocess.run([sys.executable, str(HOOK)], input=payload,
                          capture_output=True, text=True, cwd=cwd or ROOT)
    return proc.stdout


def main() -> int:
    failures = []
    out = run()

    if "<castra_execution_posture>" not in out or "</castra_execution_posture>" not in out:
        failures.append("output is not wrapped in the posture tag")

    body = PACK.read_text(encoding="utf-8")
    # the whole pack must be present, not a summary of it
    missing = [line for line in body.splitlines()
               if line.startswith("## ") and line not in out]
    if missing:
        failures.append(f"{len(missing)} pack sections did not reach the output")

    # the three model-invoked commands had a zero call rate when they lived only
    # in a file, so they have to appear in the injected text itself
    for needle in ("castra_notes.py checkpoint", "castra_guardian.py", "openloops"):
        if needle not in out:
            failures.append(f"operative command missing from output: {needle}")

    # a missing pack must be silent rather than noisy
    with tempfile.TemporaryDirectory() as tmp:
        empty = pathlib.Path(tmp)
        (empty / "hooks").mkdir()
        copy = empty / "hooks" / "castra-posture.py"
        copy.write_text(HOOK.read_text(encoding="utf-8"), encoding="utf-8")
        proc = subprocess.run([sys.executable, str(copy)], input="{}",
                              capture_output=True, text=True, cwd=empty)
        # ~/.castra may exist on this machine; only assert it never crashes
        if proc.returncode != 0:
            failures.append("hook exited non-zero when the pack was absent")

    for f in failures:
        print("FAIL", f)
    print(f"{4 - len(failures)}/4 posture checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
