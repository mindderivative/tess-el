# TEL

TEL, the Tesserae Expression Language, is a small, safe expression language and a Python
library that parses and evaluates it. It lets plain YAML (or Python code) express
conditions, repeaters and live values.

> **Status:** alpha, package 0.1.0, language version 0.1. The API may change before 1.0 (a minor
> version may break it; see [`docs/versioning.md`](https://github.com/mindderivative/tess-el/blob/main/docs/versioning.md)).
> The design is in [`docs/language.md`](https://github.com/mindderivative/tess-el/blob/main/docs/language.md);
> what is protected, how it is checked and what is not guaranteed is in
> [`docs/security-review.md`](https://github.com/mindderivative/tess-el/blob/main/docs/security-review.md).

TEL needs Python 3.14 or later and has no dependencies:

```sh
pip install tesserae-el
```

It evaluates expressions and `{{ }}` templates (with limits and positions in errors), tracks the names
and attribute paths an evaluation read, takes host functions and methods, reads conditions
(`compile_condition`, `select`) and repeaters (`compile_repeater`, `reconcile`) for a host that
builds the tree, and builds expression text from Python values (`fill`, `canonical`).

```python
import tel

expr = tel.compile_expression("'low' if battery < 20 else f'{battery}%'", language="0.1")
expr.evaluate(tel.MapScope({"battery": 63}))  # '63%'
expr.evaluate(tel.MapScope({"battery": 12}))  # 'low'
```

A conditional can also be written `cond ? a : b`: the same as `a if cond else b`, with the same
precedence (lowest, right-associative), and it may not be mixed with `if/else` without brackets.
**In YAML, quote a value that contains ` : `**: a colon followed by a space ends a plain scalar, so
`x: a ? b : c` is a YAML error and `- a ? b : c` is read as a mapping.

A condition reads an expression as yes or no. The host owns the `if:`, `elif:` and `else:` keys;
`select` gives the index of the first condition that holds, or `None` for the `else`, and
`select_tracked` also gives the paths read by every condition tested up to the winner.

```python
chain = [tel.compile_condition(t, language="0.1") for t in ("unread > 0", "muted")]
tel.select(chain, tel.MapScope({"unread": 0, "muted": True}))  # 1
```

In YAML, give a condition or a key as text: quote a value with ` : ` in it, and quote a bare `true`
or `1`, which YAML loads as a bool or an int (TEL refuses a non-text value with a `TypeError`).

To build an expression in Python, fill placeholders with values: each `$name` (outside strings and
comments) becomes a checked literal, so a value can only be data and a string is quoted. The result is
text for any `compile_*` function.

```python
text = tel.fill("battery < $limit or name in $names", {"limit": 20, "names": ["a", "b"]})
# "battery < 20 or name in ['a', 'b']"
tel.fill_template("Hello {{ $who }}!", {"who": "Ada"})  # "Hello {{ 'Ada' }}!"
```

Two spellings of one expression have one canonical text, for comparing an expression built in Python
with one written as text (compare within one run; do not store it):

```python
tel.compile_expression("a<20", language="0.1").canonical  # 'a < 20'
tel.compile_expression("c ? a : b", language="0.1").canonical  # 'a if c else b'
```

A repeater reads a header (`item in items`, or `i, item in enumerate(items)`) and a key expression,
and gives the list's items with their keys. The host owns the `for:` and `key:` keys and builds the
nodes; each item's `scope(parent)` is the scope for its children.

```python
rep = tel.compile_repeater("w in workspaces", key="w.id", name="Workspace", language="0.1")
items = rep.items(tel.MapScope({"workspaces": [{"id": 7}, {"id": 9}]}))
[(item.index, item.key) for item in items]  # [(0, 7), (1, 9)]

# keep the state between calls: entries are new or kept, and keys can be removed
both = tel.MapScope({"workspaces": [{"id": 7}, {"id": 9}]})
result = rep.reconcile(both, tel.RepeaterState())
[e.name for e in result.entries]  # ['Workspace_0001', 'Workspace_0002']
result = rep.reconcile(tel.MapScope({"workspaces": [{"id": 9}]}), result.state)
(result.removed, result.entries[0].name)  # ((7,), 'Workspace_0002')
```
A file that holds the loop variable, the list and the key apart (the Shell's TDL) passes them
separately, each with its own origin; the result is the same repeater:

```python
rep = tel.compile_repeater_parts(
    "w",
    "workspaces",
    key="w.id",
    name="Workspace",
    language="0.1",
    names_origin=tel.Origin("A.tdl", 12, 9),
    items_origin=tel.Origin("A.tdl", 12, 15),
    key_origin=tel.Origin("A.tdl", 12, 35),
)
```


```python
template = tel.compile_template("Battery {{ battery }}%, {{ state }}", language="0.1")
template.evaluate(
    tel.MapScope({"battery": 63, "state": "discharging"})
)  # 'Battery 63%, discharging'
```

A host adds its own functions and methods when it compiles. TEL calls only what the host listed:

```python
expr = tel.compile_expression(
    "format_number(total, 1) + ' ' + price.formatted()",
    language="0.1",
    functions={"format_number": lambda x, digits=0: f"{x:,.{digits}f}"},
    methods={Price: {"formatted": Price.formatted}},
)
```

To know which names an evaluation actually read, so a host re-runs it only when one of them changes:

```python
expr = tel.compile_expression("'low' if battery < 20 else state", language="0.1")
value, reads = expr.evaluate_tracked(tel.MapScope({"battery": 63, "state": "ok"}))
# value == 'ok', reads == {'battery', 'state'}; with battery=12 it reads only {'battery'}
```

A read is a name, or an attribute chain on a name: `RootShell.DP1.Top_Bar.Width` reports that whole
path, so an expression depends only on what it reads. `Tracked.names` gives the top-level names, and
`expr.paths` every path in the text, before any evaluation.

A scope is anything with `lookup(name)` (the value, or `KeyError`) and optionally `names()`. What TEL
may ask of it, and what it must do in return (quick, no effects, plain values), is written clause by
clause in [`docs/language.md`](https://github.com/mindderivative/tess-el/blob/main/docs/language.md) section 12.2 and tested in
`tests/test_scope_contract.py`.

A template that is exactly one `{{ }}` part gives that part's value with its type; any other text with
parts gives text. Text with no part is a template that evaluates to itself (`Template.is_text`).

A bad expression is an error that says where (`tel.TelError`, with a stable `code`, a line and a
column), never a hang: every size and every loop is limited (`tel.Limits`). An expression can read
names from the scope you give it and call a few built-in functions and methods; it cannot reach
files, the process, the network, or an object's private attributes.

PyPI name: `tesserae-el` (not yet published). Import name: `tel`.

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
Benchmarks: [`docs/benchmarks.md`](https://github.com/mindderivative/tess-el/blob/main/docs/benchmarks.md) (the `expr.py` baseline). Behaviour reference: [`docs/reference-cases.md`](https://github.com/mindderivative/tess-el/blob/main/docs/reference-cases.md).
Agent instructions are in [`AGENTS.md`](AGENTS.md); project skills are in `.agents/skills/`.

## Versioning

See [`docs/versioning.md`](https://github.com/mindderivative/tess-el/blob/main/docs/versioning.md).

## Licence

[MIT](https://github.com/mindderivative/tess-el/blob/main/LICENSE)
