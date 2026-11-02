"""The canonical form (step 6 phase 3): two spellings of one expression, one text (P5)."""

import gc
import inspect
import random
import sys
import tracemalloc

import pytest

import tel
from tel import Limits, MapScope, TelLimitError


def build(text, **kw):
    return tel.compile_expression(text, language="0.1", **kw)


def canon(text):
    return build(text).canonical


def tcanon(text):
    return tel.compile_template(text, language="0.1").canonical


# -- what spellings agree -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("a<20", "a < 20"),
        ("  a  <  20  ", "a < 20"),
        ("(a)+(b)", "a + b"),
        ("((a + b))", "a + b"),
        ("(a + b) * c", "((a + b)) * (c)"),
        ('"x"', "'x'"),
        ('["a", "b"]', "['a', 'b']"),
        ("f'{a}'", 'f"{a}"'),
        ("c ? a : b", "a if c else b"),
        ("c?a:b", "(a) if (c) else (b)"),
        ("a ? b : c ? d : e", "b if a else (d if c else e)"),
        ("[x for x in xs if x>1]", "[x  for  x  in  xs  if  x > 1]"),
        ("{'k':1,'j':2}", "{ 'k' : 1 , 'j' : 2 }"),
        ("x[1:2]", "x[ 1 : 2 ]"),
        ("not a", "not(a)"),
        ("a and b or c", "(a and b) or c"),
        ("1_000", "1000"),
        ("0x10", "16"),
        ("1.50", "1.5"),
        ("a#comment", "a"),
        ("a  # c\n", "a"),
        ("(a,\n b)", "(a, b)"),
        ("max(\n a,\n b )", "max(a, b)"),
    ],
)
def test_two_spellings_of_one_expression_have_one_canonical_text(a, b):
    assert canon(a) == canon(b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("a < 20", "a <= 20"),
        ("a + b", "b + a"),
        ("a - (b - c)", "a - b - c"),
        ("(a + b) * c", "a + b * c"),
        ("'x'", "x"),
        ("1", "1.0"),
        ("[1, 2]", "(1, 2)"),
        ("a and b", "a or b"),
        ("a if c else b", "b if c else a"),
        ("x[1]", "x[2]"),
        ("a.b", "a.c"),
        ("len(a)", "len(b)"),
        ("'a' 'b'", "'a' + 'b'"),
    ],
)
def test_different_expressions_have_different_canonical_text(a, b):
    assert canon(a) != canon(b)


def test_the_canonical_text_is_a_fixed_point_and_compiles_to_the_same_value():
    scope = MapScope({"a": 3, "b": 4, "xs": [1, 2, 3], "c": True})
    for text in (
        "a<b and not c",
        "c ? a : b",
        "[x*2 for x in xs if x>1]",
        "{'k':[a,b]}",
        "f'{a:>5}' + 'z'",
        "(a+b)*(a-b)",
        "xs[1:]",
        "a if c else b",
    ):
        once = build(text)
        again = build(once.canonical)
        assert again.canonical == once.canonical
        assert again.evaluate(scope) == once.evaluate(scope)


def test_it_reads_the_same_for_random_spacings_and_brackets():
    rng = random.Random(5)
    atoms = ["a", "b", "1", "2.5", "'s'", "xs[0]", "d.k", "max(a, 1)"]
    ops = ["+", "-", "*", "<", "and", "or", "if c else"]
    for _ in range(300):
        parts = [rng.choice(atoms)]
        for _ in range(rng.randint(0, 4)):
            parts += [rng.choice(ops), rng.choice(atoms)]
        tight = " ".join(parts)
        loose = "  ".join(p if rng.random() < 0.5 else f"({p})" for p in parts)
        try:
            one = canon(tight)
        except tel.TelError:
            continue  # a combination the language refuses (for example `if` with no `else`)
        try:
            assert canon(loose) == one, (tight, loose)
        except tel.TelError:
            continue


# -- filled text and the question-mark spelling (P5) ----------------------------------------------


def test_a_filled_expression_and_the_same_text_written_by_hand_agree():
    filled = tel.fill("battery < $limit or name in $names", {"limit": 20, "names": ["a", "b"]})
    by_hand = "battery<20 or name in ['a',  'b']"
    assert canon(filled) == canon(by_hand) == "battery < 20 or name in ['a', 'b']"


