#!/usr/bin/env python3
"""What is still behind before a piece of work is handed over. Read-only.

    python3 tools/wrapup.py

Prints one line per check: `ok`, `BEHIND` (something to do before calling the work done) or `note`
(information, or a check only a person can make). Exit status 1 if anything is BEHIND.

Checks: uncommitted changes; `ruff format --check` (as CI); commits not pushed (a note: pushing
waits for the user); the version in pyproject.toml and in `tel.__version__` agree; docs not touched
since code last changed; the graphify graph is current; cards still In progress or In review on the
board; memory (by hand).
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = ("src", "tests", "tools")
DOCS = ("README.md", "docs", "CHANGELOG.md")


def run(*cmd: str) -> tuple[int, str]:
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return done.returncode, done.stdout.strip()


def git_time(*paths: str) -> int:
    """Commit time of the newest commit touching any of the paths, or 0."""
    _, out = run("git", "log", "-1", "--format=%ct", "--", *paths)
    return int(out) if out else 0


def uncommitted() -> tuple[str, str]:
    _, out = run("git", "status", "--short")
    if not out:
        return "ok", "working tree clean"
    return (
        "BEHIND",
        f"{len(out.splitlines())} uncommitted path(s); commit with an explicit file list",
    )


def unpushed() -> tuple[str, str]:
    code, out = run("git", "rev-list", "--count", "@{upstream}..HEAD")
    if code != 0:
        return "note", "no upstream branch: nothing is pushed (pushing waits for the user)"
    if out == "0":
        return "ok", "nothing unpushed"
    return "note", f"{out} commit(s) not pushed (pushing waits for the user)"


def version() -> tuple[str, str]:
    pyproject = re.search(r'(?m)^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text())
    init = re.search(
        r'(?m)^__version__\s*=\s*"([^"]+)"', (ROOT / "src/tel/__init__.py").read_text()
    )
    if not pyproject or not init:
        return "BEHIND", "could not read the version from pyproject.toml or src/tel/__init__.py"
    if pyproject[1] != init[1]:
        return "BEHIND", f"pyproject.toml says {pyproject[1]}, tel.__version__ says {init[1]}"
    return "ok", f"version {pyproject[1]} in both places"


def docs() -> tuple[str, str]:
    code, doc = git_time(*CODE), git_time(*DOCS)
    if code > doc:
        return "BEHIND", "code changed since README.md / docs/ last did: update the documentation"
    return "ok", "docs are at least as new as the code"


def formatted() -> tuple[str, str]:
    """`ruff format --check`: it also formats the code blocks in Markdown, which CI runs."""
    venv = Path.home() / "Projects/pyDev/pyEnvs/tess-el/bin/ruff"
    ruff = str(venv) if venv.is_file() else "ruff"
    try:
        code, out = run(ruff, "format", "--check", ".")
    except FileNotFoundError:
        return "note", "ruff not found: format not checked"
    if code != 0:
        return "BEHIND", "ruff format --check fails (run ruff format on the files it names)"
    return "ok", "ruff format is clean"


def graph() -> tuple[str, str]:
    script = ROOT / "tools/graphify_refresh.sh"
    if not script.is_file():
        return "note", "no graphify refresh script"
    _, out = run(str(script), "--check")
    if out.startswith("graph is stale"):
        return "BEHIND", f"{out}; run `graphify update .`"
    return "ok", out or "graphify graph not built (or graphify not installed)"


def board() -> tuple[str, str]:
    code, out = run("python3", "-I", "tools/board.py", "status")
    if code != 0:
        return "note", "board not read (gh not logged in?)"
    open_cards: list[str] = []
    column = ""
    for line in out.splitlines():
        head = re.match(r"(Backlog|Ready|In progress|In review) \((\d+)\)", line)
        if head:
            column = head[1]
        elif line.strip().startswith("#") and column in ("In progress", "In review"):
            open_cards.append(f"{line.strip()} [{column}]")
    if open_cards:
        return "note", "cards in flight: " + "; ".join(open_cards)
    return "ok", "no cards in progress or in review"


def memory() -> tuple[str, str]:
    note = "not readable from here: update the tess-el entity if a decision or status changed"
    return "note", note


def main() -> int:
    behind = 0
    for name, check in [
        ("git", uncommitted),
        ("push", unpushed),
        ("version", version),
        ("docs", docs),
        ("format", formatted),
        ("graph", graph),
        ("board", board),
        ("memory", memory),
    ]:
        status, message = check()
        behind += status == "BEHIND"
        print(f"{status:<6} {name:<8} {message}")
    return 1 if behind else 0


if __name__ == "__main__":
    sys.exit(main())
