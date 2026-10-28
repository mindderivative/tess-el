"""Every table of the behaviour reference, run against TEL as a set (step 3, phase 7).

`tests/test_reference_expr_py.py` proves the tables against `expr.py`, where they came from. This
is the same tables against TEL, and every case ends in exactly one outcome: a value, or a refusal
with a pinned error code. Where TEL differs from `expr.py` on purpose the difference is listed in
`docs/reference-cases.md`.
"""

import time

import pytest
from reference import cases
from reference.expectations import (
    DROPPED_HELPER_CASES,
    ESCAPE_CODES,
    EVALUATION_LEVEL,
    EVALUATION_LEVEL_ESCAPES,
    EVALUATION_LEVEL_LIMITS,
    PARSE_LEVEL_LIMITS,
    PARSE_REFUSED,
)
from reference.support import Plain, Trap

import tel
from tel import Limits, MapScope, Origin, TelError

CEILING = 0.5  # seconds for any one refusal; the real figure is a few milliseconds


def outcome(source, scope, limits=None, origin=None):
    """`("value", v)` or `("error", code)` for compiling and evaluating `source`."""
    kwargs = {}
    if limits is not None:
        kwargs["limits"] = limits
    if origin is not None:
        kwargs["origin"] = origin
    try:
        return "value", tel.compile_expression(source, language="0.1", **kwargs).evaluate(scope)
    except TelError as error:
        return "error", error.code


def reference_scope():
    return MapScope(cases.SCOPE_VALUES)


def escape_scope():
    return MapScope({**cases.ESCAPE_SCOPE_VALUES, "obj": Plain(), "trap": Trap()})


# -- every case is accounted for ------------------------------------------------------------------


def test_the_tables_are_the_ones_that_were_ported():
    sizes = {
        "ALLOWED": len(cases.ALLOWED),
        "DISALLOWED": len(cases.DISALLOWED),
        "ESCAPES": len(cases.ESCAPES),
        "LIMIT_CASES": len(cases.LIMIT_CASES),
        "POSITIONS": len(cases.POSITIONS),
    }
    assert sizes == {
        "ALLOWED": 100,
        "DISALLOWED": 55,
        "ESCAPES": 198,
        "LIMIT_CASES": 20,
        "POSITIONS": 4,
    }


def test_every_disallowed_case_has_exactly_one_pinned_outcome():
    sources = [c[0] for c in cases.DISALLOWED]
    assert len(set(sources)) == len(sources)
    pinned = set(PARSE_REFUSED) | set(EVALUATION_LEVEL)
    assert pinned == set(sources) and not set(PARSE_REFUSED) & set(EVALUATION_LEVEL)


def test_every_escape_has_a_pinned_code_and_the_deferred_ones_agree_with_theirs():
    assert len(ESCAPE_CODES) == len(cases.ESCAPES)
    pinned = dict(zip(cases.ESCAPES, ESCAPE_CODES, strict=True))
    for source, code in EVALUATION_LEVEL_ESCAPES.items():
        assert pinned[source] == code, source


def test_every_limit_case_has_exactly_one_pinned_outcome():
    sources = [c[0] for c in cases.LIMIT_CASES]
    assert len(set(sources)) == len(sources)
    assert set(PARSE_LEVEL_LIMITS) | set(EVALUATION_LEVEL_LIMITS) == set(sources)
    assert not set(PARSE_LEVEL_LIMITS) & set(EVALUATION_LEVEL_LIMITS)


# -- the tables, case by case ---------------------------------------------------------------------


@pytest.mark.parametrize("source, expected", cases.ALLOWED, ids=[c[0] for c in cases.ALLOWED])
def test_allowed(source, expected):
    kind, value = outcome(source, reference_scope())
    if source in DROPPED_HELPER_CASES:  # a helper dropped from the core (decision B)
        assert (kind, value) == ("error", "call-not-function")
    else:
        assert kind == "value" and value == expected


@pytest.mark.parametrize(
    "source, message", cases.DISALLOWED, ids=[c[0] or "''" for c in cases.DISALLOWED]
)
def test_disallowed(source, message):
    expected = PARSE_REFUSED.get(source) or EVALUATION_LEVEL[source]
    assert outcome(source, reference_scope()) == ("error", expected)


@pytest.mark.parametrize(
    "source, code",
    list(zip(cases.ESCAPES, ESCAPE_CODES, strict=True)),
    ids=[e[:40].replace("\n", " ") for e in cases.ESCAPES],
)
def test_escapes(source, code):
    Trap.tripped.clear()
    start = time.perf_counter()
    assert outcome(source, escape_scope()) == ("error", code)
    assert Trap.tripped == []
    assert time.perf_counter() - start < CEILING


@pytest.mark.parametrize(
    "source, message, limits", cases.LIMIT_CASES, ids=[c[0][:40] for c in cases.LIMIT_CASES]
)
def test_limits(source, message, limits):
    expected = {**PARSE_LEVEL_LIMITS, **EVALUATION_LEVEL_LIMITS}[source]
    start = time.perf_counter()
    assert outcome(source, MapScope(), Limits(**limits)) == ("error", expected)
    assert time.perf_counter() - start < CEILING


@pytest.mark.parametrize(
    "source, origin, evaluate, values, line, column, message",
    cases.POSITIONS,
    ids=["name-in-yaml", "syntax-after-space", "name-after-space", "multi-line"],
)
def test_positions(source, origin, evaluate, values, line, column, message):
    # expr.py counts columns from 0, TEL from 1: the origin and the expected column both move by one
    file, origin_line, origin_column = origin
    with pytest.raises(TelError) as raised:
        compiled = tel.compile_expression(
            source, language="0.1", origin=Origin(file, origin_line, origin_column + 1)
        )
        if evaluate:
            compiled.evaluate(MapScope(values))
    error = raised.value
    assert error.line == line
    if column is not None:
        assert error.column == column + 1
    assert message in str(error)
    assert str(error).startswith(f"{file}:{line}:")
