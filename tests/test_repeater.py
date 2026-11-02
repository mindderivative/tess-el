"""Repeaters (step 5, phase 3): the header `item in items`, the key, and the items they give."""

import copy
import inspect
import pickle
import sys
import time

import pytest

import tel
from tel import (
    Limits,
    MapScope,
    Origin,
    Repeater,
    TelError,
    TelEvaluationError,
    TelLimitError,
    TelSyntaxError,
)

CEILING = 0.5  # seconds: same meaning as in test_evaluator_limits


def rep(header="w in workspaces", key="w.id", **kw):
    kw.setdefault("name", "Workspace")
    return tel.compile_repeater(header, key=key, language="0.1", **kw)


def scope(**values):
    return MapScope(values)


def keys(repeater, **values):
    return [item.key for item in repeater.items(scope(**values))]


class Thing:
    """A host object: not a plain value."""

    def __init__(self, id):
        self.id = id


WS = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}, {"id": 3, "name": "c"}]


# -- what the items are ---------------------------------------------------------------------------


def test_each_item_has_its_index_key_and_value_in_list_order():
    items = rep("w in workspaces", "w.id").items(scope(workspaces=WS))
    assert [(i.index, i.key, i.value) for i in items] == [
        (0, 1, WS[0]),
        (1, 2, WS[1]),
        (2, 3, WS[2]),
    ]
    assert isinstance(items, tuple)


def test_an_empty_list_has_no_items():
    assert rep().items(scope(workspaces=[])) == ()


def test_the_key_may_read_the_host_scope_too():
    assert keys(rep(key="prefix + w.name"), workspaces=WS, prefix="ws-") == ["ws-a", "ws-b", "ws-c"]


def test_the_item_name_hides_a_host_name_of_the_same_name():
    assert keys(rep(key="w"), workspaces=[5, 6], w=99) == [5, 6]


def test_the_list_expression_is_any_expression():
    r = rep("n in range(3)", "n")
    assert keys(r) == [0, 1, 2]
    r = rep("w in [x for x in workspaces if x.id > 1]", "w.id")
    assert keys(r, workspaces=[Thing(1), Thing(2), Thing(3)]) == [2, 3]


def test_a_host_object_item_is_carried_and_its_attributes_are_read():
    assert keys(rep(), workspaces=[Thing("a"), Thing("b")]) == ["a", "b"]


@pytest.mark.parametrize(
    ("header", "value", "expected"),
    [
        ("w in xs", ("p", "q"), ["p", "q"]),
        ("w in xs", {"k1": 1, "k2": 2}, ["k1", "k2"]),  # a dict gives its keys
        ("w in xs", "abc", ["a", "b", "c"]),
        ("w in xs", range(2), [0, 1]),
    ],
)
def test_the_list_may_be_anything_a_comprehension_loops_over_in_a_stable_order(
    header, value, expected
):
    assert keys(rep(header, "w"), xs=value) == expected


@pytest.mark.parametrize("value", [{1, 2}, frozenset({1})])
def test_a_set_is_refused_because_its_order_is_not_stable(value):
    with pytest.raises(TelEvaluationError) as raised:
        rep("w in xs", "w").items(scope(xs=value))
    assert raised.value.code == "not-iterable"
    assert "order" in raised.value.message


@pytest.mark.parametrize("value", [5, None, 2.5, True, Thing(1)])
def test_a_value_that_cannot_be_looped_over_is_refused(value):
    with pytest.raises(TelEvaluationError) as raised:
        rep("w in xs", "w").items(scope(xs=value))
    assert raised.value.code == "not-iterable"


def test_a_header_whose_list_is_a_comparison_compiles_and_then_is_not_iterable():
    r = rep("a in b in c", "a")  # `b in c` is an expression like any other
    with pytest.raises(TelEvaluationError) as raised:
        r.items(scope(b=1, c=[1]))
    assert raised.value.code == "not-iterable"


# -- the header -----------------------------------------------------------------------------------


