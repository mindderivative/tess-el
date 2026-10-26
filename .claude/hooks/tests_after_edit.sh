#!/bin/sh
# PostToolUse (Edit|Write): run the test suite after an edit under src/ or tests/. The suite is small and headless; when it stops being quick, narrow this to the tests that cover the edited file.
cd "$CLAUDE_PROJECT_DIR" || exit 0
f=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))')
case "$f" in
  */src/*.py|*/tests/*.py) ;;
  *) exit 0 ;;
esac
pytest="$HOME/Projects/pyDev/pyEnvs/tess-el/bin/pytest"; [ -x "$pytest" ] || exit 0
out=$("$pytest" -q -x 2>&1) || { printf '%s\n' "$out" | tail -25 >&2; exit 2; }
exit 0
