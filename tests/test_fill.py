"""TEL's Python form (step 6 phase 2): `literal`, `fill` and `fill_template`."""

import ast
import datetime
import decimal
import enum
import random
import time

import pytest

import tel
from tel import Limits, MapScope, TelLimitError, TelSyntaxError

CEILING = 0.5  # seconds: same meaning as in test_evaluator_limits


def value_of(text):
    return tel.compile_expression(text, language="0.1").evaluate(MapScope({}))


def same(a, b):
    """Equal, and equal in type all the way down (`1`, `1.0` and `True` are all `==`)."""
    if type(a) is not type(b):
        return False
    if isinstance(a, list | tuple):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict):
        return list(a) == list(b) and all(same(a[k], b[k]) for k in a)
    if isinstance(a, float):
        return a == b and str(a) == str(b)  # tells -0.0 from 0.0
    return a == b


# -- literal: what a value is written as ----------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, "None"),
        (True, "True"),
        (False, "False"),
        (0, "0"),
        (7, "7"),
        (-5, "(-5)"),  # a negative number on its own is in brackets
        (2.5, "2.5"),
        (-0.0, "(-0.0)"),
        (1e100, "1e+100"),
        ("a'b\"c", "'a\\'b\"c'"),
        ("", "''"),
        ([], "[]"),
        ((), "()"),
        ({}, "{}"),
        ((1,), "(1,)"),
        ((1, 2), "(1, 2)"),
        ([-1, [2]], "[-1, [2]]"),  # inside a container a minus needs no brackets
        ({"a": 1, 2: (3,)}, "{'a': 1, 2: (3,)}"),
    ],
)
def test_a_value_is_written_as_its_python_literal(value, text):
    assert tel.literal(value) == text
    assert value_of(text) == value  # TEL reads it back as the value


def test_a_negative_number_in_brackets_keeps_its_meaning_in_a_power():
    assert tel.fill("$x ** 2", {"x": -5}) == "(-5) ** 2"
    assert value_of(tel.fill("$x ** 2", {"x": -5})) == 25
    assert value_of(tel.fill("-$x", {"x": -5})) == 5
    assert value_of(tel.fill("$x * 2", {"x": -2.5})) == -5.0


def test_what_is_written_reads_back_to_the_same_value_for_random_values():
    rng = random.Random(7)

    def make(depth):
        kind = rng.randrange(9 if depth < 3 else 6)
        if kind == 0:
            return None
        if kind == 1:
            return rng.choice([True, False])
        if kind == 2:
            return rng.randint(-(10**12), 10**12)
        if kind == 3:
            return rng.choice([0.0, -0.0, 1.5, -2.25, 1e-7, 1e22, 123456789.125])
        if kind == 4:
            return "".join(rng.choice("ab '\"\\\n\t$#{}é😀\x00") for _ in range(rng.randint(0, 8)))
        if kind == 5:
            return rng.randint(0, 5)
        if kind == 6:
            return [make(depth + 1) for _ in range(rng.randint(0, 3))]
        if kind == 7:
            return tuple(make(depth + 1) for _ in range(rng.randint(0, 3)))
        keys = ["k", "j", 1, 2, "é"]
        return {rng.choice(keys): make(depth + 1) for _ in range(rng.randint(0, 3))}

    for _ in range(500):
        value = make(0)
        text = tel.literal(value)
        assert same(ast.literal_eval(text), value), (value, text)
        assert same(value_of(text), value), (value, text)


@pytest.mark.parametrize(
    "value",
    [{1}, frozenset(), datetime.date(2026, 1, 1), decimal.Decimal(1), b"x", 1j, len, object()],
)
def test_a_value_that_is_not_literal_data_is_a_type_error_naming_its_type(value):
    with pytest.raises(TypeError, match=type(value).__name__):
        tel.literal(value)


