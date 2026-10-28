"""The parser and whitelist (step 3, phase 3): what compiles, what is refused, and why."""

import ast
import random
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor

import pytest
from reference import cases
from reference.expectations import (
    DROPPED_HELPER_CASES,
    EVALUATION_LEVEL,
    EVALUATION_LEVEL_ESCAPES,
    PARSE_LEVEL_LIMITS,
)

from tel import Limits, Origin, TelError, TelLimitError, TelSyntaxError
from tel._parser import Parsed, parse
from tel._whitelist import ALLOWED_NODES, BUILTIN_NAMES, METHOD_NAMES


def refused(source, code, **kw):
    with pytest.raises(TelError) as raised:
        parse(source, **kw)
    assert raised.value.code == code, str(raised.value)
    return raised.value


# -- the reference tables, at parse level ---------------------------------------------------------

PARSE_REFUSED = {
    "lambda: 1": "disallowed-construct",
    "(y := 1)": "disallowed-construct",
    "x if": "syntax-error",
    "await x": "disallowed-construct",
    "x & 1": "disallowed-construct",
    "x | 1": "disallowed-construct",
    "x ^ 1": "disallowed-construct",
    "x << 1": "disallowed-construct",
    "x >> 1": "disallowed-construct",
    "~x": "disallowed-construct",
    "x @ x": "disallowed-construct",
    "b'x'": "constant-type",
    "1j": "constant-type",
    "...": "constant-type",
    "{**d}": "dict-unpack",
    "f(**d)": "call-unpack",
    "len(**d)": "call-unpack",
    "x is 3": "is-operand",
    "x is x": "is-operand",
    "x is not 'a'": "is-operand",
    "[i async for i in x]": "comprehension-async",
    "[x for x[0] in items]": "comprehension-target",
    "(1)(2)": "call-target",
    "items[0](1)": "call-target",
    "_x": "private-name",
    "x._y": "private-attribute",
    "x.__class__": "private-attribute",
    "__builtins__": "private-name",
    "open('f')": "call-not-function",
    "eval('1')": "call-not-function",
    "exec('1')": "call-not-function",
    "getattr(x, 'a')": "call-not-function",
    "type(x)": "call-not-function",
    "globals()": "call-not-function",
    "print(1)": "call-not-function",
    "name.format()": "method-format",
    "name.format_map({})": "method-format",
    "name.encode()": "method-not-available",
    "items.append(1)": "method-not-available",
    "items.pop()": "method-not-available",
    "d.update({})": "method-not-available",
    "d.pop('k')": "method-not-available",
    "items.sort()": "method-not-available",
    "(1).bit_length()": "method-not-available",
    "x +": "syntax-error",
    "": "empty-expression",
    "   ": "empty-expression",
    "1 2": "syntax-error",
    "x = 1": "syntax-error",
    "import os": "syntax-error",
}


@pytest.mark.parametrize(
    "source", [c[0] for c in cases.ALLOWED if c[0] not in DROPPED_HELPER_CASES]
)
def test_everything_the_grammar_allows_parses(source):
    assert isinstance(parse(source), Parsed)


def test_the_dropped_helpers_are_in_the_table_and_are_refused():
    assert DROPPED_HELPER_CASES <= {c[0] for c in cases.ALLOWED}
    for source in DROPPED_HELPER_CASES:
        refused(source, "call-not-function")


def test_the_disallowed_table_is_covered_exactly():
    assert set(PARSE_REFUSED) | set(EVALUATION_LEVEL) == {c[0] for c in cases.DISALLOWED}
    assert not set(PARSE_REFUSED) & set(EVALUATION_LEVEL)


@pytest.mark.parametrize("source, code", list(PARSE_REFUSED.items()), ids=list(PARSE_REFUSED))
def test_what_the_grammar_refuses_is_refused_with_its_code(source, code):
    error = refused(source, code)
    assert isinstance(error, TelSyntaxError) and error.message


