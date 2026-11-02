"""TEL's Python form against text (step 6 phase 5, the vault's P5).

`tree_from_text` and `tree_from_python` are a stand-in for the Shell's tree builder: the same small
shell is written once as the text a TDL file holds, and once from Python values through `fill` and
`fill_template`. The two must have the same canonical texts and the same results.
"""

import random

import pytest

import tel
from tel import MapScope, Origin, RepeaterState, TelError

LANG = "0.1"
LIMIT, NAMES = 20, ["a", "b"]


def tree_from_text():
    return {
        "if": "battery<20",
        "label": "Battery {{battery}}%",
        "for": ("w", "workspaces", "w.id"),
        "style": "{{ battery < 20 ? 'red' : 'ok' }}",
        "in": "name in ['a',  'b']",
    }


def tree_from_python():
    return {
        "if": tel.fill("battery < $limit", {"limit": LIMIT}),
        "label": "Battery {{ battery }}" + "%",
        "for": ("w", "workspaces", "w.id"),
        "style": tel.fill_template(
            "{{ battery < $limit ? $red : $ok }}", {"limit": LIMIT, "red": "red", "ok": "ok"}
        ),
        "in": tel.fill("name in $names", {"names": NAMES}),
    }


def repeater(tree):
    names, items, key = tree["for"]
    return tel.compile_repeater_parts(names, items, key=key, name="W", language=LANG)


def compiled(tree):
    return {
        "if": tel.compile_condition(tree["if"], language=LANG).expression.canonical,
        "label": tel.compile_template(tree["label"], language=LANG).canonical,
        "style": tel.compile_template(tree["style"], language=LANG).canonical,
        "in": tel.compile_expression(tree["in"], language=LANG).canonical,
        "for": repeater(tree).header,
    }


def test_the_tree_built_from_python_has_the_same_canonical_texts_as_the_text_tree():
    assert compiled(tree_from_python()) == compiled(tree_from_text())


def run(tree, scope):
    cond = tel.compile_condition(tree["if"], language=LANG)
    label = tel.compile_template(tree["label"], language=LANG)
    style = tel.compile_template(tree["style"], language=LANG)
    found = tel.compile_expression(tree["in"], language=LANG)
    entries = repeater(tree).reconcile(scope, RepeaterState()).entries
    return (
        cond.holds(scope),
        label.evaluate(scope),
        style.evaluate(scope),
        found.evaluate(scope),
        [(e.key, e.name) for e in entries],
    )


def test_both_trees_give_the_same_results_for_the_same_scope():
    scope = MapScope({"battery": 7, "name": "b", "workspaces": [{"id": 1}, {"id": 2}]})
    assert run(tree_from_python(), scope) == run(tree_from_text(), scope)
    assert run(tree_from_text(), scope)[:4] == (True, "Battery 7%", "red", True)
    scope = MapScope({"battery": 70, "name": "z", "workspaces": []})
    assert run(tree_from_python(), scope) == run(tree_from_text(), scope)
    assert run(tree_from_text(), scope) == (False, "Battery 70%", "ok", False, [])


def test_a_difference_in_the_python_form_is_a_difference_in_the_canonical_text():
    other = tree_from_python()
    other["if"] = tel.fill("battery < $limit", {"limit": 21})
    assert compiled(other) != compiled(tree_from_text())
    other = tree_from_python()
    other["in"] = tel.fill("name in $names", {"names": ["a", "c"]})
    assert compiled(other) != compiled(tree_from_text())


# -- values cannot change the shape of what they are put into -------------------------------------

ALPHABET = "ab '\"\\\n\t$#{}()[],:?é\x00"


def nasty(rng):
    return "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 12)))


def test_a_text_value_is_only_ever_a_string_in_an_expression_and_in_a_template_part():
    rng = random.Random(2026)
    scope = MapScope({"name": "n"})
    for _ in range(1500):
        value = nasty(rng)
        text = tel.fill("[$v, name, {$v: 1}]", {"v": value})
        got = tel.compile_expression(text, language=LANG).evaluate(scope)
        assert got == [value, "n", {value: 1}]
        template = tel.fill_template("a {{ $v }} b {{ name }} $x", {"v": value})
        got = tel.compile_template(template, language=LANG).evaluate(scope)
        assert got == f"a {value} b n $x"


def test_a_value_that_looks_like_code_is_a_string_and_reaches_nothing():
    scope = MapScope({"secret": "s"})
    for value in ("secret", "__import__('os')", "().__class__", "open", "x' + secret + '"):
        filled = tel.fill("$v", {"v": value})
        assert tel.compile_expression(filled, language=LANG).evaluate(scope) == value
        filled = tel.fill("$v.upper()", {"v": value})
        assert tel.compile_expression(filled, language=LANG).evaluate(scope) == value.upper()


def test_text_after_a_placeholder_is_still_checked_by_the_whitelist():
    for text in ("$v.__class__", "$v.__dict__", "[$v for _ in __import__('os')]", "$v(1)"):
        with pytest.raises(TelError):
            tel.compile_expression(tel.fill(text, {"v": 1}), language=LANG).evaluate(MapScope({}))


def test_a_placeholder_cannot_stand_for_a_name_or_an_attribute():
    with pytest.raises(tel.TelSyntaxError):  # `x.1` is not an attribute
        tel.compile_expression(tel.fill("x.$name", {"name": 1}), language=LANG)
    with pytest.raises(tel.TelSyntaxError):  # a string is not a name
        tel.compile_expression(tel.fill("$name + 1", {"name": "x"}) + " +", language=LANG)


def test_the_origins_of_a_python_built_tree_point_into_the_filled_text():
    text = tel.fill("battery < $limit and missing", {"limit": 20})
    start = text.index("missing")
    with pytest.raises(TelError) as raised:
        tel.compile_condition(text, language=LANG, origin=Origin("shell.py", 9, 4)).holds(
            MapScope({"battery": 1})
        )
    assert (raised.value.file, raised.value.line, raised.value.column) == (
        "shell.py",
        9,
        4 + start,
    )
