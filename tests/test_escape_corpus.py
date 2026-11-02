"""The escape corpus (step 7): every line must be refused, by every way TEL reads text.

`tests/escape_corpus/*.txt` holds one expression per line, then a TAB and the error code it must
give, then a TAB and `# ` and the rule it breaks. Characters that are not printable ASCII are
written as `\\uXXXX` (and a newline as `\\n`). Each line is read as an expression, a condition, the
list and the key of a repeater and a template part: all must raise a `TelError`, none may touch the
`Trap` in the scope, and each must be quick. The expression gives exactly the pinned code.
"""

import re
import time
from pathlib import Path

import pytest
from reference.support import Plain, Trap

import tel
from tel import MapScope, TelError

CEILING = 0.5  # seconds for any one refusal; the real figure is a few milliseconds
DIRECTORY = Path(__file__).parent / "escape_corpus"
_ESCAPE = re.compile(r"\\u([0-9a-f]{4})|\\n")


def decode(text):
    return _ESCAPE.sub(lambda m: "\n" if m.group() == "\\n" else chr(int(m.group(1), 16)), text)


def load():
    rows = []
    for path in sorted(DIRECTORY.glob("*.txt")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if not line or line.startswith("#"):
                continue
            expression, code, rule = line.split("\t")
            assert rule.startswith("# "), (path.name, number)
            rows.append((path.stem, number, decode(expression), code, rule[2:]))
    return rows


ROWS = load()
IDS = [f"{name}:{number}" for name, number, *_ in ROWS]


def scope():
    return MapScope(
        {
            "x": 3,
            "d": {"k": 1},
            "items": [1, 2],
            "name": "ada",
            "xs": [1, 2],
            "s": "abc",
            "c": True,
            "y": 2,
            "a": 1,
            "b": 2,
            "obj": Plain(),
            "trap": Trap(),
            "ws": [Plain(), Plain()],
            "hosts": {"k": Plain()},
        }
    )


def read(expression):
    return tel.compile_expression(expression, language="0.1").evaluate(scope())


def as_condition(expression):
    return tel.compile_condition(expression, language="0.1").holds(scope())


def as_list(expression):
    repeater = tel.compile_repeater("w in " + expression, key="w", name="W", language="0.1")
    return repeater.items(scope())


def as_key(expression):
    repeater = tel.compile_repeater("w in xs", key=expression, name="W", language="0.1")
    return repeater.items(scope())


def as_part(expression):
    return tel.compile_template("a {{ " + expression + " }} b", language="0.1").evaluate(scope())


WAYS = [read, as_condition, as_list, as_key, as_part]


def test_the_corpus_is_not_empty_and_every_line_is_well_formed():
    assert len(ROWS) > 200
    assert {name for name, *_ in ROWS} >= {
        "attributes",
        "names",
        "syntax",
        "calls",
        "constants",
        "unicode",
        "limits",
        "hostobjects",
    }
    for _, _, expression, code, rule in ROWS:
        assert isinstance(expression, str) and code and rule


@pytest.mark.parametrize(("name", "number", "expression", "code", "rule"), ROWS, ids=IDS)
def test_every_line_is_refused_with_its_code_and_touches_nothing(
    name, number, expression, code, rule
):
    Trap.tripped.clear()
    start = time.perf_counter()
    with pytest.raises(TelError) as raised:
        read(expression)
    assert raised.value.code == code, rule
    assert Trap.tripped == [], rule
    assert time.perf_counter() - start < CEILING


@pytest.mark.parametrize("way", WAYS[1:], ids=[w.__name__ for w in WAYS[1:]])
def test_every_line_is_refused_by_every_other_way_of_reading_text_too(way):
    failures = []
    for name, number, expression, _code, rule in ROWS:
        Trap.tripped.clear()
        start = time.perf_counter()
        try:
            way(expression)
        except TelError:
            pass
        except Exception as error:  # anything else is a crash, not a refusal
            failures.append((name, number, type(error).__name__))
            continue
        else:
            failures.append((name, number, "accepted"))
        if Trap.tripped or time.perf_counter() - start >= CEILING:
            failures.append((name, number, "touched the trap or took too long", rule))
    assert failures == []
