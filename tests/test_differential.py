"""TEL against `expr.py`: random expressions must give the same value, or both be refused.

Skipped when the Tesserae clone is absent (CI). Where TEL is deliberately stricter than `expr.py`,
the generator avoids the construct; the list of those is in `docs/reference-cases.md`.
"""

import math
import random

import pytest
from reference import expr_py

import tel

pytestmark = pytest.mark.skipif(not expr_py.available(), reason="the Tesserae clone is not here")

SCOPE = {
    "a": 7,
    "b": -3,
    "c": 0,
    "f": 2.5,
    "s": "hello",
    "t": "",
    "l": [3, 1, 2],
    "e": [],
    "d": {"k": 1, "j": 2},
    "n": None,
    "flag": True,
}
NAMES = list(SCOPE)
LITERALS = [
    "0",
    "1",
    "2",
    "-1",
    "5",
    "2.5",
    "0.5",
    "'a'",
    "'lo'",
    "''",
    "True",
    "None",
    "[1, 2]",
    "(1, 2)",
]
NUMBERS = ["a", "b", "c", "f", "0", "1", "2", "-1", "5", "2.5", "0.5", "flag"]
ARITH = ["+", "-", "*", "//", "%", "/"]
METHOD_CALLS = [
    "s.upper()",
    "s.split('l')",
    "s.startswith('h')",
    "t.strip()",
    "l.count(1)",
    "d.get('k')",
    "d.get('zz', 0)",
    "d.keys()",
    "d.items()",
    "s.replace('l', 'L')",
    "'-'.join(['x', 'y'])",
    "s.find('l')",
    "s.title()",
]
COMPARE = ["==", "!=", "<", "<=", ">", ">=", "in", "not in"]


def gen(rng: random.Random, depth: int = 0, loop: bool = False) -> str:
    atoms = NAMES + LITERALS + (["i"] if loop else [])
    if depth > 3 or rng.random() < 0.3:
        return rng.choice(atoms)
    sub = lambda: gen(rng, depth + 1, loop)  # noqa: E731
    kind = rng.random()
    if kind < 0.22:
        return f"({sub()} {rng.choice(ARITH)} {sub()})"
    if kind < 0.28:
        return f"({sub()} ** {rng.choice(['0', '1', '2', '3'])})"
    if kind < 0.42:
        return f"({sub()} {rng.choice(COMPARE)} {sub()})"
    if kind < 0.52:
        return f"({sub()} {rng.choice(['and', 'or'])} {sub()})"
    if kind < 0.56:
        return f"(not {sub()})"
    if kind < 0.62:
        return f"({sub()} if {sub()} else {sub()})"
    if kind < 0.68:
        index = rng.choice(["0", "1", "-1", "2", repr("k"), repr("zz")])
        return f"{rng.choice(['l', 's', 'e', 'd'])}[{index}]"
    if kind < 0.74:
        return f"{rng.choice(['len', 'abs', 'str', 'int', 'bool', 'round', 'float'])}({sub()})"
    if kind < 0.78:
        # numbers only: expr.py turns every container argument of min/max into a list, so it
        # compares the contents of two texts (or a dict and a text) where Python refuses
        return f"{rng.choice(['min', 'max'])}({rng.choice(NUMBERS)}, {rng.choice(NUMBERS)})"
    if kind < 0.83:
        function = rng.choice(["sum", "sorted", "list", "tuple", "any", "all"])
        return f"{function}({rng.choice(['l', 'e', sub()])})"
    if kind < 0.88:
        return rng.choice(METHOD_CALLS)
    if kind < 0.94:
        inner = gen(rng, depth + 1, True)
        cond = f" if {gen(rng, depth + 1, True)}" if rng.random() < 0.4 else ""
        return f"[{inner} for i in {rng.choice(['l', 'e', 's', 'd', 'range(3)'])}{cond}]"
    return f"f'{{{sub()}}}'"


def same(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return (math.isnan(a) and math.isnan(b)) or a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    return bool(a == b) and type(a) is type(b)


def outcomes(source: str):
    old = expr_py.load()
    try:
        theirs = ("value", old.compile_expr(source).evaluate(old.MapScope(SCOPE)))
    except old.ExprError:
        theirs = ("error", None)
    try:
        ours = (
            "value",
            tel.compile_expression(source, language="0.1").evaluate(tel.MapScope(SCOPE)),
        )
    except tel.TelError:
        ours = ("error", None)
    return ours, theirs


def test_random_expressions_agree_with_expr_py():
    rng = random.Random(20261027)
    values = errors = 0
    mismatches = []
    for _ in range(4000):
        source = gen(rng)
        ours, theirs = outcomes(source)
        if ours[0] != theirs[0] or (ours[0] == "value" and not same(ours[1], theirs[1])):
            mismatches.append((source, ours, theirs))
        values += ours[0] == "value"
        errors += ours[0] == "error"
    assert mismatches == [], mismatches[:5]
    assert values > 800 and errors > 800  # both sides of the language were exercised
