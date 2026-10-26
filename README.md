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
pytest
ruff check . && ruff format --check .
mypy
```

## Versioning

See [`docs/versioning.md`](docs/versioning.md).

## Licence

[MIT](LICENSE)
