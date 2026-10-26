#!/usr/bin/env python3
"""Run every check CI runs, in one command: ruff (lint and format), mypy, pytest.

    python3 tools/check.py [--no-tests]

Uses the tools next to the interpreter that runs it, so run it with the project's venv python
(`~/Projects/pyDev/pyEnvs/tess-el/bin/python tools/check.py`). Stops at the first failure.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = Path(sys.executable).parent


def run(*cmd: str) -> bool:
    print(f"$ {' '.join(cmd)}", flush=True)
    return subprocess.run([str(BIN / cmd[0]), *cmd[1:]], cwd=ROOT).returncode == 0


def main(argv: list[str]) -> int:
    steps = [("ruff", "check", "."), ("ruff", "format", "--check", "."), ("mypy",)]
    if "--no-tests" not in argv:
        steps.append(("pytest", "-q"))
    for step in steps:
        if not run(*step):
            print(f"FAILED: {' '.join(step)}", file=sys.stderr)
            return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