def test_two_names_unpack_each_item():
    r = rep("i, w in enumerate(workspaces)", "w.id")
    assert keys(r, workspaces=WS) == [1, 2, 3]
    item = r.items(scope(workspaces=WS))[1]
    child = item.scope(scope())
    assert (child.lookup("i"), child.lookup("w")) == (1, WS[1])


def test_the_key_may_use_the_position_name():
    assert keys(rep("i, w in enumerate(xs)", "i"), xs="abc") == [0, 1, 2]


def test_a_tuple_item_unpacks_and_a_list_item_too():
    assert keys(rep("a, b in xs", "a"), xs=[(1, 2), [3, 4]]) == [1, 3]


@pytest.mark.parametrize("item", [(1,), (1, 2, 3), "ab", 5, {1: 2, 3: 4}, {1, 2}])
def test_an_item_with_the_wrong_shape_cannot_be_unpacked(item):
    with pytest.raises(TelEvaluationError) as raised:
        rep("a, b in xs", "a").items(scope(xs=[item]))
    assert raised.value.code == "bad-unpack"


def test_spacing_and_line_breaks_in_the_header_are_fine():
    assert keys(rep("  w   in   xs  ", "w"), xs=[1]) == [1]
    assert keys(rep("a ,\n b\n in\n xs", "b"), xs=[(1, 2)]) == [2]
    assert keys(rep("w in(xs)", "w"), xs=[1]) == [1]


def test_the_word_in_inside_a_name_is_not_the_keyword():
    assert keys(rep("index in inbox", "index"), inbox=[4]) == [4]


@pytest.mark.parametrize(
    ("header", "column", "needle"),
    [
        ("", 1, "empty"),
        ("   ", 1, "empty"),
        ("workspaces", 1, "no `in`"),
        ("origin xs", 1, "no `in`"),
        ("w inbox", 1, None),
        (" in xs", 2, "no loop variable"),
        ("w of xs", 1, "no `in`"),
        ("w in", 3, "nothing after"),
        ("w in   ", 3, "nothing after"),
        ("(a, b) in xs", 1, "loop variable"),
        ("a.b in xs", 1, "loop variable"),
        ("a[0] in xs", 1, "loop variable"),
        ("1 in xs", 1, "loop variable"),
        ("a, in xs", 1, "loop variable"),
        ("*a in xs", 1, "loop variable"),
        ("for w in xs", 1, "loop variable"),
    ],
)
def test_a_header_that_is_not_names_in_an_expression_is_a_syntax_error(header, column, needle):
    with pytest.raises(TelSyntaxError) as raised:
        rep(header)
    error = raised.value
    assert error.code == "repeater-header"
    if needle:
        assert needle in error.message
    if column is not None:
        assert (error.line, error.column) == (1, column)


def test_a_name_that_is_a_keyword_or_private_or_repeated_is_refused():
    with pytest.raises(TelSyntaxError) as raised:
        rep("class in xs")
    assert raised.value.code == "repeater-header"
    with pytest.raises(TelSyntaxError) as raised:
        rep("_w in xs")
    assert raised.value.code == "private-name"
    assert rep("_ in xs", "1").targets == ("_",)
    with pytest.raises(TelSyntaxError) as raised:
        rep("a, a in xs")
    assert raised.value.code == "repeater-header" and "twice" in raised.value.message
    assert (raised.value.line, raised.value.column) == (1, 4)


def test_a_bad_list_expression_is_the_usual_syntax_error_at_its_place_in_the_header():
    with pytest.raises(TelSyntaxError) as raised:
        rep("w in a +", origin=Origin(file="s.yaml", line=10, column=7))
    error = raised.value
    assert error.code == "syntax-error"
    assert (error.file, error.line) == ("s.yaml", 10)
    assert error.column >= 7 + len("w in ")


def test_an_expression_that_is_not_allowed_in_the_list_is_refused_at_compile_time():
    for text in ("w in lambda: 1", "w in x.__class__", "w in open('f')"):
        with pytest.raises(TelSyntaxError):
            rep(text)


