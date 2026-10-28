"""The evaluator (step 3, phase 4): what an expression gives, and what it is refused."""

import datetime
import decimal
import enum
import types
from dataclasses import dataclass

import pytest
from reference import cases
from reference.expectations import (
    DROPPED_HELPER_CASES,
    EVALUATION_LEVEL,
    EVALUATION_LEVEL_ESCAPES,
    EVALUATION_LEVEL_LIMITS,
    PARSE_LEVEL_LIMITS,
)
from reference.support import Plain, Trap

import tel
from tel import Limits, MapScope, Origin, TelError


def build(source, **kw):
    return tel.compile_expression(source, language="0.1", **kw)


def run(source, scope=None, **values):
    return build(source).evaluate(scope if scope is not None else MapScope(values))


def fails(source, code, scope=None, **values):
    with pytest.raises(TelError) as raised:
        run(source, scope, **values)
    assert raised.value.code == code, str(raised.value)
    return raised.value


def reference_scope():
    return MapScope(cases.SCOPE_VALUES)


def escape_scope():
    return MapScope({**cases.ESCAPE_SCOPE_VALUES, "obj": Plain(), "trap": Trap()})


# -- the reference tables -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, expected",
    [c for c in cases.ALLOWED if c[0] not in DROPPED_HELPER_CASES],
    ids=[c[0] for c in cases.ALLOWED if c[0] not in DROPPED_HELPER_CASES],
)
def test_the_grammar_allows_and_gives_the_value(source, expected):
    assert build(source).evaluate(reference_scope()) == expected


@pytest.mark.parametrize("source, code", list(EVALUATION_LEVEL.items()))
def test_what_the_parser_leaves_to_a_value_is_refused_here(source, code):
    with pytest.raises(TelError) as raised:
        build(source).evaluate(reference_scope())
    assert raised.value.code == code


@pytest.mark.parametrize(
    "source", cases.ESCAPES, ids=[e[:50].replace("\n", " ") for e in cases.ESCAPES]
)
def test_every_escape_fails_and_never_reaches_the_trap(source):
    Trap.tripped.clear()
    with pytest.raises(TelError) as raised:
        build(source).evaluate(escape_scope())
    assert Trap.tripped == []
    if source in EVALUATION_LEVEL_ESCAPES:
        assert raised.value.code == EVALUATION_LEVEL_ESCAPES[source]


def test_the_limit_tables_are_covered_exactly():
    assert set(PARSE_LEVEL_LIMITS) | set(EVALUATION_LEVEL_LIMITS) == {
        c[0] for c in cases.LIMIT_CASES
    }
    assert not set(PARSE_LEVEL_LIMITS) & set(EVALUATION_LEVEL_LIMITS)


@pytest.mark.parametrize(
    "source, message, limits",
    cases.LIMIT_CASES,
    ids=[c[0][:40] for c in cases.LIMIT_CASES],
)
def test_every_limit_is_a_named_error(source, message, limits):
    codes = {**PARSE_LEVEL_LIMITS, **EVALUATION_LEVEL_LIMITS}
    with pytest.raises(tel.TelLimitError) as raised:
        build(source, limits=Limits(**limits)).evaluate(MapScope())
    assert raised.value.code == codes[source]


# -- names and scope ------------------------------------------------------------------------------


def test_an_unknown_name_suggests_the_nearest_name_in_the_scope():
    error = fails("cnt + 1", "unknown-name", count=1)
    assert error.hint == "did you mean 'count'" and "'cnt' is not defined" in error.message


def test_an_unknown_name_with_no_near_scope_name_suggests_a_built_in():
    assert fails("lenn", "unknown-name", count=1).hint == "did you mean 'len'"


def test_a_scope_without_names_still_gives_the_error():
    class Bare:
        def lookup(self, name):
            raise KeyError(name)

    assert fails("anything", "unknown-name", Bare()).hint is None


def test_the_scope_wins_over_a_built_in_name_read_as_a_value():
    assert run("len", len="mine") == "mine"


