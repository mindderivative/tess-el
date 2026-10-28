# TEL

TEL, the Tesserae Expression Language, is a small, safe expression language and a Python
library that parses and evaluates it. It lets plain YAML (or Python code) express
conditions, repeaters and live values.

> **Status:** pre-alpha, language version 0.1.0. Expressions and `{{ }}` templates compile and
> evaluate; name tracking, conditions/repeaters and the Python builder are not built yet. The API may change.
> The design is in [`docs/language.md`](docs/language.md); what is protected, how it is checked and
> what is not guaranteed is in [`docs/security-review.md`](docs/security-review.md).

```python
import tel

expr = tel.compile_expression("'low' if battery < 20 else f'{battery}%'", language="0.1")
expr.evaluate(tel.MapScope({"battery": 63}))  # '63%'
expr.evaluate(tel.MapScope({"battery": 12}))  # 'low'
```

```python
template = tel.compile_template("Battery {{ battery }}%, {{ state }}", language="0.1")
template.evaluate(
    tel.MapScope({"battery": 63, "state": "discharging"})
)  # 'Battery 63%, discharging'
```

A template that is exactly one `{{ }}` part gives that part's value with its type; any other text with
parts gives text. Text with no part is not a template (`compile_template` returns `None`).

A bad expression is an error that says where (`tel.TelError`, with a stable `code`, a line and a
column), never a hang: every size and every loop is limited (`tel.Limits`). An expression can read
names from the scope you give it and call a few built-in functions and methods; it cannot reach
files, the process, the network, or an object's private attributes.

PyPI name: `tess-el` (not yet published). Import name: `tel`.

## Development

```sh
uv pip install -e . --group dev   # into the active venv (Python 3.14+)
python tools/check.py             # ruff, format check, mypy (strict), pytest: what CI runs
python tools/wrapup.py            # what is still behind before work is handed over
python tools/removal_check.py     # break each rule of the language on purpose: a test must fail
tools/status.sh                   # branch, unpushed work, version, mailbox, board
```

Work is tracked on the [TEL (tess-el) board](https://github.com/users/mindderivative/projects/4)
(`python tools/board.py status`). `graphify update .` rebuilds the local code graph.
Benchmarks: [`docs/benchmarks.md`](docs/benchmarks.md) (the `expr.py` baseline). Behaviour reference: [`docs/reference-cases.md`](docs/reference-cases.md).
Agent instructions are in [`AGENTS.md`](AGENTS.md); project skills are in `.agents/skills/`.

## Versioning

See [`docs/versioning.md`](docs/versioning.md).

## Licence

[MIT](LICENSE)