def test_the_targets_are_listed():
    assert rep("w in xs").targets == ("w",)
    assert rep("i, w in xs").targets == ("i", "w")


# -- the key --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("1", 1),
        ("'a'", "a"),
        ("(1, 'a')", (1, "a")),
        ("(w, 2)", (5, 2)),
        ("-3", -3),
        ("10 ** 30", 10**30),
        ("()", ()),
    ],
)
def test_a_key_is_an_int_a_str_or_a_tuple_of_those(key, expected):
    assert keys(rep("w in xs", key), xs=[5]) == [expected]


@pytest.mark.parametrize(
    "key", ["1.5", "True", "None", "(1, 2.5)", "(1, (2, 3))", "[1]", "{1: 2}", "w"]
)
def test_any_other_key_is_bad_key_type_and_says_which_item(key):
    with pytest.raises(TelEvaluationError) as raised:
        rep("w in xs", key).items(scope(xs=[Thing(1) if key == "w" else 0, 0]))
    error = raised.value
    assert error.code == "bad-key-type"
    assert (error.line, error.column) == (1, 1)
    assert "item 0" in error.message


def test_the_item_that_made_a_bad_key_is_named_whichever_it_is():
    with pytest.raises(TelEvaluationError) as raised:
        rep("w in xs", "w").items(scope(xs=[1, 2, 3.5, 4]))
    assert "item 2" in raised.value.message


def test_a_str_or_int_subclass_is_a_key_as_its_plain_value():
    class Name(str):
        def __hash__(self):
            raise RuntimeError("host code ran")

        def __eq__(self, other):
            raise RuntimeError("host code ran")

    class Num(int):
        def __hash__(self):
            raise RuntimeError("host code ran")

    (name,) = keys(rep("w in xs", "w"), xs=[Name("a")])
    (num,) = keys(rep("w in xs", "w"), xs=[Num(4)])
    assert (type(name), name, type(num), num) == (str, "a", int, 4)


def test_a_duplicate_key_names_both_items_but_not_the_key():
    with pytest.raises(TelEvaluationError) as raised:
        rep("w in xs", "w").items(scope(xs=["a", "b", "c", "b"]))
    error = raised.value
    assert error.code == "duplicate-key"
    assert "items 1 and 3" in error.message
    assert "'b'" not in error.message  # messages never carry values from the scope
    assert (error.line, error.column) == (1, 1)


def test_keys_that_look_alike_are_different_keys():
    assert keys(rep("w in xs", "w"), xs=[1, "1", (1,), (1, 1)]) == [1, "1", (1,), (1, 1)]


def test_a_key_that_fails_fails_like_any_expression():
    with pytest.raises(TelError) as raised:
        rep("w in xs", "w.missing").items(scope(xs=[{"id": 1}]))
    assert raised.value.code == "no-key"


def test_an_error_in_the_key_points_into_the_key_scalar_not_the_header():
    r = rep("w in xs", "w / 0", origin=Origin("a.yaml", 4, 6), key_origin=Origin("a.yaml", 5, 8))
    with pytest.raises(TelError) as raised:
        r.items(scope(xs=[1]))
    assert (raised.value.file, raised.value.line, raised.value.column) == ("a.yaml", 5, 8)


def test_a_bad_key_type_error_points_into_the_key_scalar():
    r = rep("w in xs", " 1.5", key_origin=Origin("a.yaml", 5, 8))
    with pytest.raises(TelEvaluationError) as raised:
        r.items(scope(xs=[1]))
    assert (raised.value.line, raised.value.column) == (5, 9)  # past the leading space


def test_an_error_in_the_list_points_into_the_header():
    r = rep("w in 1 / 0", origin=Origin("a.yaml", 4, 6))
    with pytest.raises(TelError) as raised:
        r.items(scope())
    assert (raised.value.file, raised.value.line, raised.value.column) == (
        "a.yaml",
        4,
        6 + len("w in "),
    )