def test_an_enum_is_refused_but_an_int_enum_is_its_number():
    class Colour(enum.Enum):
        RED = 1

    class Level(enum.IntEnum):
        LOW = 3

    with pytest.raises(TypeError, match="Colour"):
        tel.literal(Colour.RED)
    assert tel.literal(Level.LOW) == "3"


def test_the_message_names_where_the_bad_value_is():
    with pytest.raises(TypeError) as raised:
        tel.fill("$names", {"names": ["a", "b", {1}]})
    assert "values['names'][2]" in str(raised.value)
    with pytest.raises(TypeError) as raised:
        tel.fill("$d", {"d": {"k": [1, {"z": object()}]}})
    assert "values['d']['k'][1]['z']" in str(raised.value)
    with pytest.raises(TypeError) as raised:
        tel.literal([1, object()])
    assert "value[1]" in str(raised.value)


@pytest.mark.parametrize("key", [1.5, None, (1,), True, b"k"])
def test_a_dict_key_must_be_a_str_or_an_int(key):
    with pytest.raises(TypeError, match="dict key"):
        tel.literal({key: 1})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), [float("nan")]])
def test_nan_and_inf_have_no_literal(value):
    with pytest.raises(ValueError, match="nan and inf"):
        tel.literal(value)


def test_a_subclass_is_written_as_the_plain_type_without_running_its_methods():
    def boom(*_):
        raise RuntimeError("host code ran")

    class Int(int):
        __repr__ = __str__ = __hash__ = bit_length = boom

    class Str(str):
        __repr__ = __str__ = __len__ = boom

    class Key(str):
        __repr__ = __str__ = __len__ = boom  # it must still hash to be a dict key

    class Float(float):
        __repr__ = __str__ = __hash__ = boom

    class List(list):
        __iter__ = __len__ = __repr__ = boom

    class Tuple(tuple):
        __iter__ = __len__ = __repr__ = boom

    class Dict(dict):
        items = keys = __iter__ = __len__ = __repr__ = boom

    assert tel.literal(Int(-4)) == "(-4)"
    assert tel.literal(Str("a")) == "'a'"
    assert tel.literal(Float(1.5)) == "1.5"
    assert tel.literal(List([1, 2])) == "[1, 2]"
    assert tel.literal(Tuple((1,))) == "(1,)"
    assert tel.literal(Dict({Key("k"): Int(2)})) == "{'k': 2}"


# -- literal: limits ------------------------------------------------------------------------------


def test_a_value_over_the_source_limit_is_a_limit_error_before_it_is_built():
    with pytest.raises(TelLimitError) as raised:
        tel.literal("x" * 3000)
    assert raised.value.code == "limit-source"
    with pytest.raises(TelLimitError) as raised:
        tel.literal(list(range(1000)))
    assert raised.value.code == "limit-source"
    assert len(tel.literal("x" * 1990)) == 1992  # just under the default 2,000
    with pytest.raises(TelLimitError):
        tel.literal("x" * 1999)  # the quotes make 2,001


def test_the_limit_is_on_the_text_so_a_huge_container_is_refused_in_reasonable_time():
    start = time.perf_counter()
    with pytest.raises(TelLimitError):
        tel.literal(list(range(10**6)), limits=Limits(max_source=10_000))
    assert time.perf_counter() - start < CEILING


def test_a_value_nested_too_deep_is_a_limit_error_not_a_stack_overflow():
    deep = []
    for _ in range(100):
        deep = [deep]
    with pytest.raises(TelLimitError) as raised:
        tel.literal(deep)
    assert raised.value.code == "limit-depth"
    ok = []
    for _ in range(39):
        ok = [ok]
    assert tel.literal(ok) == "[" * 40 + "]" * 40
    loop: list = []
    loop.append(loop)
    with pytest.raises(TelLimitError) as raised:
        tel.literal(loop)
    assert raised.value.code == "limit-depth"


def test_a_self_containing_value_with_the_limits_raised_is_still_a_depth_error():
    loop: list = []
    loop.append(loop)
    big = Limits(max_depth=10**6, max_source=10**9)
    with pytest.raises(TelLimitError) as raised:
        tel.literal(loop, limits=big)
    assert raised.value.code == "limit-depth"
    mapping: dict = {}
    mapping["k"] = mapping
    with pytest.raises(TelLimitError):
        tel.literal(mapping, limits=big)


