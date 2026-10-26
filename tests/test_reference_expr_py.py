"""The ported behaviour tables, run against `expr.py` itself.

This proves the port is faithful: every table passes on the implementation it came from. When TEL's
evaluator exists (step 3) the same tables run against it. Skipped when the Tesserae clone is absent
(CI), because TEL never depends on it.
"""

import re

import pytest
from reference import cases, expr_py
from reference.support import Plain, Trap

pytestmark = pytest.mark.skipif(not expr_py.available(), reason="the Tesserae clone is not here")


@pytest.fixture(scope="module")
def expr():  # type: ignore[no-untyped-def]
    return expr_py.load()


def escape_scope(expr):  # type: ignore[no-untyped-def]
    return expr.MapScope({**cases.ESCAPE_SCOPE_VALUES, "obj": Plain(), "trap": Trap()})


@pytest.mark.parametrize("source, expected", cases.ALLOWED, ids=[c[0] for c in cases.ALLOWED])
def test_allowed(expr, source, expected):  # type: ignore[no-untyped-def]
    assert expr.compile_expr(source).evaluate(expr.MapScope(cases.SCOPE_VALUES)) == expected


_disallowed = [c for c in cases.DISALLOWED if c[1] is not None]


@pytest.mark.parametrize("source, message", _disallowed, ids=[c[0] or "''" for c in _disallowed])
def test_disallowed(expr, source, message):  # type: ignore[no-untyped-def]
    with pytest.raises(expr.ExprError, match=re.escape(message)):
        expr.compile_expr(source).evaluate(expr.MapScope(cases.SCOPE_VALUES))


@pytest.mark.parametrize(
    "source", cases.ESCAPES, ids=[e[:60].replace("\n", " ") for e in cases.ESCAPES]
)
def test_escapes_fail_and_never_reach_the_trap(expr, source):  # type: ignore[no-untyped-def]
    Trap.tripped.clear()
    with pytest.raises(expr.ExprError):
        expr.compile_expr(source).evaluate(escape_scope(expr))
    assert Trap.tripped == []


@pytest.mark.parametrize(
    "source, message, limits", cases.LIMIT_CASES, ids=[c[0][:50] for c in cases.LIMIT_CASES]
)
def test_limits(expr, source, message, limits):  # type: ignore[no-untyped-def]
    with pytest.raises(expr.ExprError, match=message):
        expr.compile_expr(source, limits=expr.Limits(**limits)).evaluate(expr.MapScope())


@pytest.mark.parametrize("source, origin, run, values, line, column, message", cases.POSITIONS)
def test_positions(expr, source, origin, run, values, line, column, message):  # type: ignore[no-untyped-def]
    with pytest.raises(expr.ExprError) as raised:
        compiled = expr.compile_expr(source, origin=expr.Origin(*origin))
        if run:
            compiled.evaluate(expr.MapScope(values))
    assert raised.value.line == line
    if column is not None:
        assert raised.value.column == column
    assert message in str(raised.value)
