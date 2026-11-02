"""A host object inside a container is carried, but nothing may call its methods (step 7).

`sum`, `min`, `max`, `sorted`, `any`, `all`, `set`, `dict`, `str`, a comparison, `in`, a value in
text and `.index` / `.count` would call `__radd__`, `__lt__`, `__bool__`, `__hash__`, `__eq__` or
`__repr__` of an element. They refuse a container with a host object inside it instead
(`docs/language.md`, 12.2 clause 4). Reading an attribute, a length, an index or a loop is fine.
"""

import time

import pytest
from reference.support import Plain, Trap

import tel
from tel import Limits, MapScope, TelError
from tel._values import TooMany, foreign_inside

CEILING = 0.5


def scope(**extra):
    values = {
        "ws": [Plain(), Plain()],
        "trap": Trap(),
        "nums": [3, 1, 2],
        "words": ["b", "a"],
        "mixed": [1, "a", None, 2.5, True],
        "nested": [[1, 2], [3, [4, (5, "x")]]],
        "d": {"k": 1, "j": [1, 2]},
        "hosts": {"k": Plain()},
        "keyed": {Trap(): 1},
    }
    values.update(extra)
    return MapScope(values)


def run(text, **extra):
    values = scope(**extra)  # building the scope hashes its own `Trap` key: not the test
    Trap.tripped.clear()
    try:
        return tel.compile_expression(text, language="0.1").evaluate(values)
    finally:
        assert Trap.tripped == [], text


def refused(text, **extra):
    with pytest.raises(TelError) as raised:
        run(text, **extra)
    assert raised.value.code == "value-not-plain", text
    return raised.value


# -- what is refused ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "sum(ws)",
        "max(ws)",
        "min(ws)",
        "sorted(ws)",
        "any(ws)",
        "all(ws)",
        "set(ws)",
        "dict(hosts)",
        "str(ws)",
        "str(hosts)",
        "f'{ws}'",
        "f'{hosts!r}'",
        "ws == ws",
        "ws != ws",
        "ws < ws",
        "hosts == hosts",
        "1 in ws",
        "1 not in ws",
        "ws.index(1)",
        "ws.count(1)",
        "[ws] == [ws]",
        "[[ws]] < [[ws]]",
        "sum([[trap]][0])",
        "max([ws, ws])",
        "(trap,) == (1,)",
        "{'a': [trap]} == {'a': [1]}",
        "ws in [ws]",
    ],
)
def test_an_operation_that_would_call_a_host_objects_methods_is_refused(text):
    refused(text)


def test_a_host_object_on_its_own_keeps_its_own_message_in_text_and_in_a_comparison():
    assert refused("f'{trap}'").message.startswith("a Trap cannot be used in text")
    assert refused("trap == 1").message.startswith("a Trap cannot be used in a comparison")
    assert refused("1 < trap").message.startswith("a Trap cannot be used in a comparison")
    assert refused("sum([trap])").message.startswith("a Trap cannot be used inside a value")


def test_the_message_names_the_host_object_and_the_operation():
    error = refused("sum(ws)")
    assert "Plain" in error.message and "sum()" in error.message
    assert (error.line, error.column) == (1, 1)
    assert "Plain" in refused("ws == ws").message
    assert "Trap" in refused("str([trap])").message


def test_the_check_looks_through_nested_lists_tuples_sets_and_dict_keys_and_values():
    for value in (
        [[Plain()]],
        ([1], (2, (Plain(),))),
        {"a": {"b": [Plain()]}},
        {Plain(): 1},
        [{"k": (Plain(),)}],
    ):
        refused("str(v)", v=value)
        refused("v == v", v=value)
    refused("set(v)", v=frozenset({Plain()}))


def test_a_cycle_ends_and_a_shared_container_is_looked_at_once():
    loop = [1]
    loop.append(loop)
    assert run("v == v", v=loop) is True  # a cycle of plain values is compared by Python as it is
    shared = [Plain()]
    refused("str(v)", v=[shared, shared, shared])
    assert foreign_inside([1, loop], 100) is None
    ring: dict = {}
    ring["k"] = ring
    assert foreign_inside(ring, 100) is None  # not "too many": the dict is looked at once
    both: list = []
    both.append({"k": both})
    assert foreign_inside(both, 100) is None
    assert foreign_inside(range(5), 100) is None