def test_a_number_over_the_bits_limit_is_a_limit_error_and_not_a_conversion_error():
    with pytest.raises(TelLimitError) as raised:
        tel.literal(2**5000, limits=Limits(max_int_bits=4096, max_source=10**6))
    assert raised.value.code == "limit-int-bits"
    assert tel.literal(2**4000, limits=Limits(max_source=10**6)).startswith("1")


# -- fill: placeholders ---------------------------------------------------------------------------


def test_a_placeholder_is_replaced_by_the_literal_of_its_value():
    text = tel.fill("battery < $limit or name in $names", {"limit": 20, "names": ["a", "b"]})
    assert text == "battery < 20 or name in ['a', 'b']"
    expr = tel.compile_expression(text, language="0.1")
    assert expr.evaluate(MapScope({"battery": 5, "name": "z"})) is True


def test_a_placeholder_may_be_used_twice_and_longest_name_wins():
    assert tel.fill("$a + $a + $ab", {"a": 1, "ab": 2}) == "1 + 1 + 2"
    assert tel.fill("$a_b1", {"a_b1": 3}) == "3"
    assert tel.fill("[$x,$x]", {"x": 0}) == "[0,0]"


@pytest.mark.parametrize(
    "text",
    [
        "'cost $x'",
        '"cost $x"',
        "'''a $x\nb $x'''",
        '"""$x"""',
        "f'{a} $x'",
        "f'{$x}'",  # not valid TEL, but `$` in an f-string is left alone
        'f"{d["k"]}"',
        "r'$x'",
        "b'$x'",
        "'a' + '$x'",
        "1  # $x",
        "'it\\'s $x'",
    ],
)
def test_a_dollar_inside_a_string_or_a_comment_is_left_alone(text):
    assert tel.fill(text, {}) == text


def test_a_placeholder_after_a_string_or_a_comment_line_is_still_found():
    assert tel.fill("'$x' + $x", {"x": 1}) == "'$x' + 1"
    assert tel.fill("# $x\n$x", {"x": 1}) == "# $x\n1"
    assert tel.fill("f'{a}' + $x", {"x": 1}) == "f'{a}' + 1"
    assert tel.fill("'a' # it's\n$x", {"x": 1}) == "'a' # it's\n1"


def test_a_value_is_never_scanned_for_placeholders_again():
    assert tel.fill("$a", {"a": "$b"}) == "'$b'"
    assert tel.fill("$a + $b", {"a": "$b", "b": 1}) == "'$b' + 1"
    assert tel.fill("$a", {"a": ["$a", {"$a": "$a"}]}) == "['$a', {'$a': '$a'}]"


def test_a_text_value_goes_in_as_a_string_never_as_code():
    for nasty in ("'); __import__('os'); ('", "1) + (2", "x' + y + '", "\n__import__('os')"):
        assert value_of(tel.fill("$v", {"v": nasty})) == nasty  # a string, not code
        assert value_of(tel.fill("[$v, $v]", {"v": nasty})) == [nasty, nasty]
        assert value_of(tel.fill("{$v: 1}", {"v": nasty})) == {nasty: 1}


def test_text_with_no_placeholder_comes_back_unchanged():
    for text in ("a + b", "", "  x  ", "'a' # c"):
        assert tel.fill(text, {}) == text


# -- fill: mistakes -------------------------------------------------------------------------------


def test_a_placeholder_with_no_value_is_a_value_error_naming_it():
    with pytest.raises(ValueError, match=r"\$b"):
        tel.fill("$a + $b", {"a": 1})
    with pytest.raises(ValueError, match=r"\$a, \$b"):
        tel.fill("$a + $b + $a", {})