@pytest.mark.parametrize("source", sorted(EVALUATION_LEVEL))
def test_what_is_refused_only_with_a_value_still_parses(source):
    parse(source)


def test_every_escape_is_refused_here_or_marked():
    accepted = set()
    for source in cases.ESCAPES:
        try:
            parse(source)
        except TelError:
            continue
        accepted.add(source)
    expected = set(EVALUATION_LEVEL_ESCAPES)
    assert accepted == expected, sorted(accepted ^ expected)


@pytest.mark.parametrize(
    "source, message, limits", cases.LIMIT_CASES, ids=[c[0][:40] for c in cases.LIMIT_CASES]
)
def test_limit_cases_are_refused_at_parse_or_left_to_evaluation(source, message, limits):
    if source in PARSE_LEVEL_LIMITS:
        error = refused(source, PARSE_LEVEL_LIMITS[source], limits=Limits(**limits))
        assert isinstance(error, TelLimitError)
    else:
        parse(source, limits=Limits(**limits))


# -- the whitelist itself -------------------------------------------------------------------------

ALLOWED_NODE_NAMES = """
    Expression Constant Name Load Store Attribute Subscript Slice UnaryOp Not USub UAdd BinOp
    Add Sub Mult Div FloorDiv Mod Pow BoolOp And Or Compare Eq NotEq Lt LtE Gt GtE In NotIn Is
    IsNot IfExp JoinedStr FormattedValue List Tuple Set Dict ListComp DictComp SetComp
    GeneratorExp comprehension Call keyword Starred
""".split()


def test_the_allowed_node_types_are_exactly_these():
    assert sorted(t.__name__ for t in ALLOWED_NODES) == sorted(ALLOWED_NODE_NAMES)


def test_every_python_expression_node_is_either_allowed_or_refused_by_name():
    # a node type that Python adds later is not allowed until it is listed, and a test says so
    for node_type in ast.expr.__subclasses__():
        if node_type in ALLOWED_NODES:
            continue
        sample = {
            ast.Lambda: "lambda: 1",
            ast.NamedExpr: "(y := 1)",
            ast.Await: "await x",
            ast.Yield: "(yield)",
            ast.YieldFrom: "(yield from x)",
            ast.TemplateStr: "t'{x}'",
            ast.Interpolation: None,  # only inside a t-string
        }
        assert node_type in sample, f"{node_type.__name__} is neither allowed nor tested as refused"
        if sample[node_type] is not None:
            error = refused(sample[node_type], "disallowed-construct")
            # named in words, not by the Python class (that is the fallback for unknown nodes)
            assert node_type.__name__ not in error.message


def test_a_t_string_is_refused_by_name():
    error = refused("t'{x}'", "disallowed-construct")
    assert "t-string" in error.message


def test_the_built_in_names_are_the_documented_twenty_three():
    assert BUILTIN_NAMES == frozenset(
        """
        len min max abs round sum str int float bool sorted reversed range enumerate
        zip any all list dict tuple set isinstance clamp
    """.split()
    )


def test_the_method_names_are_the_documented_ones():
    assert METHOD_NAMES == frozenset(
        """
        lower upper title capitalize strip lstrip rstrip split splitlines join
        startswith endswith replace find count zfill isdigit isalpha center ljust
        rjust removeprefix removesuffix index get keys values items
    """.split()
    )


@pytest.mark.parametrize("name", sorted(BUILTIN_NAMES))
def test_each_built_in_can_be_called(name):
    parse(f"{name}(x)" if name != "isinstance" else "isinstance(x, int)")


@pytest.mark.parametrize("name", sorted(METHOD_NAMES))
def test_each_whitelisted_method_can_be_called(name):
    parse(f"x.{name}(y)")


@pytest.mark.parametrize(
    "name",
    [
        "append",
        "pop",
        "update",
        "setdefault",
        "sort",
        "reverse",
        "clear",
        "remove",
        "insert",
        "extend",
        "popitem",
    ],
)
def test_a_method_that_mutates_is_refused(name):
    refused(f"x.{name}()", "method-not-available")


