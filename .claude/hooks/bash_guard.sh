#!/bin/sh
# PreToolUse (Bash): Block a release or PyPI upload, and a push except to feat/, fix/ or docs/ (never main, never force); before a `git commit`, check the staged Python files (pyflakes level).
cd "$CLAUDE_PROJECT_DIR" || exit 0
cmd=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))')
sep='(^|[;&|[:space:]])'
push="${sep}git[[:space:]]+([^;&|]*[[:space:]])?push([[:space:]]|\$)"
if printf '%s' "$cmd" | grep -Eq "$push"; then
  # Allowed only as the whole command: git push [-u|--set-upstream] origin <feat|fix|docs>/<name>.
  # No chaining, no colon or + refspec, no other option or remote, never main, never a force.
  allow='^[[:space:]]*git[[:space:]]+push([[:space:]]+(-u|--set-upstream))?[[:space:]]+origin[[:space:]]+(feat|fix|docs)/[A-Za-z0-9._/-]+[[:space:]]*$'
  if ! printf '%s' "$cmd" | grep -Ezq "$allow" || [ "$(printf '%s' "$cmd" | wc -l)" -gt 0 ]; then
    echo "Blocked: the only push allowed is: git push [-u] origin <feat|fix|docs>/<name> (AGENTS.md)." >&2
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
