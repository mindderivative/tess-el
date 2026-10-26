#!/usr/bin/env bash
# Where the project stands, in one screen:  tools/status.sh
#
# Read-only. Shows the branch and what is not pushed, the working tree, the version, waiting
# mailbox messages and the open cards on the GitHub board (tools/board.py). The board part is
# skipped with a note if `gh` is not logged in.
set -uo pipefail
cd "$(dirname "$0")/.."

echo "== git"
echo "branch: $(git branch --show-current)"
upstream=$(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null || true)
if [ -n "$upstream" ]; then
    echo "not pushed to $upstream: $(git rev-list --count "$upstream"..HEAD) commit(s)"
else
    echo "no upstream branch: nothing of this branch is pushed"
fi
dirty=$(git status --short)
if [ -n "$dirty" ]; then echo "uncommitted:"; echo "$dirty" | sed 's/^/  /'; else echo "working tree clean"; fi
echo "recent:"; git log --oneline -5 | sed 's/^/  /'

echo
echo "== version"
grep -m1 '^version' pyproject.toml
grep -m1 '__version__' src/tel/__init__.py

echo
echo "== mailbox"
if [ -f "$HOME/.claude/mailbox/cli.py" ]; then
    echo "messages waiting: $(python3 -I "$HOME/.claude/mailbox/cli.py" pending 2>/dev/null || echo 'not configured for this project')"
else
    echo "no mailbox on this machine"
fi

echo
echo "== board"
if gh auth status >/dev/null 2>&1; then
    python3 -I tools/board.py status
else
    echo "gh is not logged in; skipped"
fi