def test_format_is_named_as_the_reason_it_is_refused():
    assert "attributes" in refused("x.format()", "method-format").message


def test_calling_a_name_that_is_not_a_built_in_function_is_refused():
    error = refused("save(x)", "call-not-function")
    assert "'save'" in error.message and "not a function you can call here" in error.message
    parse("save(x)", functions=BUILTIN_NAMES | {"save"})  # a host that supplies it may allow it


def test_a_comprehension_variable_cannot_be_called_even_if_it_is_named_like_a_built_in():
    refused("[len(1) for len in x]", "call-not-function")
    parse("[len(i) for i in x]")


def test_a_private_keyword_name_is_refused():
    refused("sorted(x, _key=1)", "private-name")


@pytest.mark.parametrize(
    "source", ["isinstance(x, int)", "isinstance(x, str)", "isinstance(x, dict)"]
)
def test_isinstance_takes_one_of_the_basic_types(source):
    parse(source)


@pytest.mark.parametrize(
    "source",
    [
        "isinstance(x, (int, str))",
        "isinstance(x, object)",
        "isinstance(x, trap)",
        "isinstance(x, int | str)",
        "isinstance(x)",
        "isinstance(x, int, str)",
        "isinstance(x, classinfo=int)",
        "isinstance(x, tuple)",
        "isinstance(*x)",
    ],
)
def test_isinstance_refuses_anything_else(source):
    refused(source, "isinstance-type")


@pytest.mark.parametrize(
    "source", ["x is None", "x is True", "x is not False", "a is None is not False"]
)
def test_is_compares_with_none_true_or_false(source):
    parse(source)


@pytest.mark.parametrize(
    "source", ["x is 0", "x is 'a'", "x is y", "x is -1", "x is None is 3", "x is not []"]
)
def test_is_compares_with_nothing_else(source):
    refused(source, "is-operand")


def test_unpacking_a_mapping_is_refused_but_a_sequence_may_be_spread():
    refused("{**d}", "dict-unpack")
    refused("f(**d)", "call-unpack")
    parse("[*a, *b]")
    parse("max(*a)")


@pytest.mark.parametrize(
    "source", ["[x for (a, b) in y]", "[x for [a, b] in y]", "[x for a in y for b in a]"]
)
def test_a_comprehension_may_bind_names_and_tuples_of_names(source):
    parse(source)


@pytest.mark.parametrize("source", ["[x for *a, b in y]", "[x for a.b in y]", "[x for a[0] in y]"])
def test_a_comprehension_target_must_be_a_name(source):
    refused(source, "comprehension-target")


def test_a_comprehension_target_that_python_itself_rejects_is_a_syntax_error():
    refused("[x for 1 in y]", "syntax-error")


def test_python_folds_wide_characters_and_the_checks_see_the_folded_name():
    assert parse("ｌｅｎ(x)").names == {"x"}  # fullwidth letters fold to `len`, a built-in callee
    assert parse("ｘ").names == {"x"}  # ... and to an ASCII name
    refused("ｅval('1')", "call-not-function")


def test_a_comprehension_target_may_not_be_private():
    refused("[x for _y in z]", "private-name")


# -- names ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["_x", "__class__", "__builtins__", "_", "_＿class＿＿", "_＿private", "_＿"]
)
def test_a_name_starting_with_an_underscore_is_refused_even_when_written_in_wide_characters(name):
    refused(name, "private-name")


@pytest.mark.parametrize("attr", ["_x", "__class__", "_＿class＿＿", "_＿private"])
def test_an_attribute_starting_with_an_underscore_is_refused_even_when_written_in_wide_characters(
    attr,
):
    refused(f"x.{attr}", "private-attribute")