# -- what is not refused --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("sum(nums)", 6),
        ("max(nums)", 3),
        ("sorted(nums)", [1, 2, 3]),
        ("sorted(words)", ["a", "b"]),
        ("any(nums)", True),
        ("set(nums) == {1, 2, 3}", True),
        ("dict(d) == d", True),
        ("str(nested)", "[[1, 2], [3, [4, (5, 'x')]]]"),
        ("f'{mixed}'", "[1, 'a', None, 2.5, True]"),
        ("nums == [3, 1, 2]", True),
        ("3 in nums", True),
        ("nums.index(2)", 2),
        ("nums.count(1)", 1),
        ("d == {'k': 1, 'j': [1, 2]}", True),
        ("len(ws)", 2),
        ("[w.title for w in ws]", ["t", "t"]),
        ("ws[0].title", "t"),
        ("len(list(ws)) == 2", True),
        ("[len(ws), ws[1].items]", [2, [1, 2]]),
        ("{'k': ws}['k'][0].title", "t"),
        ("sum([w.items[0] for w in ws])", 2),
    ],
)
def test_plain_containers_and_reading_the_elements_of_a_host_list_are_fine(text, expected):
    assert run(text) == expected


def test_a_comparison_of_host_objects_that_is_not_a_container_is_refused_as_before():
    with pytest.raises(TelError) as raised:
        run("ws[0] == ws[1]")
    assert raised.value.code == "value-not-plain"


# -- the helper -----------------------------------------------------------------------------------


def test_foreign_inside_gives_the_first_host_object_or_none():
    host = Plain()
    assert foreign_inside([1, [2, (3, host)]], 100) is host
    assert foreign_inside({"a": host}, 100) is host
    assert foreign_inside({host: 1}, 100) is host
    assert foreign_inside([1, 2.5, "a", None, True, range(3), (1,), {1: 2}, {3}], 100) is None
    assert foreign_inside("text", 100) is None
    assert foreign_inside([], 100) is None


def test_foreign_inside_does_not_run_any_method_of_a_subclass():
    def boom(*_):
        raise RuntimeError("host code ran")

    class Rows(list):
        __iter__ = __len__ = __eq__ = __repr__ = boom  # type: ignore[assignment]

    class Pair(tuple):
        __iter__ = __len__ = boom  # type: ignore[assignment]

    class Bag(dict):
        keys = values = items = __iter__ = __len__ = boom  # type: ignore[assignment]

    class Chosen(set):
        __iter__ = __len__ = boom  # type: ignore[assignment]

    class Frozen(frozenset):
        __iter__ = __len__ = boom  # type: ignore[assignment]

    host = Plain()
    assert foreign_inside(Rows([1, host]), 100) is host
    assert foreign_inside(Pair((host,)), 100) is host
    assert foreign_inside(Bag({"k": host}), 100) is host
    assert foreign_inside(Rows([1, 2]), 100) is None
    assert foreign_inside(Chosen({host}), 100) is host
    assert foreign_inside(Frozen({host}), 100) is host
    assert foreign_inside(Chosen({1, 2}), 100) is None


def test_foreign_inside_stops_after_the_allowed_number_of_elements():
    assert foreign_inside(list(range(10)), 10) is None
    with pytest.raises(TooMany):
        foreign_inside(list(range(11)), 10)
    with pytest.raises(TooMany):
        foreign_inside([[1] * 6, [2] * 6], 10)


def test_a_huge_container_is_a_step_limit_error_before_it_is_checked_whole():
    big = list(range(300_000))
    start = time.perf_counter()
    with pytest.raises(TelError) as raised:
        tel.compile_expression("str(v)", language="0.1").evaluate(scope(v=[big]))
    assert raised.value.code == "limit-steps"
    assert time.perf_counter() - start < CEILING
    ok = tel.compile_expression("len(str(v))", language="0.1", limits=Limits(max_steps=10**6))
    assert ok.evaluate(scope(v=[1, 2])) == 6
