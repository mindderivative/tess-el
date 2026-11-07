# TEL

TEL, the Tesserae Expression Language, is a small, safe expression language and a Python library
that parses and evaluates it. It lets plain YAML (or Python code) express conditions, repeaters and
live values, without giving the text any way out of the sandbox.

!!! note "Status"
    Alpha: package 0.1.2, language version 0.1. The API may change before 1.0, and a minor version
    may break it ([versioning](versioning.md)). The package is `tesserae-el` on PyPI and is imported
    as `tess_el` (it was `tel` until 0.1.1).

## Install

TEL needs Python 3.14 or later and has no dependencies:

```sh
pip install tesserae-el
```

## A first expression

```python
import tess_el

expr = tess_el.compile_expression("'low' if battery < 20 else f'{battery}%'", language="0.1")
expr.evaluate(tess_el.MapScope({"battery": 63}))  # '63%'
expr.evaluate(tess_el.MapScope({"battery": 12}))  # 'low'
```

A conditional can also be written `cond ? a : b`. In YAML, quote a value that contains ` : `, since a
colon followed by a space ends a plain scalar.

## Where to read next

| If you want | Read |
|---|---|
| The language and the API, section by section | [Language specification](language.md) |
| What every error code means | [Error codes](error-codes.md) |
| What is protected, how it is checked, what is not guaranteed | [Security review](security-review.md) |
| Why a choice was made | [Decisions](decisions.md) |
| How fast it is, and against what | [Benchmarks](benchmarks.md) |
| What the reference cases from `expr.py` pin | [Reference cases](reference-cases.md) |
| How package and language versions work | [Versioning](versioning.md) |

The source, the issues and the changelog are on
[GitHub](https://github.com/mindderivative/tess-el); the package is on
[PyPI](https://pypi.org/project/tesserae-el/).
