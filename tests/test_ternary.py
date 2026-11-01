"""`cond ? a : b` (decision D14): a second spelling of `a if cond else b`, rewritten before parsing.

The evidence is a differential test: random expressions written both ways must parse to the same
tree, and every name must report the position of its own text in what the author wrote.
"""

import ast
import random

import pytest

import tel
from tel import Limits, MapScope, TelError, TelLimitError, TelSyntaxError
from tel._parser import _read, parse, reads_as_expression
from tel._spans import node_span, split_lines
from tel._ternary import RewriteError, _Scanner, _tokens_fast, join, pieces_of
from tel.limits import DEFAULT_LIMITS


def build(text, **kw):
    return tel.compile_expression(text, language="0.1", **kw)


def run(text, **values):
    return build(text).evaluate(MapScope(values))


def fails(text, **values):
    with pytest.raises(TelError) as raised:
        run(text, **values)
    return raised.value


# -- the generator: a pair of (text with ?:, the same with if/else) --------------------------------

ATOMS = ["a", "b", "c", "n", "1", "2.5", "'?'", "':'", "'a?b:c'", "x.y", "f(1, 2)", "d['k']"]
CONDS = ["a", "not a", "a < b", "a or b", "a and not b", "n + 1", "x in xs", "a is not None"]
SPACES = [(" ", " "), ("", ""), (" ", ""), ("", " "), ("  ", "\t")]


def generate(rng, depth):
    kind = rng.random()
    if depth <= 0 or kind < 0.25:
        atom = rng.choice(ATOMS)
        return atom, atom
    if kind < 0.55:
        cond = cond_ref = rng.choice(CONDS)
        if rng.random() < 0.3:
            text, ref = generate(rng, depth - 1)
            cond, cond_ref = f"({text})", f"({ref})"
        mid, mid_ref = generate(rng, depth - 1)
        other, other_ref = generate(rng, depth - 1)
        s1, s2 = rng.choice(SPACES)
        s3, s4 = rng.choice(SPACES)
        return (
            f"{cond}{s1}?{s2}{mid}{s3}:{s4}{other}",
            f"(({mid_ref}) if ({cond_ref}) else ({other_ref}))",
        )
    (t1, r1), (t2, r2) = generate(rng, depth - 1), generate(rng, depth - 1)
    form = rng.choice(
        ["call", "list", "dict", "index", "slice", "comp", "filter", "fstr", "spec", "tuple"]
    )
    if form == "call":
        return f"f({t1}, {t2})", f"f({r1}, {r2})"
    if form == "list":
        return f"[{t1}, {t2}]", f"[{r1}, {r2}]"
    if form == "tuple":
        return f"({t1}, {t2})", f"({r1}, {r2})"
    if form == "dict":
        return f"{{'k': {t1}, 'j': {t2}}}", f"{{'k': {r1}, 'j': {r2}}}"
    if form == "index":
        return f"x[{t1}]", f"x[{r1}]"
    if form == "slice":
        return f"x[{t1} : {t2}]", f"x[{r1} : {r2}]"
    if form == "comp":
        return f"[{t1} for v in xs]", f"[{r1} for v in xs]"
    if form == "filter":
        return f"[v for v in xs if {t1}]", f"[v for v in xs if {r1}]"
    if form == "fstr":
        return f'f"{{ {t1} }} {{ {t2} }}"', f'f"{{ {r1} }} {{ {r2} }}"'
    return f'f"{{ {t1} :>{{ {t2} }}}}"', f'f"{{ {r1} :>{{ {r2} }}}}"'


def pairs(count, seed):
    rng = random.Random(seed)
    return [generate(rng, rng.randint(1, 4)) for _ in range(count)]


PAIRS = pairs(3000, seed=14)


def tree_of(text):
    pieces = pieces_of(text)
    return _read(text, None, DEFAULT_LIMITS, pieces), pieces


# -- the evidence ---------------------------------------------------------------------------------


def test_the_generator_makes_enough_real_ternaries():
    assert sum(1 for t, _ in PAIRS if pieces_of(t) is not None) > 1000


def test_random_expressions_parse_to_the_tree_if_else_makes():
    for text, reference in PAIRS:
        tree, pieces = tree_of(text)
        if pieces is None:
            assert text == reference
            continue
        want = ast.parse(reference, mode="eval")
        assert ast.dump(tree) == ast.dump(want), text


