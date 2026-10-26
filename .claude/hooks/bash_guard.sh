#!/bin/sh
# PreToolUse (Bash): AGENTS.md allows local commits only. Block anything that publishes (git push,
# a release, a PyPI upload); before a `git commit`, check the staged Python files (pyflakes level).
cd "$CLAUDE_PROJECT_DIR" || exit 0
cmd=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))')
sep='(^|[;&|[:space:]])'
if printf '%s' "$cmd" | grep -Eq "${sep}git[[:space:]]+([^;&|]*[[:space:]])?push([[:space:]]|\$)|${sep}(twine[[:space:]]+upload|uv[[:space:]]+publish|gh[[:space:]]+release[[:space:]]+create)"; then
  echo "Blocked: publishing (push, release, PyPI upload) needs a separate, human-gated instruction (AGENTS.md). Commit locally only." >&2
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