def test_a_value_with_no_placeholder_is_a_value_error_naming_it():
    with pytest.raises(ValueError, match="'limt'"):
        tel.fill("battery < $limit", {"limit": 1, "limt": 2})
    with pytest.raises(ValueError, match="'x'"):
        tel.fill("'$x'", {"x": 1})  # a `$` in a string is not a placeholder


@pytest.mark.parametrize("text", ["a $ b", "$", "$1", "$$x", "a$", "$-x"])
def test_a_dollar_with_no_name_is_a_value_error(text):
    with pytest.raises(ValueError, match="not followed by a name"):
        tel.fill(text, {"x": 1})


@pytest.mark.parametrize("name", ["a-b", "1a", "", " a", "a b", 3, None, ("a",)])
def test_a_name_that_is_not_a_plain_identifier_is_a_value_error(name):
    with pytest.raises(ValueError, match="placeholder name"):
        tel.fill("1", {name: 1})


def test_the_arguments_are_checked():
    with pytest.raises(TypeError, match="str"):
        tel.fill(5, {})
    with pytest.raises(TypeError, match="mapping"):
        tel.fill("1", [("a", 1)])
    with pytest.raises(TypeError, match="mapping"):
        tel.fill("1", None)
    with pytest.raises(TypeError, match="Limits"):
        tel.fill("1", {}, limits=5)
    with pytest.raises(TypeError):
        tel.fill("1", {}, Limits())  # limits is a keyword


def test_a_mapping_that_is_not_a_dict_is_accepted():
    from types import MappingProxyType

    assert tel.fill("$a", MappingProxyType({"a": 1})) == "1"


def test_a_str_subclass_text_is_read_as_plain_text():
    class Text(str):
        def __str__(self):
            raise RuntimeError("host code ran")

    assert tel.fill(Text("$a"), {"a": 1}) == "1"


# -- fill: size -----------------------------------------------------------------------------------


def test_the_result_is_checked_against_the_source_limit_as_it_grows():
    with pytest.raises(TelLimitError) as raised:
        tel.fill("$a + $a", {"a": "x" * 1500})
    assert raised.value.code == "limit-source"
    assert len(tel.fill("$a", {"a": "x" * 1990})) == 1992


def test_a_text_with_a_huge_number_of_placeholders_is_refused_in_reasonable_time():
    start = time.perf_counter()
    with pytest.raises(TelLimitError):
        tel.fill("$a + " * 400_000, {"a": 1}, limits=Limits(max_source=10_000))
    assert time.perf_counter() - start < CEILING


def test_the_limits_given_are_the_ones_used():
    assert tel.fill("$a", {"a": "x" * 5000}, limits=Limits(max_source=6000)).startswith("'x")
    with pytest.raises(TelLimitError):
        tel.fill("$a", {"a": [[1]]}, limits=Limits(max_depth=1))


# -- positions (6H) -------------------------------------------------------------------------------


def test_errors_after_filling_point_into_the_filled_text():
    text = tel.fill("1 + $x + )", {"x": 1234})
    assert text == "1 + 1234 + )"
    with pytest.raises(TelSyntaxError) as raised:
        tel.compile_expression(text, language="0.1")
    assert (raised.value.line, raised.value.column) == (1, 12)  # the `)` in the filled text
    with pytest.raises(tel.TelError) as raised:
        tel.compile_expression(tel.fill("$x / 0", {"x": 1234}), language="0.1").evaluate(
            MapScope({})
        )
    assert raised.value.column == 1


# -- it works with every entry point --------------------------------------------------------------


def test_filled_text_goes_to_every_entry_point():
    scope = MapScope({"battery": 10, "ws": [{"id": 1}, {"id": 2}]})
    cond = tel.compile_condition(tel.fill("battery < $n", {"n": 20}), language="0.1")
    assert cond.holds(scope) is True
    rep = tel.compile_repeater(
        "w in ws", key=tel.fill("w.id + $off", {"off": 100}), name="W", language="0.1"
    )
    assert [i.key for i in rep.items(scope)] == [101, 102]
    t = tel.compile_template(
        tel.fill_template("Battery {{ battery * $k }}%", {"k": 2}), language="0.1"
    )
    assert t.evaluate(scope) == "Battery 20%"