def test_a_bad_key_expression_fails_when_the_repeater_is_compiled():
    with pytest.raises(TelSyntaxError):
        rep(key="w +")
    with pytest.raises(TelSyntaxError) as raised:
        rep(key="")
    assert raised.value.code == "empty-expression"


# -- the layered scope ----------------------------------------------------------------------------


def test_the_item_scope_binds_the_item_over_the_parent_and_falls_through_to_it():
    (item,) = rep("w in xs", "w").items(scope(xs=[5]))
    parent = scope(w=1, other=2)
    child = item.scope(parent)
    assert child.lookup("w") == 5 and child.lookup("other") == 2
    with pytest.raises(KeyError):
        child.lookup("nope")
    assert parent.lookup("w") == 1  # the parent is untouched
    assert sorted(child.names()) == ["other", "w"]


def test_children_compile_as_ordinary_expressions_in_the_item_scope():
    (item,) = rep().items(scope(workspaces=[{"id": 7, "name": "seven"}]))
    child = tel.compile_expression("w.name + suffix", language="0.1")
    assert child.evaluate(item.scope(scope(suffix="!"))) == "seven!"


def test_tracked_reads_through_the_item_are_reported_as_written():
    (item,) = rep().items(scope(workspaces=[{"id": 7, "name": "seven"}]))
    child = tel.compile_expression("w.name", language="0.1")
    assert child.evaluate_tracked(item.scope(scope())).reads == {"w.name"}


def test_a_parent_without_lookup_is_a_type_error_that_says_so():
    (item,) = rep("w in xs", "w").items(scope(xs=[1]))
    with pytest.raises(TypeError, match="lookup"):
        item.scope(object())
    with pytest.raises(TypeError, match="lookup"):
        rep().items(object())


def test_the_names_of_a_parent_without_names_is_just_the_item():
    class Bare:
        def lookup(self, name):
            raise KeyError(name)

    (item,) = rep("w in xs", "w").items(scope(xs=[1]))
    assert list(item.scope(Bare()).names()) == ["w"]


# -- limits ---------------------------------------------------------------------------------------


def test_a_list_over_max_sequence_is_a_limit_error_before_any_key_is_made():
    asked = []
    r = rep(
        "w in xs",
        "f(w)",
        functions={"f": lambda w: asked.append(w) or w},
        limits=Limits(max_sequence=10),
    )
    with pytest.raises(TelLimitError) as raised:
        r.items(scope(xs=list(range(11))))
    assert raised.value.code == "limit-sequence"
    assert asked == []
    assert len(r.items(scope(xs=list(range(10))))) == 10  # at the limit is fine


def test_the_list_and_all_the_keys_share_one_step_budget():
    r = rep("w in xs", "(w, sum(range(10)))", limits=Limits(max_steps=100))  # a key costs ~10 steps
    assert len(r.items(scope(xs=list(range(5))))) == 5
    with pytest.raises(TelLimitError) as raised:
        r.items(scope(xs=list(range(20))))  # each key is within the budget; together they are not
    assert raised.value.code == "limit-steps"


def test_a_list_too_long_for_the_budget_is_refused_before_any_key_is_made():
    asked = []
    r = rep("w in xs", "f(w)", functions={"f": lambda w: asked.append(w) or w})
    with pytest.raises(TelLimitError) as raised:
        r.items(scope(xs=list(range(300_000))))  # over the default 200,000 steps
    assert raised.value.code == "limit-steps" and asked == []
    assert (raised.value.line, raised.value.column) == (1, 1)


def test_a_costly_key_over_a_long_list_ends_as_a_limit_error_in_reasonable_time():
    r = rep("w in xs", "(w, sum(range(100000)))")
    start = time.perf_counter()
    with pytest.raises(TelLimitError) as raised:
        r.items(scope(xs=list(range(100_000))))  # each key alone is within the budget
    assert raised.value.code == "limit-steps"
    assert time.perf_counter() - start < CEILING


