"""`x + y`, `f() + y`, `x + f()`, `items[0]` and `d['k']` run as one closure that reads the name
itself. Each must give the result and the error that the plain closures give: operand order, the
name's own position in an error, the checks of a result, and the paths read."""

import pytest

import tess_el
from tess_el import Limits, MapScope, TelError


def build(source, **kw):
    return tess_el.compile_expression(source, language="0.1", **kw)


def run(source, limits=None, **values):
    kw = {} if limits is None else {"limits": limits}
    return build(source, **kw).evaluate(MapScope(values))


def fails(source, code, limits=None, **values):
    with pytest.raises(TelError) as raised:
        run(source, limits, **values)
    assert raised.value.code == code, str(raised.value)
    return raised.value


VALUES = {"a": 7, "b": 3, "s": "ab", "l": [1, 2, 3], "d": {"k": 5, 2: "two"}, "f": 1.5}


@pytest.mark.parametrize(
    "source",
    [
        "(a - 1) + b",
        "(a - 1) - b",
        "(a - 1) * b",
        "a + (b * 2)",
        "a - (b * 2)",
        "a * (b + 1)",
        "(a + 1) + f",
        "a * (b - f)",
        "(s + s) + s",
        "s + (s + s)",
        "(l + l) + l",
        "l + (l + l)",
        "(s * 2) + s",
        "s * (b - 1)",
        "(l + [0]) * b",
        "l[0]",
        "l[-1]",
        "l[2]",
        "d['k']",
        "d[2]",
        "s[1]",
        "s[-2]",
        "l[0] + l[-1]",
    ],
)
def test_a_fused_shape_gives_what_python_gives(source):
    assert run(source, **VALUES) == eval(source, {}, dict(VALUES))  # noqa: S307


@pytest.mark.parametrize(
    ("source", "code"),
    [
        ("l[9]", "bad-index"),
        ("l[-9]", "bad-index"),
        ("d['zz']", "bad-index"),
        ("a[0]", "bad-index"),
        ("(a - 1) + s", "bad-operand"),
        ("s + (a - 1)", "bad-operand"),
        ("(a - 1) * d", "bad-operand"),
        ("(s + s) * s", "bad-operand"),
    ],
)
def test_a_fused_shape_fails_with_the_code_of_the_plain_one(source, code):
    fails(source, code, **VALUES)


def test_the_unknown_name_is_reported_at_its_own_place():
    for source, name in (("(a - 1) + zz", "zz"), ("zz + (a - 1)", "zz"), ("zz[0]", "zz")):
        error = fails(source, "unknown-name", **VALUES)
        assert f"'{name}' is not defined" in error.message
        start = (error.column or 1) - 1
        assert source[start : start + len(name)] == name, (source, error.column)


def test_the_left_operand_is_evaluated_before_the_name_on_the_right():
    fails("(1 // 0) + zz", "division-by-zero")  # both are wrong: the left one is the error


def test_the_name_on_the_left_is_read_before_the_right_operand_runs():
    assert "'zz'" in fails("zz + (1 // 0)", "unknown-name").message


@pytest.mark.parametrize(
    "source",
    ["(a * 1) * a", "a * (a * 1)", "(a + 0) - -a", "l[0] * a"],
)
def test_a_fused_arithmetic_still_checks_the_size_of_the_result(source):
    fails(source, "limit-int-bits", Limits(max_int_bits=100), a=2**99, l=[2**99])


def test_a_bool_index_is_not_the_integer_it_looks_like():
    assert run("l[True]", l=[10, 20]) == 20  # Python agrees: True is 1
    assert run("d[True]", d={1: "one"}) == "one"


def test_the_paths_read_are_those_of_the_name_inside_the_closure():
    expression = build("(a - 1) + b + l[0] + d['k']")
    scope = MapScope({"a": 1, "b": 2, "l": [3], "d": {"k": 4}})
    assert expression.evaluate_tracked(scope).reads >= {"a", "b", "l", "d"}
    assert build("a + b").evaluate_tracked(MapScope({"a": 1, "b": 2})).reads == {"a", "b"}


def test_a_comprehension_variable_is_not_read_from_the_scope():
    # `x` is a loop variable: it must not be fused as a scope name (the scope has no `x`)
    assert run("[x + b for x in l]", l=[1, 2], b=10) == [11, 12]
    assert run("[b + x for x in l]", l=[1, 2], b=10) == [11, 12]
    assert run("[x[0] for x in l]", l=[[5], [6]]) == [5, 6]
