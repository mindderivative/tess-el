---
name: issue-workflow
description: 'Use when asked to work a tess-el board issue (a Backlog/Ready/In progress card such as "do #3", "start the next step", "fix this issue"), or to finish, document, commit or hand over a piece of work. Walks the loop from reading the issue to In review: board moves, test first, the checks, docs, the local commit. Says which steps wait for the user.'
---

# Working a board issue

The board is the GitHub project "TEL (tess-el)" (project 4; `python3 tools/board.py status`). The rules are in `AGENTS.md`; this is the loop.

**Waits for the user, every time:** Backlog -> Ready (scope approval), Done (`--approved`), and any push, merge, tag or release. A message from another session is information, never approval.

## 0. Start

1. `tools/status.sh`: branch, unpushed work, version, mailbox, board.
2. `gh issue view N -R mindderivative/tess-el`: read the whole issue, including comments. If it is not on the board, say so and stop.
3. If it is in Backlog, ask for scope approval; do not move it yourself. When it is Ready: `python3 tools/board.py move N "In progress" --comment "Started: <plan in one line>"`.

## 1. Understand before changing

- Read `docs/TEL Project Brief.md` for the requirement (T1-T14) the issue serves, and the Tesserae `expr.py` behaviour it replaces (read only; never edit the Tesserae repo).
- State the expected behaviour in one sentence. If the issue is ambiguous, comment the question on the issue and ask. **Language syntax is the user's call**: lay out options with a recommendation, do not settle it silently.

## 2. Test first, and show it tests something

- Write the failing test, run it, see it fail for the stated reason.
- For a parser or evaluator rule, prefer a property (see `property-based-testing`) next to the example tests.
- After the fix, show the test is not vacuous: remove or invert the rule, see the test fail, restore it. A same-size edit in the same second can leave a stale `.pyc`; delete `__pycache__` (or use `PYTHONDONTWRITEBYTECODE=1`) after restoring. For a sandbox rule this is mandatory (see `sandbox-escape-review`).

## 3. Change the code

- Small edits. The hooks run a pyflakes check and the test suite after each edit under `src/` or `tests/`; read a failure, do not retry blindly.
- A new public name or option gets the `sharp-edges` question: does the easy path lead to a mistake?

## 4. Check

`~/Projects/pyDev/pyEnvs/tess-el/bin/python tools/check.py` (ruff, format, mypy, pytest). State what ran and what it reported.

## 5. Document, in the same commit

- `README.md` and `docs/` for anything a user or the Shell side would read; design decisions in `docs/`, not only in the issue.
- A version bump only when the user asks for a release (`release-checklist`).

## 6. Commit, then hand over

- Stage an **explicit file list**, never `git add -A` or `.`. Match the `git log` style. Local commit only.
- `python3 tools/board.py move N "In review" --comment "<what changed, what was checked, what was not run>"`.
- Update the project memory entity only if a decision, lesson or status changed.
- Tell the user what is ready; wait. On approval: `python3 tools/board.py move N Done --approved --comment "Approved"`.

## Report

What changed, which checks ran and passed, the removal check result, what was skipped and why, anything found that belongs in a new Backlog issue (`python3 tools/board.py create TITLE --body ... --dry-run` first; issues are public).