def test_the_step_budget_is_per_call_not_kept_between_calls():
    r = rep("w in xs", "(w, sum(range(10)))", limits=Limits(max_steps=100))
    for _ in range(3):
        assert len(r.items(scope(xs=list(range(5))))) == 5


def test_a_long_list_of_keys_is_made_in_reasonable_time():
    r = rep("w in range(50000)", "w")
    start = time.perf_counter()
    assert len(r.items(scope())) == 50000
    assert time.perf_counter() - start < CEILING


# -- the object -----------------------------------------------------------------------------------


def test_the_name_must_be_a_public_identifier():
    for bad in ("", "1a", "a b", "class", "_x", "a-b"):
        with pytest.raises(ValueError):
            rep(name=bad)
    for bad in (None, 3):
        with pytest.raises(TypeError):
            rep(name=bad)
    assert rep(name="Workspace").name == "Workspace"
    assert rep(name="é_1").name == "é_1"


def test_the_key_and_the_name_are_required_keywords():
    with pytest.raises(TypeError):
        tel.compile_repeater("w in xs", language="0.1", name="W")
    with pytest.raises(TypeError):
        tel.compile_repeater("w in xs", key="w", language="0.1")


def test_the_host_registrations_the_limits_and_the_version_carry_over():
    r = rep("w in xs", "double(w)", functions={"double": lambda n: n * 2})
    assert keys(r, xs=[1, 2]) == [2, 4]
    with pytest.raises(tel.TelVersionError):
        tel.compile_repeater("w in xs", key="w", name="W", language="9.9")
    with pytest.raises(TelLimitError) as raised:
        tel.compile_repeater(
            "w in xs", key="w", name="W", language="0.1", limits=Limits(max_source=1)
        )
    assert raised.value.code == "limit-source"


def test_arguments_of_the_wrong_type_are_type_errors():
    with pytest.raises(TypeError):
        tel.compile_repeater(5, key="w", name="W", language="0.1")
    with pytest.raises(TypeError):
        tel.compile_repeater("w in xs", key=5, name="W", language="0.1")
    with pytest.raises(TypeError):
        tel.compile_repeater("w in xs", key="w", name="W", language="0.1", origin="x")
    with pytest.raises(TypeError):
        tel.compile_repeater("w in xs", key="w", name="W", language="0.1", key_origin="x")


def test_a_repeater_and_an_item_are_immutable_and_cannot_be_pickled():
    r = rep()
    (item,) = r.items(scope(workspaces=WS[:1]))
    for obj in (r, item):
        with pytest.raises(AttributeError):
            obj.name = "x"
        with pytest.raises(AttributeError):
            del obj.name
        with pytest.raises(TypeError):
            pickle.dumps(obj)
        assert copy.copy(obj) is obj and copy.deepcopy(obj) is obj
    assert isinstance(r, Repeater)
    assert repr(r) == "Repeater('w in workspaces', key='w.id')"


def test_an_item_and_an_entry_are_tuples_with_value_equality_and_no_dict():
    r = rep()
    (item,) = r.items(scope(workspaces=WS[:1]))
    (entry,) = r.reconcile(scope(workspaces=WS[:1]), tel.RepeaterState()).entries
    assert (len(item), len(entry)) == (4, 6)
    assert item[:3] == (item.index, item.key, item.value)
    assert entry[4:] == (entry.name, entry.status)
    assert isinstance(entry, tel.Item) and not hasattr(entry, "__dict__")
    with pytest.raises(AttributeError):
        entry.status = "new"


def test_the_header_keeps_its_text():
    assert rep("  w in xs ").header == "  w in xs "


def test_a_list_that_does_not_read_as_an_expression_is_a_syntax_error_not_a_header_error():
    with pytest.raises(TelSyntaxError) as raised:
        rep("w in xs for q in ys")
    assert raised.value.code == "syntax-error"