def test_a_called_built_in_is_always_the_built_in_whatever_the_scope_says():
    assert run("len(items)", len="mine", items=[1, 2]) == 2


@pytest.mark.parametrize("name", ["len", "sum", "sorted", "range", "isinstance", "clamp", "str"])
def test_a_built_in_function_is_not_a_value(name):
    error = fails(name, "function-as-value")
    assert f"'{name}' is a function" in error.message


def test_comprehension_names_do_not_leak():
    fails("[i for i in [1]] + [i]", "unknown-name")


def test_a_loop_variable_shadows_the_scope_inside_and_not_after():
    assert run("[x + 1 for x in items] + [x]", x=100, items=[1, 2]) == [2, 3, 100]


def test_the_first_iterable_sees_the_scope_and_later_ones_the_loop_variables():
    assert run("[x for x in x]", x=[7, 8]) == [7, 8]
    assert run("[y for x in xs for y in x]", xs=[[1], [2, 3]]) == [1, 2, 3]


def test_two_loops_with_the_same_variable_name_do_not_disturb_each_other():
    assert run("[[i for i in range(2)] + [i] for i in range(3)]") == [
        [0, 1, 0],
        [0, 1, 1],
        [0, 1, 2],
    ]


def test_an_exception_from_the_scope_other_than_key_error_is_the_hosts_and_propagates():
    class Broken:
        def lookup(self, name):
            raise RuntimeError("the host's own bug")

    with pytest.raises(RuntimeError, match="the host's own bug"):
        run("x", Broken())


def test_map_scope_copies_its_mapping_and_lists_names():
    source = {"a": 1}
    scope = MapScope(source)
    source["b"] = 2
    assert scope.names() == ["a"] and scope.lookup("a") == 1
    with pytest.raises(KeyError):
        scope.lookup("b")
    assert MapScope().names() == []


# -- arithmetic and comparison --------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, expected",
    [
        ("7 // 2", 3),
        ("-7 // 2", -4),
        ("-7 % 3", 2),
        ("7 / 2", 3.5),
        ("2 ** 10", 1024),
        ("2 ** -2", 0.25),
        ("4 ** 0.5", 2.0),
        ("True + 1", 2),
        ("[1] + [2]", [1, 2]),
        ("(1,) + (2,)", (1, 2)),
        ("'a' + 'b'", "ab"),
        ("'ab' * 3", "ababab"),
        ("2 * [1]", [1, 1]),
        ("'a' * 0", ""),
        ("'a' * -1", ""),
        ("-x", -3),
        ("+x", 3),
        ("-(-x)", 3),
        ("1 < x < 5", True),
        ("1 < x < 2", False),
        ("x == 3 == 3", True),
        ("'a' < 'b'", True),
        ("[1, 2] < [1, 3]", True),
        ("3 in {1, 3}", True),
        ("'k' in d", True),
        ("2 in range(3)", True),
        ("'ell' in 'hello'", True),
        ("3 not in items", True),
        ("n is None", True),
        ("x is not None", True),
        ("x == 'a'", False),
        ("1 == 1.0", True),
        ("0 or x", 3),
        ("x and 5", 5),
        ("[] or 'empty'", "empty"),
        ("None or 0", 0),
        ("not []", True),
        ("not 'a'", False),
        ("1 if x else 2", 1),
        ("1 if 0 else 2", 2),
    ],
)
def test_operators_give_python_values(source, expected):
    assert build(source).evaluate(reference_scope()) == expected


def test_boolean_operators_and_conditionals_do_not_evaluate_what_they_skip():
    assert run("x or 1 / 0", x=1) == 1
    assert run("x and 1 / 0", x=0) == 0
    assert run("1 if True else 1 / 0") == 1
    assert run("1 / 0 if False else 2") == 2