def test_a_single_underscore_is_allowed_only_as_a_throwaway_loop_variable():
    parse("[0 for _ in items]")
    parse("[_ for _ in items]")
    refused("_ + 1", "private-name")


def test_the_free_names_are_collected_and_comprehension_names_are_not_free():
    assert parse("a + b.c[d]").names == {"a", "b", "d"}
    assert parse("[i * k for i in items]").names == {"k", "items"}
    assert parse("{k: v for k, v in pairs if k != skip}").names == {"pairs", "skip"}
    assert parse("1 + 2").names == frozenset()


def test_the_first_iterable_sees_the_outer_names_and_later_ones_see_the_targets():
    assert parse("[x for x in x]").names == {"x"}
    assert parse("[y for x in xs for y in x]").names == {"xs"}
    assert parse("[(x, y) for x in xs for y in ys if x < z]").names == {"xs", "ys", "z"}


def test_a_name_bound_in_one_comprehension_is_free_in_the_next():
    assert parse("[i for i in a] + [i for j in b]").names == {"a", "b", "i"}


def test_a_called_built_in_is_not_a_name_the_scope_is_asked_for():
    assert parse("len(items)").names == {"items"}
    assert parse("len").names == {"len"}  # read as a value, it is looked up in the scope first


# -- constants ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source", ["1", "1.5", "'a'", "True", "False", "None", "0x10", "1_000", "1e999"]
)
def test_plain_constants_are_allowed(source):
    parse(source)


@pytest.mark.parametrize("source", ["b'x'", "1j", "...", "1.5j", "(b'a', 1)"])
def test_other_constants_are_refused(source):
    refused(source, "constant-type")


def test_an_integer_literal_over_the_bit_limit_is_refused():
    refused("9" * 1300, "limit-int-bits", limits=Limits(max_source=10_000, max_int_bits=4_096))
    parse("9" * 1200, limits=Limits(max_source=10_000, max_int_bits=4_096))


def test_an_integer_literal_python_itself_cannot_read_is_a_limit_not_a_crash():
    refused("9" * 5000, "limit-int-bits", limits=Limits(max_source=10_000))


def test_a_string_literal_over_the_limit_is_refused():
    refused("'" + "a" * 50 + "'", "limit-string", limits=Limits(max_string=49))
    parse("'" + "a" * 49 + "'", limits=Limits(max_string=49))


def test_a_constant_exponent_over_the_limit_is_refused_before_evaluation():
    parse("2 ** 64")
    parse("2 ** x")  # not a constant: checked while evaluating
    refused("2 ** 65", "limit-pow-exponent")
    refused("x ** 65", "limit-pow-exponent")
    parse("2 ** 10", limits=Limits(max_pow_exponent=10))
    refused("2 ** 11", "limit-pow-exponent", limits=Limits(max_pow_exponent=10))


# -- limits of the text ---------------------------------------------------------------------------


def test_source_length_boundary():
    parse("1" + " " * 7, limits=Limits(max_source=8))  # exactly 8 characters
    refused("1" + " " * 8, "limit-source", limits=Limits(max_source=8))


# Operators and contexts are shared instances with no children: they are not counted.
SINGLETONS = (ast.expr_context, ast.operator, ast.unaryop, ast.boolop, ast.cmpop)


def counted_children(node):
    return [c for c in ast.iter_child_nodes(node) if not isinstance(c, SINGLETONS)]


def tree_depth(node, depth=1):
    return max([depth] + [tree_depth(c, depth + 1) for c in counted_children(node)])


def count_nodes(node):
    return 1 + sum(count_nodes(c) for c in counted_children(node))


@pytest.mark.parametrize(
    "source", ["x", "[[[1]]]", "a + (b * (c - d))", "[[[[[[1]]]]]]", "len(abs(max(1)))"]
)
def test_depth_counts_the_expression_root_as_one(source):
    depth = tree_depth(ast.parse(source, mode="eval"))
    parse(source, limits=Limits(max_depth=depth))
    refused(source, "limit-depth", limits=Limits(max_depth=depth - 1))