def test_two_underscores_are_two_throwaway_names_and_not_a_repeat():
    assert rep("_, _ in xs", "1").targets == ("_", "_")
    with pytest.raises(TelSyntaxError):
        rep("_, a, a in xs")


def test_a_header_error_has_the_span_of_what_is_wrong():
    with pytest.raises(TelSyntaxError) as raised:
        rep("  a, a in xs")
    assert (raised.value.column, raised.value.end_column) == (6, 7)
    with pytest.raises(TelSyntaxError) as raised:
        rep("(a, b) in xs")
    assert (raised.value.column, raised.value.end_column) == (1, 7)


def test_a_key_error_spans_the_key_on_one_line_and_not_on_several():
    with pytest.raises(TelEvaluationError) as raised:
        rep("w in xs", "1.5").items(scope(xs=[1]))
    assert (raised.value.column, raised.value.end_column) == (1, 4)
    with pytest.raises(TelEvaluationError) as raised:
        rep("w in xs", "(\n1.5)").items(scope(xs=[1]))
    assert raised.value.end_column is None


def test_the_key_gets_the_limits_and_the_methods_too():
    with pytest.raises(TelLimitError) as raised:
        rep("w in xs", "ab", limits=Limits(max_source=1))
    assert raised.value.code == "limit-source"

    class Price:
        pass

    r = rep("w in xs", "w.tag()", methods={Price: {"tag": lambda p: "t"}})
    assert keys(r, xs=[Price()]) == ["t"]


def test_a_tuple_subclass_is_not_a_key_and_names_its_type():
    class Pair(tuple):
        pass

    with pytest.raises(TelEvaluationError) as raised:
        rep("w in xs", "w").items(scope(xs=[Pair((1, 2))]))
    assert raised.value.code == "bad-key-type" and "Pair" in raised.value.message


def test_an_unpack_error_says_what_the_item_has():
    with pytest.raises(TelEvaluationError) as raised:
        rep("a, b in xs", "a").items(scope(xs=[(1, 2, 3)]))
    assert "3 values" in raised.value.message
    with pytest.raises(TelEvaluationError) as raised:
        rep("a, b in xs", "a").items(scope(xs=[5]))
    assert "int" in raised.value.message


def test_the_names_of_the_item_scope_are_not_listed_twice():
    (item,) = rep("w in xs", "w").items(scope(xs=[1]))
    assert sorted(item.scope(scope(w=2, z=3)).names()) == ["w", "z"]


def test_a_header_error_over_several_lines_is_not_underlined():
    with pytest.raises(TelSyntaxError) as raised:
        rep("(a,\n b) in xs")
    assert (raised.value.line, raised.value.column, raised.value.end_column) == (1, 1, None)


def test_the_parts_of_a_tuple_key_are_plain_too():
    class Name(str):
        def __hash__(self):
            raise RuntimeError("host code ran")

    (key,) = keys(rep("w in xs", "(w, 1)"), xs=[Name("a")])
    assert key == ("a", 1) and type(key[0]) is str


def test_the_language_version_is_checked_before_the_header_is_read():
    with pytest.raises(tel.TelVersionError):
        tel.compile_repeater("", key="", name="", language="9.9")


def test_a_path_read_in_the_list_and_in_the_key_uses_the_right_scope():
    class Box:
        rows = [{"id": 5}]

    r = rep("w in box.rows", "w.id + off.n")
    assert keys(r, box=Box(), off=type("O", (), {"n": 1})()) == [6]


def test_a_stack_overflow_while_evaluating_is_a_depth_error_in_the_list_and_in_the_key():
    for header, key in (("w in " + "-" * 30 + "1", "w"), ("w in xs", "-" * 30 + "1")):
        r = rep(header, key)
        old = sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(len(inspect.stack()) + 25)
            with pytest.raises(TelLimitError) as raised:
                r.items(scope(xs=[1]))
        finally:
            sys.setrecursionlimit(old)
        assert raised.value.code == "limit-depth"