@pytest.mark.parametrize(
    "source, code",
    [
        ("1 / 0", "division-by-zero"),
        ("1 // 0", "division-by-zero"),
        ("1 % 0", "division-by-zero"),
        ("0 ** -1", "division-by-zero"),
        ("(10 ** 60) ** 60 / 3", "limit-int-bits"),
        ("1 + 'a'", "bad-operand"),
        ("'a' - 'b'", "bad-operand"),
        ("[1] + (2,)", "bad-operand"),
        ("(-8) ** 0.5", "bad-operand"),
        ("-'a'", "bad-operand"),
        ("None < 1", "bad-comparison"),
        ("'a' < 1", "bad-comparison"),
        ("1 in 5", "not-iterable"),
        ("1 not in None", "not-iterable"),
        ("'%s' % 1", "percent-format"),
    ],
)
def test_operators_give_errors_with_codes(source, code):
    fails(source, code)


def test_a_huge_integer_division_is_a_number_too_large_error():
    fails("big / 3", "number-too-large", big=10**1200)


def test_dates_decimals_and_enums_are_plain_values():
    class Mode(enum.Enum):
        A = 1

    scope = {
        "d": datetime.date(2026, 10, 26),
        "t": datetime.timedelta(days=2),
        "m": decimal.Decimal("1.5"),
        "e": Mode.A,
    }
    assert run("d + t", **scope) == datetime.date(2026, 10, 28)
    assert run("d < d + t", **scope) is True
    assert run("m * 2", **scope) == decimal.Decimal("3.0")
    assert run("e == e", **scope) is True
    assert run("f'{d}'", **scope) == "2026-10-26"


# -- the inert rule -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "trap + 1",
        "1 + trap",
        "trap == 1",
        "1 < trap",
        "1 in trap",
        "trap in [1]",
        "-trap",
        "trap[0]",
        "x[trap]",
        "f'{trap}'",
        "len(trap)",
        "str(trap)",
        "max(1, trap)",
        "name.replace(trap, 'x')",
        "name.join(trap)",
        "d.get(trap)",
        "{trap: 1}",
        "{trap}",
        "{trap for _ in [1]}",
        "{trap: 1 for _ in [1]}",
    ],
)
def test_an_object_that_is_not_plain_is_never_asked_to_do_anything(source):
    Trap.tripped.clear()
    with pytest.raises(TelError):
        build(source).evaluate(escape_scope())
    assert Trap.tripped == []


def test_the_truth_of_an_object_that_is_not_plain_is_true_without_asking_it():
    Trap.tripped.clear()
    scope = escape_scope()
    assert build("not trap").evaluate(scope) is False
    assert build("1 if trap else 2").evaluate(scope) == 1
    assert build("trap and 7").evaluate(scope) == 7
    assert build("trap or 7").evaluate(scope) is scope.values["trap"]
    assert Trap.tripped == []


def test_an_object_inside_a_plain_container_is_the_hosts_and_may_be_carried():
    Trap.tripped.clear()
    scope = escape_scope()
    assert build("len([trap, trap])").evaluate(scope) == 2
    assert build("{'a': trap}['a']").evaluate(scope) is scope.values["trap"]
    assert Trap.tripped == []


def test_the_message_names_the_kind_of_value_and_what_to_do():
    error = fails("trap + 1", "value-not-plain", trap=Trap())
    assert "Trap cannot be used in arithmetic" in error.message
    assert error.hint == "read one of its attributes instead"


# -- attributes -----------------------------------------------------------------------------------


def test_object_attributes_are_read_only_public_and_never_methods():
    assert run("o.title", o=Plain()) == "t"
    assert run("o.items[1]", o=Plain()) == 2
    fails("o.method", "attribute-is-method", o=Plain())
    error = fails("o.titel", "no-attribute", o=Plain())
    assert error.hint.startswith("did you mean 'title'")


def test_a_mapping_reads_by_attribute_and_names_a_missing_key():
    assert run("row.title", row={"title": "x"}) == "x"
    error = fails("row.titel", "no-key", row={"title": "x"})
    assert error.hint == "did you mean 'title'"
    assert run("row.a", row=types.MappingProxyType({"a": 1})) == 1


def test_a_dataclass_instance_reads_like_an_object():
    @dataclass
    class Row:
        title: str = "t"

    assert run("r.title", r=Row()) == "t"