def test_node_count_boundary():
    count = count_nodes(ast.parse("[1, 2, 3]", mode="eval"))
    assert count == 5  # Expression, List, three constants: no context
    parse("[1, 2, 3]", limits=Limits(max_nodes=count))
    refused("[1, 2, 3]", "limit-nodes", limits=Limits(max_nodes=count - 1))


@pytest.mark.parametrize(
    "source",
    [
        "(" * 500 + "1" + ")" * 500,
        "[" * 300 + "]" * 300,
        "-" * 100_000 + "1",
        "not " * 50_000 + "x",
        "[" * 5000 + "]" * 5000,
        "1 if 1 else " * 2000 + "2",
        "f" + "(" * 3000 + ")" * 3000,
        "x" + ".y" * 20_000,
        "x" + "[0]" * 20_000,
        "1" + " + 1" * 20_000,
    ],
    ids=[
        "parens",
        "brackets",
        "minus",
        "not",
        "brackets-5000",
        "if-else",
        "call",
        "attributes",
        "subscripts",
        "additions",
    ],
)
def test_pathologically_deep_text_is_a_limit_error_and_never_a_crash(source):
    error = refused(source, "limit-depth", limits=Limits(max_source=1_000_000, max_nodes=10**7))
    assert isinstance(error, TelLimitError)


# -- text that Python itself trips over ----------------------------------------------------------


def test_empty_and_blank_text_is_an_error_with_its_own_code():
    for text in ("", " ", "\n\t \n"):
        refused(text, "empty-expression")


def test_text_around_the_expression_is_ignored():
    parsed = parse("  \n  count + 1 \n ")
    assert parsed.text == "count + 1"


def test_a_null_byte_or_a_lone_surrogate_is_a_syntax_error_not_a_crash():
    refused("x\x00", "invalid-text")
    refused("'\ud800'", "invalid-text")


def test_an_invalid_escape_in_a_string_is_text_and_prints_nothing():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        parsed = parse(r"'\d' + x")
    assert caught == [] and isinstance(parsed.tree, ast.BinOp)


def test_parsing_from_many_threads_gives_the_same_answers_and_no_warnings():
    sources = [r"'\d' + x", "a + b", "_x", "x +", "[i for i in z]", "2 ** 65"] * 25

    def one(source):
        try:
            return parse(source).text
        except TelError as error:
            return error.code

    expected = [one(s) for s in sources]
    barrier = threading.Barrier(8)

    def worker(chunk):
        barrier.wait()
        return [one(s) for s in chunk]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with ThreadPoolExecutor(8) as pool:
            results = list(pool.map(worker, [sources] * 8))
    assert all(r == expected for r in results)
    assert caught == []


def test_random_one_token_mutations_only_ever_give_tel_errors_or_a_parse():
    rng = random.Random(2026)
    tokens = [
        "__class__",
        "lambda",
        "import",
        ":=",
        "**",
        "[",
        "]",
        "(",
        ")",
        "'",
        ".",
        "_",
        "\x00",
        "\ud800",
        "é",
        "\n",
        "t'",
    ]
    seeds = [c[0] for c in cases.ALLOWED] + list(cases.ESCAPES[:60])
    for source in seeds:
        for _ in range(8):
            cut = rng.randrange(len(source) + 1)
            mutated = source[:cut] + rng.choice(tokens) + source[cut:]
            try:
                parse(mutated)
            except TelError:
                pass


# -- positions ------------------------------------------------------------------------------------


def test_a_syntax_error_counts_characters_and_maps_into_the_file():
    error = refused("'é' x", "syntax-error", origin=Origin("A.yaml", 3, 11))
    assert (error.line, error.column) == (3, 15)  # character 5 of the text, shifted by the origin


def test_a_syntax_error_after_leading_space_accounts_for_it():
    error = refused("   x +", "syntax-error", origin=Origin("A_View.yaml", 2, 10))
    assert error.line == 2 and error.column >= 13 and "syntax error" in error.message


