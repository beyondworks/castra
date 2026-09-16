#!/usr/bin/env python3
"""SessionStart hook: injects the pack, so no session has to open the file."""
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "castra-posture.py"
PACK = ROOT / "packs" / "execution-posture-pack.txt"


def run(payload: str = '{"hook_event_name":"SessionStart","source":"startup"}',
        cwd: pathlib.Path | None = None) -> str:
    # Point CASTRA_HOME at the repo so the check reads the pack it asserts against
    # rather than whatever happens to be installed on this machine.
    env = dict(os.environ, CASTRA_HOME=str(ROOT))
    proc = subprocess.run([sys.executable, str(HOOK)], input=payload,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd or ROOT, env=env)
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

    # Only one thing is still called by hand, and it has to appear in the
    # injected text rather than in a file the model would have to open.
    if "castra_notes.py checkpoint" not in out:
        failures.append("the checkpoint command is missing from the output")

    # The guard and the open-loop record run from tool events now. Advertising
    # them as commands to call would reintroduce the dependence on the model
    # choosing to call something, which measured zero.
    for stale in ("castra_guardian.py \"", ">> .castra/openloops"):
        if stale in out:
            failures.append(f"output still asks the model to call: {stale}")

    # a stale install must announce itself: the hook read an old pack while the
    # checks asserted against the repo, and nothing surfaced the mismatch
    with tempfile.TemporaryDirectory() as tmp:
        home = pathlib.Path(tmp)
        (home / "packs").mkdir()
        (home / "packs" / "execution-posture-pack.txt").write_text(
            "## Old\nstale body\n", encoding="utf-8")
        (home / "manifest.json").write_text(json.dumps({
            "source": str(ROOT),
            "files": {"packs/execution-posture-pack.txt": "0" * 16},
        }), encoding="utf-8")
        env = dict(os.environ, CASTRA_HOME=str(home))
        proc = subprocess.run([sys.executable, str(HOOK)], input="{}",
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", cwd=ROOT, env=env)
        if "설치본이 정본보다 낡았다" not in proc.stdout:
            failures.append("a stale install produced no drift notice")

        # matching hashes must stay quiet
        digest = hashlib.sha256(PACK.read_bytes()).hexdigest()[:16]
        (home / "manifest.json").write_text(json.dumps({
            "source": str(ROOT),
            "files": {"packs/execution-posture-pack.txt": digest},
        }), encoding="utf-8")
        proc = subprocess.run([sys.executable, str(HOOK)], input="{}",
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", cwd=ROOT, env=env)
        if "설치본이 정본보다" in proc.stdout:
            failures.append("a matching install still reported drift")

    # a missing pack must be silent rather than noisy
    with tempfile.TemporaryDirectory() as tmp:
        empty = pathlib.Path(tmp)
        (empty / "hooks").mkdir()
        copy = empty / "hooks" / "castra-posture.py"
        copy.write_text(HOOK.read_text(encoding="utf-8"), encoding="utf-8")
        proc = subprocess.run([sys.executable, str(copy)], input="{}",
                              capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=empty)
        # ~/.castra may exist on this machine; only assert it never crashes
        if proc.returncode != 0:
            failures.append("hook exited non-zero when the pack was absent")

    # A desktop session can start at '/', which macOS mounts read-only. Recording
    # the emission raised there, so the hook dropped the contract it had loaded.
    checks = 6
    if os.name != "nt" and os.geteuid() != 0:
        checks += 1
        with tempfile.TemporaryDirectory() as tmp:
            locked = pathlib.Path(tmp) / "readonly"
            locked.mkdir()
            locked.chmod(0o500)
            home = pathlib.Path(tmp) / "home"
            payload = json.dumps({"hook_event_name": "SessionStart", "source": "startup",
                                  "session_id": "readonly-probe", "cwd": str(locked)})
            try:
                proc = subprocess.run([sys.executable, str(HOOK)], input=payload,
                                      capture_output=True, text=True, encoding="utf-8", errors="replace",
                                      cwd=ROOT, env=dict(os.environ, CASTRA_HOME=str(home)))
            finally:
                locked.chmod(0o700)
            if ("<castra_execution_posture>" not in proc.stdout
                    or "restoration failed" in proc.stdout
                    or not list(home.glob("sessions/*.json"))):
                failures.append("an unwritable cwd dropped the contract or its session state")

    for f in failures:
        print("FAIL", f)
    print(f"{checks - len(failures)}/{checks} posture checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