def test_a_filled_negative_number_agrees_with_the_hand_written_one():
    assert canon(tel.fill("$x ** 2", {"x": -5})) == canon("(-5) ** 2") == "(-5) ** 2"
    assert canon(tel.fill("$x + 1", {"x": -5})) == canon("-5 + 1")


def test_a_filled_string_agrees_whatever_quotes_it_was_written_with():
    assert canon(tel.fill("$s", {"s": "it's"})) == canon('"it\'s"')
    assert canon(tel.fill("$s", {"s": 'say "hi"'})) == canon("'say \"hi\"'")


def test_a_filled_template_and_the_hand_written_one_agree():
    filled = tel.fill_template("Battery {{ battery * $k }}% {{ $g }}", {"k": 2, "g": "hi"})
    assert tcanon(filled) == tcanon("Battery {{battery*2}}% {{ 'hi' }}")


def test_the_condition_and_the_repeater_pieces_agree_too():
    a = tel.compile_condition(tel.fill("battery < $n", {"n": 20}), language="0.1")
    b = tel.compile_condition("battery<20", language="0.1")
    assert a.expression.canonical == b.expression.canonical


# -- templates ------------------------------------------------------------------------------------


def test_a_template_is_its_literal_text_and_its_parts_in_canonical_form():
    assert tcanon("Hi {{name}}, {{ n+1 }} new") == "Hi {{ name }}, {{ n + 1 }} new"
    assert tcanon("{{a}}{{b}}") == "{{ a }}{{ b }}"
    assert tcanon("plain $5 text") == "plain $5 text"
    assert tcanon("") == ""
    assert tcanon("{{ c ? a : b }}") == tcanon("{{a if c else b}}")


def test_the_literal_text_between_parts_is_kept_exactly():
    assert tcanon("  a  {{x}}  b  ") == "  a  {{ x }}  b  "
    assert tcanon("a } b { c }} d") == "a } b { c }} d"
    assert tcanon("é\n{{x}}\n") == "é\n{{ x }}\n"


def test_a_template_whose_part_holds_braces_or_strings_with_braces_reads_back_the_same():
    for text in ("{{ {'a': {'b': 1}} }}", "{{ 'a}}b' }}", "x {{ ['}}', 1] }} y", "{{ f'{a}' }}"):
        first = tel.compile_template(text, language="0.1")
        again = tel.compile_template(first.canonical, language="0.1")
        assert again.canonical == first.canonical


def test_a_template_with_a_part_is_not_text_whatever_the_canonical_form_says():
    t = tel.compile_template("{{ x }}", language="0.1")
    assert not t.is_text and t.canonical == "{{ x }}"


# -- what it does not do --------------------------------------------------------------------------


def test_there_is_no_equality_between_expressions():
    a, b = build("a"), build("a")
    assert a != b and a == a
    assert hash(a) == hash(a)


def test_the_canonical_form_needs_no_registry_so_a_host_function_is_just_a_call():
    one = build("double(n)", functions={"double": lambda n: n * 2})
    two = build("double( n )", functions={"double": lambda n: n * 3})
    assert one.canonical == two.canonical == "double(n)"  # the registry is not part of it


def test_a_deep_expression_is_a_depth_error_not_a_stack_overflow():
    big = Limits(max_source=10_000, max_depth=10_000, max_nodes=10_000)
    expr = build("-" * 30 + "1", limits=big)
    old = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(len(inspect.stack()) + 25)
        with pytest.raises(TelLimitError) as raised:
            _ = expr.canonical
    finally:
        sys.setrecursionlimit(old)
    assert raised.value.code == "limit-depth"


# -- the cost -------------------------------------------------------------------------------------


def bytes_per_compiled(text, copies=3000):
    build(text)
    gc.collect()
    tracemalloc.start()
    keep = [build(text) for _ in range(copies)]
    size = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()
    del keep
    return size / copies


def test_asking_for_the_canonical_form_keeps_nothing_on_the_expression():
    expr = build("a < 20")
    before = (expr.__slots__ if hasattr(expr, "__slots__") else None, sys.getsizeof(expr))
    for _ in range(3):
        _ = expr.canonical
    assert (expr.__slots__, sys.getsizeof(expr)) == before
    assert not hasattr(expr, "__dict__")
    with pytest.raises(AttributeError):
        expr.canonical = "x"  # type: ignore[misc]  # a read-only property
    # the bytes kept per compiled expression do not depend on the property being there
    assert 400 < bytes_per_compiled("a < 20") < 2500