def test_a_rule_error_points_at_the_node_with_its_span():
    error = refused("count + _x", "private-name", origin=Origin("V.yaml", 14, 8))
    assert (error.line, error.column, error.end_column) == (14, 16, 18)
    assert error.render().splitlines()[2].endswith("^^")


def test_a_rule_error_after_a_non_ascii_character_is_in_characters():
    error = refused("'é' + _x", "private-name")
    assert (error.column, error.end_column) == (7, 9)


def test_an_error_on_a_later_line_of_the_text_is_on_that_line_of_the_file():
    error = refused("(1 +\n  _x)", "private-name", origin=Origin("A.yaml", 5, 5))
    assert (error.line, error.column) == (6, 3)


def test_the_error_carries_the_stripped_text_and_an_origin_aligned_to_it():
    error = refused("  \n  _x", "private-name", origin=Origin("A.yaml", 5, 5))
    assert error.source == "_x" and (error.line, error.column) == (6, 3)


# -- the result -----------------------------------------------------------------------------------


def test_parsed_holds_the_checked_tree_and_what_evaluation_needs():
    parsed = parse("  a + 1 ", origin=Origin("A.yaml", 2, 4))
    assert isinstance(parsed.tree, ast.BinOp)
    assert parsed.text == "a + 1" and parsed.source == "  a + 1 "
    assert parsed.origin == Origin("A.yaml", 2, 6)
    assert parsed.names == {"a"}
    assert parsed.nodes == count_nodes(ast.parse("a + 1", mode="eval")) == 4


def test_parsed_is_immutable():
    parsed = parse("a")
    with pytest.raises(AttributeError):
        parsed.text = "b"  # type: ignore[misc]


# -- rules that source text alone cannot reach ----------------------------------------------------


def test_a_node_that_is_neither_allowed_nor_named_is_refused_too():
    # defence in depth: a node type Python adds later is not allowed until it is listed
    from tel._parser import _Checker

    tree = ast.Expression(body=ast.Pass())  # type: ignore[arg-type]
    checker = _Checker("pass", None, Limits(), BUILTIN_NAMES)
    with pytest.raises(TelSyntaxError) as raised:
        checker.visit(tree, 1)
    assert raised.value.code == "disallowed-construct" and "Pass" in raised.value.message


def test_isinstance_cannot_be_fooled_by_a_loop_variable_named_like_a_type():
    refused("[isinstance(1, int) for int in z]", "isinstance-type")
    parse("[isinstance(i, int) for i in z]")


@pytest.mark.parametrize("source", ["x = 1", "import os", "del x", "pass", "x += 1"])
def test_text_that_is_a_statement_says_that_tel_has_none(source):
    error = refused(source, "syntax-error")
    assert error.hint is not None and "no statements" in error.hint


def test_text_that_is_not_a_statement_either_has_no_such_hint():
    assert refused("x +", "syntax-error").hint is None


@pytest.mark.parametrize("n", [500, 3000, 20_000])
@pytest.mark.parametrize("shape", ["-{}1", "{}x", "x{}"])
def test_python_running_out_of_stack_is_a_depth_error_even_when_the_limit_is_set_very_high(
    n, shape
):
    # with max_depth this high the checker's own recursion is what runs out first
    unit = {"-{}1": "-", "{}x": "not ", "x{}": ".y"}[shape]
    source = shape.format(unit * n)
    huge = Limits(max_source=1_000_000, max_depth=10**7, max_nodes=10**7)
    refused(source, "limit-depth", limits=huge)


@pytest.mark.parametrize(
    "source", ["1if x else 2", "0x1for x in y", "[1or 2]", "x1y + 1", r"'\d'", r"b'\d'"]
)
def test_text_that_makes_python_warn_is_read_without_a_sound(source):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            parse(source)
        except TelError:
            pass
    assert caught == []