def test_a_callable_stored_in_an_attribute_is_not_a_value():
    class Holder:
        def __init__(self):
            self.action = lambda: 1

    fails("h.action", "attribute-is-method", h=Holder())


def test_a_property_that_fails_is_an_error_that_does_not_repeat_its_message():
    class Holder:
        @property
        def broken(self):
            raise ValueError("secret-detail")

    error = fails("h.broken", "attribute-failed", h=Holder())
    assert "secret-detail" not in str(error) and "ValueError" in error.message


@pytest.mark.parametrize(
    "value",
    [types, int, len, Plain.method, (lambda: 1), (i for i in []), Plain.__init__.__code__],
    ids=["module", "class", "builtin", "method", "lambda", "generator", "code"],
)
def test_modules_classes_and_functions_have_no_attributes_to_read(value):
    fails("v.anything", "attribute-denied", v=value)
    fails("v[0]", "attribute-denied", v=value)
    fails("[i for i in v]", "not-iterable", v=value)


@pytest.mark.parametrize("source", ["x.real", "x.numerator", "name.upper", "items.count", "n.x"])
def test_a_plain_value_has_methods_and_no_attributes(source):
    with pytest.raises(TelError) as raised:
        build(source).evaluate(reference_scope())
    assert raised.value.code in {"no-attribute", "attribute-is-method"}


# -- indexing -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, expected",
    [
        ("items[0]", 10),
        ("items[-1]", 30),
        ("items[1:]", [20, 30]),
        ("items[::-1]", [30, 20, 10]),
        ("items[:2]", [10, 20]),
        ("items[a:b]", [20, 30]),
        ("name[1]", "d"),
        ("name[-1]", "a"),
        ("name[::2]", "aa"),
        ("d['k']", 1),
        ("(1, 2, 3)[1]", 2),
        ("[[1, 2], [3]][0][1]", 2),
    ],
)
def test_indexing_and_slicing(source, expected):
    assert run(source, **cases.SCOPE_VALUES, a=1, b=3) == expected


@pytest.mark.parametrize(
    "source",
    ["items[10]", "d['nope']", "name[1.5]", "d[[1]]", "x[0]", "items['a']", "items[::0]", "n[0]"],
)
def test_a_bad_index_is_an_error_that_names_the_kind_of_error_only(source):
    error = fails(source, "bad-index", **cases.SCOPE_VALUES)
    assert "nope" not in error.message


# -- calls: built-in functions --------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, expected",
    [
        ("sorted(items, reverse=True)", [30, 20, 10]),
        ("round(2.567, ndigits=2)", 2.57),
        ("round(2.5)", 2),
        ("sum(items, 10)", 70),
        ("max(items, default=0)", 30),
        ("max([], default=0)", 0),
        ("min(5, 2)", 2),
        ("abs(-2.5)", 2.5),
        ("int('7') + int(2.9)", 9),
        ("float('1.5')", 1.5),
        ("str(None)", "None"),
        ("str([1, 'a'])", "[1, 'a']"),
        ("bool([])", False),
        ("len('héllo')", 5),
        ("list('ab')", ["a", "b"]),
        ("list(d)", ["k"]),
        ("dict(d)", {"k": 1}),
        ("dict([('a', 1)])", {"a": 1}),
        ("tuple([1, 2])", (1, 2)),
        ("set([1, 1, 2]) == {1, 2}", True),
        ("list(reversed('abc'))", ["c", "b", "a"]),
        ("list(enumerate(items, 1))", [(1, 10), (2, 20), (3, 30)]),
        ("list(zip(items, 'ab'))", [(10, "a"), (20, "b")]),
        ("any([0, 0])", False),
        ("all([])", True),
        ("sum(x for x in items)", 60),
        ("list(range(1, 10, 3))", [1, 4, 7]),
        ("list(range(0))", []),
        ("clamp(-5, 0, 10)", 0),
        ("clamp(5, 0, 10)", 5),
        ("isinstance(True, int)", True),
        ("isinstance(1, float)", False),
        ("isinstance(d, dict)", True),
        ("isinstance(items, list)", True),
        ("isinstance(name, str)", True),
        ("isinstance(n, str)", False),
    ],
)
def test_built_in_functions(source, expected):
    assert build(source).evaluate(reference_scope()) == expected