def test_every_name_reports_the_position_of_its_own_text():
    checked = 0
    for text, _ in PAIRS:
        tree, _ = tree_of(text)
        lines = split_lines(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                line, start, end = node_span(text, node)
                assert end is not None, text
                assert lines[line - 1][start - 1 : end - 1] == node.id, text
                checked += 1
    assert checked > 3000


def test_the_two_readers_find_the_same_tokens_in_text_without_f_strings():
    compared = 0
    for text, _ in PAIRS:
        if 'f"' in text:
            continue
        fast, full = _tokens_fast(text), _Scanner(text).tokens()
        assert (fast is None) == (full is None), text
        if fast is not None and full is not None:
            assert fast[:3] == full[:3], text
            assert fast.match == full.match and fast.prefix == full.prefix, text
            compared += 1
    assert compared > 500


def test_a_tracked_evaluation_of_a_ternary_reads_what_the_if_else_reads():
    scope = MapScope({"ok": True, "a": {"x": 1}, "b": {"y": 2}, "R": {"p": {"q": 5}}})
    for text, reference in [
        ("ok ? a.x : b.y", "a.x if ok else b.y"),
        ("not ok ? a.x : R.p.q", "a.x if not ok else R.p.q"),
        ("[ok ? a.x : b.y for _ in [1]]", "[a.x if ok else b.y for _ in [1]]"),
    ]:
        mine, theirs = build(text), build(reference)
        assert mine.evaluate_tracked(scope) == theirs.evaluate_tracked(scope)
        assert mine.paths == theirs.paths and mine.names == theirs.names


# -- the grammar ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "values", "want"),
    [
        ("ok ? 1 : 2", {"ok": True}, 1),
        ("ok ? 1 : 2", {"ok": False}, 2),
        ("ok?1:2", {"ok": True}, 1),
        ("n > 5 ? 'big' : n > 2 ? 'mid' : 'small'", {"n": 3}, "mid"),
        ("n > 5 ? 'big' : n > 2 ? 'mid' : 'small'", {"n": 1}, "small"),
        ("a ? b ? 1 : 2 : 3", {"a": True, "b": False}, 2),
        ("a ? b ? 1 : 2 : 3", {"a": False, "b": False}, 3),
        ("x or y ? 1 : 2", {"x": 0, "y": 1}, 1),
        ("not x ? 1 : 2", {"x": 0}, 1),
        ("x in xs ? 'in' : 'out'", {"x": 1, "xs": [1]}, "in"),
        ("1 + n ? 'yes' : 'no'", {"n": -1}, "no"),
        ("max(1, ok ? 5 : 2)", {"ok": True}, 5),
        ("[ok ? 1 : 0, 3]", {"ok": False}, [0, 3]),
        ("{'k': ok ? 1 : 2}", {"ok": False}, {"k": 2}),
        ("xs[ok ? 0 : 1]", {"ok": False, "xs": [7, 8]}, 8),
        ("xs[ok ? 1 : 2 : 3]", {"ok": True, "xs": [7, 8, 9, 10]}, [8, 9]),
        ("xs[0 : ok ? 1 : 2]", {"ok": False, "xs": [7, 8, 9]}, [7, 8]),
        ("[x ? 1 : 0 for x in xs]", {"xs": [0, 5]}, [0, 1]),
        ("[v for v in xs if v > 1 ? True : False]", {"xs": [1, 2, 3]}, [2, 3]),
        ("[v for v in xs ? [1] : [2]]", {"xs": []}, [2]),
        ("(ok ? 1 : 2, 3)", {"ok": True}, (1, 3)),
        ("ok ? 'a' : 'b'  # why? because: so", {"ok": False}, "b"),
        ("ok ?\n  'a'\n  : 'b'", {"ok": True}, "a"),
        ("(ok ? 1 : 2  # why\n)", {"ok": False}, 2),
        ("a ? 1 : b ? 2 : 3  # x\n# y", {"a": False, "b": True}, 2),
        ("[ok ? 1 : 2  # one\n  # two\n, 3]", {"ok": True}, [1, 3]),
    ],
)
def test_the_conditional_means_what_if_else_means(text, values, want):
    assert run(text, **values) == want


def test_only_the_branch_taken_is_evaluated():
    assert run("ok ? 1 : missing", ok=True) == 1
    assert fails("ok ? missing : 1", ok=True).code == "unknown-name"
    assert run("ok ? missing : 1", ok=False) == 1


@pytest.mark.parametrize(
    "text",
    [
        "f\"{ok ? 'a' : 'b'}\"",
        "f\"{ ok ? 'a' : 'b' }\"",
        "f\"{(ok ? 'a' : 'b')}\"",
        "f\"{ok ? 'a' : 'b'!s}\"",
        'f\'{ok ? "a" : "b"}\'',
    ],
)
def test_a_conditional_works_in_an_f_string_field(text):
    assert run(text, ok=True) == "a" and run(text, ok=False) == "b"


def test_a_colon_after_the_pair_in_an_f_string_field_is_the_format_spec():
    assert run('f"{ok ? 1 : 22:>4}|"', ok=False) == ("  22|")
    assert run('f"{ok ? 1 : 22:>{n ? 3 : 5}}|"', ok=True, n=1) == "  1|"


