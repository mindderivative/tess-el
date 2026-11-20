#!/bin/sh
# PreToolUse (Bash): Block a release or PyPI upload, and a push except to feat/, fix/ or docs/ (never main, never force); before a `git commit`, check the staged Python files (pyflakes level).
cd "$CLAUDE_PROJECT_DIR" || exit 0
cmd=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))')
sep='(^|[;&|[:space:]])'
push="${sep}git[[:space:]]+([^;&|]*[[:space:]])?push([[:space:]]|\$)"
if printf '%s' "$cmd" | grep -Eq "$push"; then
  # Allowed: a push to a feat/, fix/ or docs/ branch. Never main/master, never a force, never a bare push.
  if printf '%s' "$cmd" | grep -Eq "(--force|--delete|[[:space:]]-[a-zA-Z]*[fd][a-zA-Z]*([[:space:]]|\$)|[[:space:]]\+|main|master)" \
     || ! printf '%s' "$cmd" | grep -Eq "[[:space:]](feat|fix|docs)/[A-Za-z0-9._/-]+"; then
    echo "Blocked: push only to feat/, fix/ or docs/ branches; never main, never force (AGENTS.md)." >&2
    exit 2
  fi
fi
if printf '%s' "$cmd" | grep -Eq "${sep}(twine[[:space:]]+upload|uv[[:space:]]+publish|gh[[:space:]]+release[[:space:]]+create)"; then
  echo "Blocked: releases and PyPI uploads need the owner (AGENTS.md)." >&2
  exit 2
fi
if printf '%s' "$cmd" | grep -Eq "${sep}git[[:space:]]+commit([[:space:]]|\$)"; then
  ruff="$HOME/Projects/pyDev/pyEnvs/tess-el/bin/ruff"; [ -x "$ruff" ] || ruff=$(command -v ruff)
  staged=$(git diff --cached --name-only --diff-filter=ACM -- '*.py')
  if [ -n "$ruff" ] && [ -n "$staged" ]; then
    out=$(printf '%s\n' "$staged" | xargs "$ruff" check --isolated --select E9,F --quiet 2>&1) || { printf 'ruff found problems in staged files:\n%s\n' "$out" >&2; exit 2; }
  fi
fi
exit 0