@pytest.mark.parametrize(
    "source, code",
    [
        ("int('x')", "bad-call"),
        ("float('x')", "bad-call"),
        ("len(5)", "bad-call"),
        ("sum('a')", "bad-call"),
        ("min([])", "bad-call"),
        ("sorted([1, 'a'])", "bad-call"),
        ("abs('a')", "bad-call"),
        ("round('a')", "bad-call"),
        ("round(1.5, bogus=1)", "bad-call"),
        ("clamp(1, 'a', 3)", "bad-call"),
        ("range('a')", "bad-call"),
        ("range(3.5)", "bad-call"),
        ("range(1, 2, 0)", "bad-call"),
        ("range(True)", "bad-call"),
        ("range(1, 2, 3, 4)", "bad-call"),
        ("range(a=1)", "bad-call"),
        ("range(10 ** 30)", "limit-range"),
        ("int('9' * 5000)", "bad-call"),
    ],
)
def test_a_built_in_that_fails_is_an_error_with_the_functions_name(source, code):
    error = fails(source, code)
    assert error.code == code


def test_isinstance_uses_the_real_type_not_a_scope_name():
    assert run("isinstance(1, int)", int="shadowed") is True
    assert run("isinstance(x, str)", x=Trap()) is False


def test_isinstance_does_not_ask_an_object_for_its_class():
    class Liar:
        @property
        def __class__(self):
            raise AssertionError("asked")

    assert run("isinstance(x, str)", x=Liar()) is False


# -- calls: methods -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, expected",
    [
        ("name.upper()", "ADA"),
        ("'a,b'.split(',')", ["a", "b"]),
        ("'a b c'.split(None, 1)", ["a", "b c"]),
        ("'-'.join(['a', 'b'])", "a-b"),
        ("'-'.join(('a', 'b'))", "a-b"),
        ("''.join(['a', 'b'])", "ab"),
        ("'x'.center(5, '*')", "**x**"),
        ("'7'.zfill(3)", "007"),
        ("name.startswith(('a', 'b'))", True),
        ("name.replace('a', 'o')", "odo"),
        ("name.replace('a', 'o', 1)", "oda"),
        ("'  x '.strip()", "x"),
        ("'Hello'.removeprefix('He')", "llo"),
        ("name.find('d')", 1),
        ("name.count('a')", 2),
        ("'ß'.upper()", "SS"),
        ("d.get('k')", 1),
        ("d.get('zz', 0)", 0),
        ("d.keys()", ["k"]),
        ("d.values()", [1]),
        ("d.items()", [("k", 1)]),
        ("items.index(20)", 1),
        ("items.count(10)", 1),
        ("(1, 2, 1).count(1)", 2),
        ("types.get('a')", 1),
    ],
)
def test_methods(source, expected):
    scope = MapScope({**cases.SCOPE_VALUES, "types": types.MappingProxyType({"a": 1})})
    assert build(source).evaluate(scope) == expected


@pytest.mark.parametrize(
    "source, code",
    [
        ("x.upper()", "method-not-for-type"),
        ("n.get(1)", "method-not-for-type"),
        ("items.upper()", "method-not-for-type"),
        ("items.get(0)", "method-not-for-type"),
        ("name.index('a')", "method-not-for-type"),
        ("d.index(1)", "method-not-for-type"),
        ("name.get(1)", "method-not-for-type"),
        ("name.split(bogus=1)", "bad-call"),
        ("name.startswith(1)", "bad-call"),
        ("'-'.join([1, 2])", "bad-call"),
        ("d.get()", "bad-call"),
        ("name.replace('a')", "bad-call"),
    ],
)
def test_a_method_on_the_wrong_value_or_with_wrong_arguments(source, code):
    fails(source, code, **cases.SCOPE_VALUES)


