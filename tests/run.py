#!/usr/bin/env python3
"""Run every Castra check. Exits non-zero if any of them fails."""
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent


def main() -> int:
    status = 0
    for test in sorted(HERE.glob("test_*.py")):
        print(f"-- {test.name}")
        if subprocess.run([sys.executable, str(test)], cwd=HERE).returncode:
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