def test_each_item_costs_a_step_and_the_budget_is_exact():
    r = rep("w in xs", "w", limits=Limits(max_steps=100))
    assert len(r.items(scope(xs=list(range(100))))) == 100
    with pytest.raises(TelLimitError) as raised:
        r.items(scope(xs=list(range(101))))
    assert raised.value.code == "limit-steps"


def test_a_misspelt_loop_variable_in_the_key_is_given_a_hint_from_the_item_scope():
    with pytest.raises(TelEvaluationError) as raised:
        rep("w in xs", "ww").items(scope(xs=[1]))
    assert raised.value.code == "unknown-name" and "'w'" in (raised.value.hint or "")


def test_a_misspelt_name_in_the_list_is_given_a_hint_from_the_host_scope():
    with pytest.raises(TelEvaluationError) as raised:
        rep("w in workspace", "w").items(scope(workspaces=[1]))
    assert raised.value.code == "unknown-name" and "workspaces" in (raised.value.hint or "")


def test_a_header_over_max_source_is_refused_whole_before_it_is_read():
    limits = Limits(max_source=20)
    rep("w in xs", "w", limits=limits)
    assert len("w in " + "x" * 15) == 20
    rep("w in " + "x" * 15, "w", limits=limits)  # exactly at the limit is fine
    with pytest.raises(TelLimitError) as raised:
        rep("w in " + "x" * 16, "w", limits=limits)
    assert raised.value.code == "limit-source"
    with pytest.raises(TelLimitError) as raised:
        rep("w in " + "x" * 20, "w", limits=limits)
    assert raised.value.code == "limit-source"
    with pytest.raises(TelLimitError) as raised:
        rep("a" + ", a" * 20, "w", limits=limits)  # a bad header too: the size comes first
    assert raised.value.code == "limit-source"


def test_a_huge_bad_header_is_refused_in_reasonable_time():
    huge = Limits(max_source=10**8)
    for header in ("a" + " , a" * 200_000, "a " * 1_000_000, "  " * 1_000_000 + "a"):
        start = time.perf_counter()
        with pytest.raises(TelSyntaxError):
            rep(header, "w", limits=huge)
        assert time.perf_counter() - start < CEILING


# -- the sandbox rules apply to the header, the key and a condition alike -------------------------

ESCAPES = [
    "().__class__.__bases__",
    "w.__class__",
    "__import__('os')",
    "open('/etc/passwd')",
    "(lambda: 1)()",
    "[c for c in ().__class__.__subclasses__()]",
    "'{0.__class__}'.format(w)",
    "getattr(w, 'x')",
    "eval('1')",
    "w := 1",
    "2 ** 99999",
    "w if w else (yield)",
]


@pytest.mark.parametrize("text", ESCAPES)
def test_an_escape_is_refused_in_the_list_the_key_and_a_condition(text):
    for build in (
        lambda: rep("w in " + text, "w"),
        lambda: rep("w in xs", text),
        lambda: tel.compile_condition(text, language="0.1"),
    ):
        with pytest.raises((TelSyntaxError, TelLimitError)) as raised:
            build()
        assert raised.value.line is not None or raised.value.code.startswith("limit-")


def test_an_escape_through_a_host_object_item_does_not_get_out_of_the_scope():
    class Host:
        secret = "s"

        def _private(self):
            return 1

    r = rep("w in xs", "w.secret")
    assert keys(r, xs=[Host()]) == ["s"]
    for text in ("w._private", "w.secret.__class__", "w.__dict__"):
        with pytest.raises(TelSyntaxError) as raised:
            rep("w in xs", text)
        assert raised.value.code in {"private-attribute", "private-name"}


def test_a_list_and_a_key_with_several_loop_variables_have_the_slots_they_need():
    r = rep(
        "w in [a * 10 + b for a in range(2) for b in range(3)]",
        "sum([x + y for x in range(2) for y in range(3)]) + w",
    )
    assert keys(r) == [9, 10, 11, 19, 20, 21]