def test_a_mapping_that_is_not_a_dict_has_the_dict_methods():
    scope = {"m": types.MappingProxyType({"a": 1, "b": 2})}
    assert run("m.keys()", **scope) == ["a", "b"]
    assert run("m.items()", **scope) == [("a", 1), ("b", 2)]


# -- comprehensions and displays ------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, expected",
    [
        ("[a + b for a, b in pairs]", [3, 7]),
        ("[a for a, _ in pairs]", [1, 3]),
        ("[(a, b) for (a, b) in pairs if a > 1]", [(3, 4)]),
        ("[x for x in 'abc']", ["a", "b", "c"]),
        ("[k for k in d]", ["k"]),
        ("[v for k, v in d.items()]", [1]),
        ("[i for i in range(5) if i % 2 if i > 1]", [3]),
        ("{x % 2 for x in items}", {0}),
        ("{x: x * 2 for x in [1, 2]}", {1: 2, 2: 4}),
        ("{k: len(v) for k, v in {'a': [1, 2]}.items()}", {"a": 2}),
        ("[[y for y in range(x)] for x in range(3)]", [[], [0], [0, 1]]),
        ("[x * k for x in items]", [30, 60, 90]),
        ("[0 for _ in range(3)]", [0, 0, 0]),
        ("sorted({3, 1, 2})", [1, 2, 3]),
        ("[x for x in {5}]", [5]),
        ("list(x for x in 'ab')", ["a", "b"]),
    ],
)
def test_comprehensions(source, expected):
    assert run(source, **cases.SCOPE_VALUES, pairs=[(1, 2), (3, 4)], k=3) == expected


def test_a_comprehension_does_not_change_the_scopes_values():
    items = [3, 1, 2]
    run("[i for i in sorted(items)]", items=items)
    assert items == [3, 1, 2]


@pytest.mark.parametrize(
    "source, code",
    [
        ("[a for a, b in [(1, 2, 3)]]", "bad-unpack"),
        ("[a for a, b in [1]]", "not-iterable"),
        ("[a for a in 5]", "not-iterable"),
        ("{[i] for i in [1]}", "bad-key"),
        ("{[i]: 1 for i in [1]}", "bad-key"),
        ("{1: 1, [2]: 3}", "bad-key"),
        ("{[1]}", "bad-key"),
        ("[*5]", "not-iterable"),
        ("max(*5)", "not-iterable"),
    ],
)
def test_comprehension_and_display_errors(source, code):
    fails(source, code)


def test_displays_build_new_containers_for_each_evaluation():
    expr = build("[1, 2]")
    first = expr.evaluate(MapScope())
    first.append(9)
    assert expr.evaluate(MapScope()) == [1, 2]
    expr = build("{'a': [1]}")
    expr.evaluate(MapScope())["a"].append(2)
    assert expr.evaluate(MapScope()) == {"a": [1]}


@pytest.mark.parametrize(
    "source, expected",
    [
        ("[*'ab', *range(2)]", ["a", "b", 0, 1]),
        ("(*[1], *(2,))", (1, 2)),
        ("{*[1, 1], 2}", {1, 2}),
        ("[*d]", ["k"]),
        ("max(*items)", 30),
        ("{1: 1, 1: 2}", {1: 2}),
        ("{}", {}),
        ("()", ()),
        ("[]", []),
    ],
)
def test_displays_and_spreading(source, expected):
    assert build(source).evaluate(reference_scope()) == expected


# -- text -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, expected",
    [
        ("f''", ""),
        ("f'{x}'", "3"),
        ("f'{{x}}'", "{x}"),
        ("f'{x!r}'", "3"),
        ("f'{name!r}'", "'ada'"),
        ("f'{name!s}'", "ada"),
        ("f'{\"é\"!a}'", "'\\xe9'"),
        ("f'{x:03d}'", "003"),
        ("f'{x:>5}'", "    3"),
        ("f'{2.5:.2f}'", "2.50"),
        ("f'{1234567:,}'", "1,234,567"),
        ("f'{x:{w}}'", "    3"),
        ("f'{n}'", "None"),
        ("f'{x + 1} and {name.upper()}'", "4 and ADA"),
        ("f'{[1, 2]}'", "[1, 2]"),
    ],
)
def test_f_strings(source, expected):
    assert run(source, **cases.SCOPE_VALUES, w=5) == expected


