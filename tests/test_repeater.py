"""Repeaters (step 5, phase 3): the header `item in items`, the key, and the items they give."""

import copy
import pickle
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
        ("w in xs for q in ys", None, None),
    ],
)
def test_a_header_that_is_not_names_in_an_expression_is_a_syntax_error(header, column, needle):
    with pytest.raises(TelSyntaxError) as raised:
        rep(header)
    error = raised.value
    assert error.code in {"repeater-header", "syntax-error"}
    if needle:
        assert error.code == "repeater-header" and needle in error.message
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


def test_each_key_has_its_own_step_budget():
    r = rep("w in xs", "(w, sum(range(w)))", limits=Limits(max_steps=100))
    assert keys(r, xs=[10, 11]) == [(10, 45), (11, 55)]
    with pytest.raises(TelLimitError) as raised:
        r.items(scope(xs=[10, 100000]))
    assert raised.value.code == "limit-steps"


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


def test_the_header_keeps_its_text():
    assert rep("  w in xs ").header == "  w in xs "