@pytest.mark.parametrize(
    "text",
    [
        "'what? yes: no'",
        "'a ? b : c'",
        'f"{x:?>5}"',
        'f"{x!r:?^9}"',
        'f"{x:{w}?}"',
        "'is it?'  # a comment? maybe",
        "x[1:2]",
        "{'a': 1, 'b': [1, 2][0:1]}",
        "'a' if x else 'c?'",
    ],
)
def test_a_question_mark_that_is_not_an_operator_changes_nothing(text):
    assert pieces_of(text) is None
    assert ast.dump(parse(text).tree) == ast.dump(ast.parse(text, mode="eval").body)


# -- what is refused, and where -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "message", "column"),
    [
        ("ok ? 1", "no ':'", 4),
        ("ok ? 1 : 2 ? 3", "no ':'", 12),
        ("a ?? b", "no ':'", 3),
        ("ok ? : 1", "nothing between", 4),
        ("? 1 : 2", "no condition", 1),
        ("ok ? 1 :", "nothing after", 8),
        ("f(ok ? 1, 2 : 3)", "no ':'", 6),
        ("[ok ? 1 for x in xs]", "no ':'", 5),
        ("ok ? 1 if x else 2 : 3", "cannot be mixed", 4),
        ("ok ? 1 : 2 if x else 3", "cannot be mixed", 4),
    ],
)
def test_a_question_mark_that_cannot_be_paired_is_a_syntax_error_at_the_question_mark(
    text, message, column
):
    with pytest.raises(TelSyntaxError) as raised:
        build(text)
    assert raised.value.code == "syntax-error"
    assert message in str(raised.value)
    assert (raised.value.line, raised.value.column) == (1, column)


def test_mixing_is_fine_when_the_other_spelling_is_in_brackets():
    assert run("ok ? (1 if x else 2) : 3", ok=True, x=False) == 2
    assert run("(1 if x else 2) if (ok ? y : z) else 9", ok=True, x=True, y=True, z=False) == 1


@pytest.mark.parametrize(
    ("text", "line", "column"),
    [
        ("ok ? 1 : 2 : 3", 1, 12),
        ("(ok ? 1 : 2", 1, 9),
        ("ok ? 1 : 2)", 1, 11),
    ],
)
def test_text_python_cannot_read_after_the_rewrite_is_reported_in_the_original(text, line, column):
    with pytest.raises(TelSyntaxError) as raised:
        build(text)
    assert (raised.value.line, raised.value.column) == (line, column)
    assert raised.value.end_column is None


@pytest.mark.parametrize(
    ("text", "code", "column"),
    [
        ("ok ? __class__ : 1", "private-name", 6),
        ("ok ? 1 : a.__dict__", "private-attribute", 10),
        ("ok ? open('x') : 1", "call-not-function", 6),
        ("ok ? (x := 1) : 2", "disallowed-construct", 7),
        ("ok ? lambda: 1 : 2", "syntax-error", 4),
    ],
)
def test_a_rule_broken_inside_a_conditional_is_reported_where_its_text_is(text, code, column):
    with pytest.raises(TelError) as raised:
        build(text)
    assert raised.value.code == code
    assert (raised.value.line, raised.value.column) == (1, column)


@pytest.mark.parametrize(
    ("text", "values", "code", "line", "column", "end"),
    [
        ("ok ? missing : 1", {"ok": True}, "unknown-name", 1, 6, 13),
        ("ok ? 1 : missing", {"ok": False}, "unknown-name", 1, 10, 17),
        ("missing ? 1 : 2", {}, "unknown-name", 1, 1, 8),
        ("ok ? 1 : 1 / 0", {"ok": False}, "division-by-zero", 1, 10, 15),
        ("n > 1 ? 'big' : n == 0 ? 1 / n : 'x'", {"n": 0}, "division-by-zero", 1, 26, 31),
        ("[x ? 1 / v : 0 for v in vs]", {"x": True, "vs": [1, 0]}, "division-by-zero", 1, 6, 11),
        ("f\"{ok ? 'a' : missing}\"", {"ok": False}, "unknown-name", 1, 15, 22),
        ("ok ? 'é' : missing", {"ok": False}, "unknown-name", 1, 12, 19),
        ("ok ?\n  missing\n  : 1", {"ok": True}, "unknown-name", 2, 3, 10),
        ("max(1, ok ? missing : 2)", {"ok": True}, "unknown-name", 1, 13, 20),
        ("'日本' + (ok ? missing : 1)", {"ok": True}, "unknown-name", 1, 14, 21),
    ],
)
def test_an_evaluation_error_in_any_part_is_reported_where_its_own_text_is(
    text, values, code, line, column, end
):
    error = fails(text, **values)
    assert error.code == code
    assert (error.line, error.column, error.end_column) == (line, column, end)