def test_a_filled_expression_is_the_same_expression_as_the_hand_written_one():
    rng = random.Random(11)
    for _ in range(200):
        a, b = rng.randint(-50, 50), rng.choice(["x", "it's", "a b", ""])
        filled = tel.fill("[$a, $b, $a * 2 - 1, {$b: $a}]", {"a": a, "b": b})
        by_hand = f"[{a!r}, {b!r}, {a!r} * 2 - 1, {{{b!r}: {a!r}}}]"
        assert value_of(filled) == value_of(by_hand) == [a, b, a * 2 - 1, {b: a}]


# -- fill_template --------------------------------------------------------------------------------


def test_a_template_part_is_filled_and_the_text_between_parts_is_not_touched():
    out = tel.fill_template("cost $5, {{ $n + 1 }} left, '$x' {{ 'a$b' }} #$y", {"n": 4})
    assert out == "cost $5, {{ 4 + 1 }} left, '$x' {{ 'a$b' }} #$y"
    t = tel.compile_template(out, language="0.1")
    assert t.evaluate(MapScope({})) == "cost $5, 5 left, '$x' a$b #$y"


def test_a_value_that_holds_template_syntax_is_only_text_in_a_part():
    out = tel.fill_template("{{ $g }}, {{ user }}!", {"g": "Hello {{ }} }}"})
    t = tel.compile_template(out, language="0.1")
    assert t.evaluate(MapScope({"user": "u"})) == "Hello {{ }} }}, u!"


def test_a_part_with_braces_inside_is_found_even_when_it_has_a_placeholder():
    out = tel.fill_template("a {{ {'k': {'j': $x}} }} b {{ [$x] }}", {"x": 7})
    assert out == "a {{ {'k': {'j': 7}} }} b {{ [7] }}"
    assert (
        tel.compile_template(out, language="0.1").evaluate(MapScope({}))
        == "a {'k': {'j': 7}} b [7]"
    )


def test_filling_a_template_with_no_placeholder_changes_nothing():
    rng = random.Random(3)
    pieces = [
        "a",
        " ",
        "{{ x }}",
        "{{x+1}}",
        "}",
        "{",
        "{{ {'a': {'b': 1}} }}",
        "$",
        "é",
        "{{ 'a}}b' }}",
    ]
    for _ in range(300):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 6)))
        try:
            out = tel.fill_template(text, {})
        except TelSyntaxError:
            continue  # an unclosed or empty part: the template reader's own error
        assert out == text


def test_a_template_with_a_part_that_is_never_closed_is_the_templates_own_error():
    with pytest.raises(TelSyntaxError) as raised:
        tel.fill_template("a {{ $x", {"x": 1})
    assert raised.value.code == "template-unclosed"
    with pytest.raises(TelSyntaxError) as raised:
        tel.fill_template("{{   }}", {})
    assert raised.value.code == "template-empty"


def test_a_placeholder_outside_every_part_is_not_a_placeholder_for_a_template():
    with pytest.raises(ValueError, match="'x'"):
        tel.fill_template("cost $x", {"x": 1})
    with pytest.raises(ValueError, match=r"\$y"):
        tel.fill_template("{{ $x + $y }}", {"x": 1})
    with pytest.raises(ValueError, match="not followed by a name"):
        tel.fill_template("{{ $ }}", {})


def test_a_template_is_checked_against_the_source_limit_too():
    with pytest.raises(TelLimitError) as raised:
        tel.fill_template("{{ $a }}{{ $a }}", {"a": "x" * 1200})
    assert raised.value.code == "limit-source"
    start = time.perf_counter()
    with pytest.raises(TelLimitError):
        tel.fill_template("{{ $a }}" * 100_000, {"a": 1}, limits=Limits(max_source=10_000))
    assert time.perf_counter() - start < CEILING