@pytest.mark.parametrize(
    "source, code",
    [
        ("f'{x:z}'", "bad-format"),
        ("f'{name:d}'", "bad-format"),
        ("f'{x:>99999999}'", "limit-string"),
        ("f'{x:.99999999f}'", "limit-string"),
        ("f'{x:{w}}'", "limit-string"),
    ],
)
def test_f_string_errors(source, code):
    fails(source, code, **cases.SCOPE_VALUES, w=10**9)


# -- positions ------------------------------------------------------------------------------------


def test_errors_name_the_file_line_and_column_of_the_text_in_the_yaml():
    expr = build("count + cnt", origin=Origin("Main_View.yaml", 14, 8))
    with pytest.raises(TelError) as raised:
        expr.evaluate(MapScope({"count": 1}))
    error = raised.value
    assert str(error).startswith("Main_View.yaml:14:16: ")  # expr.py: column 15, 0-based
    assert (error.line, error.column, error.end_column) == (14, 16, 19)
    assert "did you mean 'count'" in str(error)
    assert error.render().splitlines()[2].endswith("^^^")


def test_leading_whitespace_is_accounted_for_at_evaluation_too():
    error = None
    try:
        build("  nope", origin=Origin("A_View.yaml", 2, 11)).evaluate(MapScope())
    except TelError as raised:
        error = raised
    assert error is not None and (error.line, error.column) == (2, 13)


def test_an_error_inside_a_multi_line_expression_is_on_its_own_line():
    with pytest.raises(TelError) as raised:
        build("(1 +\n  oops)", origin=Origin("A_View.yaml", 5, 5)).evaluate(MapScope())
    assert (raised.value.line, raised.value.column) == (6, 3)


def test_the_position_of_a_failing_operation_is_the_operation():
    error = fails("1 + 'a'", "bad-operand")
    assert (error.line, error.column, error.end_column) == (1, 1, 8)


def test_the_position_after_a_non_ascii_character_is_in_characters():
    error = fails("'é' + 1", "bad-operand")
    assert (error.column, error.end_column) == (1, 8)
    error = fails("'é' + zz", "unknown-name")
    assert (error.column, error.end_column) == (7, 9)


def test_an_error_inside_a_comprehension_points_at_the_failing_part():
    error = fails("[a + 'x' for a in [1]]", "bad-operand")
    assert (error.column, error.end_column) == (2, 9)


def test_an_error_inside_a_call_argument_points_at_the_argument():
    error = fails("len(nope)", "unknown-name")
    assert (error.column, error.end_column) == (5, 9)


def _runtime_object(kind):
    import sys

    async def coroutine():
        return 1

    async def agen():
        yield 1

    if kind == "frame":
        return sys._getframe()
    if kind == "traceback":
        try:
            raise ValueError
        except ValueError as exc:
            return exc.__traceback__
    if kind == "coroutine":
        return coroutine()
    return {
        "async generator": agen,
        "method-wrapper": lambda: (1).__add__,
        "wrapper_descriptor": lambda: int.__add__,
        "method_descriptor": lambda: str.upper,
    }[kind]()


@pytest.mark.parametrize(
    "kind",
    [
        "frame",
        "traceback",
        "coroutine",
        "async generator",
        "method-wrapper",
        "wrapper_descriptor",
        "method_descriptor",
    ],
)
def test_every_kind_of_runtime_object_has_no_attributes_to_read(kind):
    value = _runtime_object(kind)
    try:
        fails("v.anything", "attribute-denied", v=value)
    finally:
        if kind == "coroutine":
            value.close()


def test_is_looks_at_identity_and_never_asks_the_value():
    Trap.tripped.clear()
    scope = escape_scope()
    assert build("trap is None").evaluate(scope) is False
    assert build("trap is not None").evaluate(scope) is True
    assert build("trap is not False").evaluate(scope) is True
    assert Trap.tripped == []