def test_an_error_at_the_whole_conditional_spans_all_of_its_text():
    for text, end in [("ok ? 1 : 2", 11), ("ok ?  'a'  :  'b'", 18), ("n > 1 ? 1 : 2  # why", 14)]:
        with pytest.raises(TelLimitError) as raised:
            build(text, limits=Limits(max_depth=1))
        assert (raised.value.line, raised.value.column, raised.value.end_column) == (1, 1, end)


def test_doubled_braces_in_an_f_string_are_text_not_fields():
    assert run('f"{{?}} {ok ? 1 : 2} }}"', ok=True) == "{?} 1 }"


@pytest.mark.parametrize("prefix", ["", "f'{1}' + "])
def test_an_assignment_expression_is_not_a_conditional_colon(prefix):
    with pytest.raises(TelError) as raised:
        build(prefix + "(a := ok ? 1 : 2)")
    assert raised.value.code == "disallowed-construct"


def test_a_conditional_in_a_template_part():
    scope = MapScope({"ok": True, "a": 1, "d": {"k": {"j": 7}}, "no": False})
    for text, want in [
        ("Battery {{ ok ? 'yes' : 'no' }}!", "Battery yes!"),
        ("Why? {{ a }}: really?", "Why? 1: really?"),
        ("{{ ok ? a : 2 }} and {{ no ? a : 2 }}", "1 and 2"),
        ("{{ ok ? d['k']['j'] : 2 }}", 7),
        ("{{ ok ? {'k': {'j': 9}}['k']['j'] : 2 }}", 9),
        ("{{ ok ? 'a}}b' : 'c' }}", "a}}b"),
        ("x {{ no ? 1 : ok ? 2 : 3 }} y", "x 2 y"),
    ]:
        template = tel.compile_template(text, language="0.1")
        assert template is not None and template.evaluate(scope) == want, text


def test_an_unpaired_question_mark_in_a_template_part_is_reported_in_the_template():
    for text, column in [("{{ ok ? }} {{ a }}", 7), ("a {{ ok ? 1 }}", 9)]:
        with pytest.raises(TelSyntaxError) as raised:
            tel.compile_template(text, language="0.1")
        assert (raised.value.line, raised.value.column) == (1, column), text


def test_a_template_part_ends_where_the_text_reads_as_an_expression():
    assert reads_as_expression("ok ? 1 : 2")
    assert not reads_as_expression("ok ? 1")
    assert not reads_as_expression("ok ? {'k': {'j': 1")
    assert not reads_as_expression("ok ? : 2")


# -- limits ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("count", [60, 200, 450])
def test_a_long_chain_is_a_depth_error_not_a_crash(count):
    text = "a?b:" * count + "c"
    with pytest.raises(TelLimitError) as raised:
        build(text, limits=Limits(max_source=10**6))
    assert raised.value.code == "limit-depth"


@pytest.mark.parametrize("count", [300, 3000])
def test_a_deep_middle_is_a_depth_error_not_a_crash(count):
    text = "a?" * count + "b" + ":c" * count
    big = Limits(max_source=10**6, max_depth=10**6, max_nodes=10**6)
    with pytest.raises(TelLimitError):
        build(text, limits=big)


def test_a_chain_within_the_limits_works():
    text = "n == 0 ? 'z' : " * 10 + "'none'"
    assert run(text, n=0) == "z" and run(text, n=1) == "none"


def test_the_source_limit_counts_the_text_the_author_wrote():
    text = "ok ? 1 : 2"
    assert build(text, limits=Limits(max_source=len(text))).evaluate(MapScope({"ok": True})) == 1
    with pytest.raises(TelLimitError):
        build(text, limits=Limits(max_source=len(text) - 1))


# -- the rewrite itself ---------------------------------------------------------------------------


def test_text_without_a_question_mark_operator_is_not_rewritten():
    for text in ["a + 1", "'a?b'", "x if y else z", "[i for i in xs]", ""]:
        assert pieces_of(text) is None


def test_the_rewrite_of_a_simple_conditional():
    text = "a < 1 ? 'x' : 'y'"
    pieces = pieces_of(text)
    assert pieces is not None
    assert ast.dump(ast.parse(join(text, pieces), mode="eval")) == ast.dump(
        ast.parse("'x' if a < 1 else 'y'", mode="eval")
    )


def test_an_unpaired_question_mark_raises_a_rewrite_error_with_its_index():
    with pytest.raises(RewriteError) as raised:
        pieces_of("abc ? 1")
    assert raised.value.index == 4


def test_a_compiled_conditional_keeps_the_text_the_author_wrote():
    expr = build("  ok ? 1 : 2  ")
    assert expr.source == "  ok ? 1 : 2  " and expr.text == "ok ? 1 : 2"
