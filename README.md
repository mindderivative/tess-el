# TEL

TEL, the Tesserae Expression Language, is a small, safe expression language and a Python
library that parses and evaluates it. It lets plain YAML (or Python code) express
conditions, repeaters and live values.

> **Status:** planning. Nothing is implemented yet. See [`docs/`](docs/) for the project brief.

```python
import tel
```

PyPI name: `tess-el` (not yet published). Import name: `tel`.

## Development

```sh
uv pip install -e . --group dev   # into the active venv (Python 3.14+)
python tools/check.py             # ruff, format check, mypy (strict), pytest: what CI runs
python tools/wrapup.py            # what is still behind before work is handed over
tools/status.sh                   # branch, unpushed work, version, mailbox, board
```

Work is tracked on the [TEL (tess-el) board](https://github.com/users/mindderivative/projects/4)
(`python tools/board.py status`). `graphify update .` rebuilds the local code graph.
Agent instructions are in [`AGENTS.md`](AGENTS.md); project skills are in `.agents/skills/`.

## Versioning

See [`docs/versioning.md`](docs/versioning.md).

## Licence

[MIT](LICENSE)