@pytest.mark.parametrize("source", ["items[trap]", "d[trap]", "name[trap]", "items[trap:]"])
def test_an_object_used_as_an_index_or_slice_bound_is_never_asked(source):
    Trap.tripped.clear()
    scope = MapScope({"items": [1, 2], "d": {"k": 1}, "name": "ada", "trap": Trap()})
    with pytest.raises(TelError):
        build(source).evaluate(scope)
    assert Trap.tripped == []


# -- the operators that are compiled specially when one side is a number written in the text ------


@pytest.mark.parametrize(
    "source, expected",
    [
        ("x + 1", 4),
        ("x - 1", 2),
        ("x * 2", 6),
        ("x + 1.5", 4.5),
        ("f + 1", 3.5),
        ("f * 2", 5.0),
        ("x < 5", True),
        ("x > 5", False),
        ("x == 3", True),
        ("x != 3", False),
        ("x <= 3.0", True),
        ("f >= 2", True),
        ("name == 'ada'", True),
        ("name < 'b'", True),
        ("name != 'ada'", False),
        ("True + 1", 2),
        ("b + 1", 2),
        ("b < 2", True),
        ("x / 2", 1.5),
        ("x // 2", 1),
        ("x % 2", 1),
        ("x ** 2", 9),
    ],
)
def test_an_operator_with_a_number_in_the_text_gives_the_same_values(source, expected):
    assert run(source, x=3, f=2.5, b=True, name="ada") == expected


@pytest.mark.parametrize(
    "source, scope, code",
    [
        ("x + 1", {"x": "a"}, "bad-operand"),
        ("x * 2", {"x": None}, "bad-operand"),
        ("x - 1", {"x": [1]}, "bad-operand"),
        ("x < 5", {"x": "a"}, "bad-comparison"),
        ("x == 5", {"x": "a"}, None),
        ("x >= 1", {"x": None}, "bad-comparison"),
        ("name < 'b'", {"name": 3}, "bad-comparison"),
        ("x + 1", {"x": Trap()}, "value-not-plain"),
        ("x < 1", {"x": Trap()}, "value-not-plain"),
        ("x * 2", {"x": 2**99}, "limit-int-bits"),
        ("x + 1", {"x": 2**99 * 2 - 1}, "limit-int-bits"),
        ("x * 2.0", {"x": "ab"}, "bad-operand"),
    ],
)
def test_the_special_forms_keep_every_check(source, scope, code):
    limits = Limits(max_int_bits=100)
    expr = build(source, limits=limits)
    if code is None:
        assert expr.evaluate(MapScope(scope)) is False
        return
    with pytest.raises(TelError) as raised:
        expr.evaluate(MapScope(scope))
    assert raised.value.code == code


def test_a_repeated_sequence_by_a_number_in_the_text_is_still_size_checked():
    fails("s * 2000000", "limit-sequence", s="ab")
    assert run("s * 2", s="ab") == "abab"
    assert run("l * 2", l=[1]) == [1, 1]


def test_a_compiled_expression_keeps_no_syntax_tree():
    import ast

    def reaches_a_tree(value, seen):
        if id(value) in seen:
            return False
        seen.add(id(value))
        if isinstance(value, ast.AST):
            return True
        if isinstance(value, (tuple, list, set, frozenset)):
            return any(reaches_a_tree(v, seen) for v in value)
        if isinstance(value, dict):
            return any(reaches_a_tree(v, seen) for v in value.values())
        if isinstance(value, types.FunctionType):
            parts = [*(value.__defaults__ or ())]
            parts += [cell.cell_contents for cell in value.__closure__ or ()]
            return any(reaches_a_tree(v, seen) for v in parts)
        return False

    sources = [
        "count + 1",
        "[w.name for w in workspaces if w.active]",
        "{k: v for k, v in d.items()}",
        "f'{battery}% {state}'",
        "max(1, 2) if flag else sum(items)",
        "name.upper() + str(count)",
    ]
    for source in sources:
        assert not reaches_a_tree(build(source)._fn, set()), source
