"""Name tracking (step 4, phase 2): which names an evaluation actually read."""

import pickle
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from reference import cases
from reference.expectations import DROPPED_HELPER_CASES

import tel
from tel import MapScope, TelError, Tracked


def build(text, **kw):
    return tel.compile_expression(text, language="0.1", **kw)


def tracked(text, **values):
    return build(text).evaluate_tracked(MapScope(values))


class Recording(MapScope):
    """An independent oracle: a scope that writes down every name it is asked for."""

    __slots__ = ("asked",)

    def __init__(self, values):
        super().__init__(values)
        self.asked = set()

    def lookup(self, name):
        self.asked.add(name)
        return super().lookup(name)


# -- what reads holds -----------------------------------------------------------------------------


def test_the_result_is_a_value_and_a_frozenset_of_names():
    result = tracked("count + 1", count=2)
    assert isinstance(result, Tracked) and result == (3, frozenset({"count"}))
    value, reads = result
    assert value == 3 and type(reads) is frozenset
    assert (Tracked._fields, result.value, result.reads) == (("value", "reads"), 3, {"count"})


@pytest.mark.parametrize(
    "source, scope, reads",
    [
        ("1 + 2", {}, set()),
        ("x", {"x": 1}, {"x"}),
        ("x + x * x", {"x": 2}, {"x"}),
        ("a + b", {"a": 1, "b": 2}, {"a", "b"}),
        ("len(items)", {"items": [1]}, {"items"}),
        ("sum(i for i in items)", {"items": [1]}, {"items"}),
        ("[i * k for i in items]", {"items": [1], "k": 2}, {"items", "k"}),
        ("[x for x in x]", {"x": [1]}, {"x"}),
        ("[y for x in xs for y in x]", {"xs": [[1]]}, {"xs"}),
        ("{k: v for k, v in d.items()}", {"d": {"a": 1}}, {"d"}),
        ("ws.name", {"ws": {"name": "n"}}, {"ws"}),
        ("d['k'] + items[0]", {"d": {"k": 1}, "items": [1]}, {"d", "items"}),
        ("f'{a} and {b}'", {"a": 1, "b": 2}, {"a", "b"}),
        ("name.upper()", {"name": "ada"}, {"name"}),
        ("max(a, b, key_default)", {"a": 1, "b": 2, "key_default": 3}, {"a", "b", "key_default"}),
    ],
)
def test_the_names_an_evaluation_asked_the_scope_for(source, scope, reads):
    assert tracked(source, **scope).reads == reads


# -- reads can be fewer than the names in the text ------------------------------------------------


@pytest.mark.parametrize("flag, reads", [(True, {"flag", "a"}), (False, {"flag", "b"})])
def test_a_conditional_reads_only_the_branch_it_takes(flag, reads):
    expr = build("a if flag else b")
    assert expr.names == {"a", "b", "flag"}
    assert expr.evaluate_tracked(MapScope({"flag": flag, "a": 1, "b": 2})).reads == reads


@pytest.mark.parametrize(
    "source, scope, reads",
    [
        ("x or y", {"x": 1, "y": 2}, {"x"}),
        ("x or y", {"x": 0, "y": 2}, {"x", "y"}),
        ("x and y", {"x": 0, "y": 2}, {"x"}),
        ("x and y", {"x": 1, "y": 2}, {"x", "y"}),
        ("a < b < c", {"a": 2, "b": 1, "c": 9}, {"a", "b"}),
        ("a < b < c", {"a": 1, "b": 2, "c": 9}, {"a", "b", "c"}),
        ("[v for v in items if v > lo]", {"items": [], "lo": 0}, {"items"}),
        ("[v for v in items if v > lo]", {"items": [1], "lo": 0}, {"items", "lo"}),
        ("a if p else (b if q else c)", {"p": 0, "q": 1, "a": 1, "b": 2, "c": 3}, {"p", "q", "b"}),
    ],
)
def test_short_circuit_and_empty_loops_read_less_than_the_text_names(source, scope, reads):
    assert tracked(source, **scope).reads == reads


def test_reads_of_a_constant_expression_are_empty_and_its_names_say_so():
    for source in ("2 * 60", "'x'.upper()", "[i for i in range(3)]", "len('abc') + 1"):
        expr = build(source)
        assert expr.names == frozenset() and expr.evaluate_tracked(MapScope()).reads == frozenset()


def test_the_value_is_the_one_evaluate_gives():
    scope = MapScope({"x": 3, "items": [1, 2, 3]})
    for source in ("x + 1", "[i * x for i in items]", "f'{x:03d}'", "x if x > 5 else items"):
        expr = build(source)
        assert expr.evaluate_tracked(scope).value == expr.evaluate(scope)


# -- an oracle: every reference case, against a scope that writes down what it is asked ------------


@pytest.mark.parametrize(
    "source, expected",
    [c for c in cases.ALLOWED if c[0] not in DROPPED_HELPER_CASES],
    ids=[c[0] for c in cases.ALLOWED if c[0] not in DROPPED_HELPER_CASES],
)
def test_the_reads_of_every_allowed_case_are_what_the_scope_was_asked_for(source, expected):
    expr = build(source)
    oracle = Recording(cases.SCOPE_VALUES)
    expr.evaluate(oracle)
    result = expr.evaluate_tracked(MapScope(cases.SCOPE_VALUES))
    assert result.value == expected and result.reads == oracle.asked
    assert result.reads <= expr.names


# -- a name that is not there ---------------------------------------------------------------------


def test_a_missing_name_is_read_and_is_on_the_error():
    with pytest.raises(TelError) as raised:
        build("a + b + nme").evaluate_tracked(MapScope({"a": 1, "b": 2, "name": 3}))
    error = raised.value
    assert error.code == "unknown-name" and error.reads == {"a", "b", "nme"}
    assert type(error.reads) is frozenset


def test_reads_are_on_every_kind_of_error():
    scope = MapScope({"x": "a", "n": 10**30})
    for source, code in (
        ("x + 1", "bad-operand"),
        ("2 ** n", "limit-pow-exponent"),
        ("y", "unknown-name"),
    ):
        with pytest.raises(TelError) as raised:
            build(source).evaluate_tracked(scope)
        assert raised.value.code == code and raised.value.reads is not None


def test_a_plain_evaluation_leaves_reads_unknown():
    with pytest.raises(TelError) as raised:
        build("nme").evaluate(MapScope({"name": 1}))
    assert raised.value.reads is None


def test_errors_raised_before_any_evaluation_have_no_reads():
    with pytest.raises(TelError) as raised:
        build("__class__")
    assert raised.value.reads is None
    with pytest.raises(tel.TelVersionError) as raised:
        tel.compile_expression("x", language="9.9")
    assert raised.value.reads is None


def test_reads_survive_pickling_with_the_error():
    with pytest.raises(TelError) as raised:
        build("a + nme").evaluate_tracked(MapScope({"a": 1}))
    copy = pickle.loads(pickle.dumps(raised.value))
    assert copy.reads == {"a", "nme"} and copy.code == "unknown-name"


def test_an_exception_from_the_hosts_lookup_propagates_unchanged():
    class Broken:
        def lookup(self, name):
            raise RuntimeError("the host's own bug")

    with pytest.raises(RuntimeError, match="the host's own bug"):
        build("x").evaluate_tracked(Broken())


def test_a_scope_without_lookup_is_the_same_helpful_type_error():
    with pytest.raises(TypeError, match=r"lookup\(name\).*MapScope"):
        build("x").evaluate_tracked({"x": 1})


# -- the lookup the host sees ---------------------------------------------------------------------


def test_a_tracked_evaluation_asks_the_scope_exactly_as_a_plain_one_does():
    expr = build("a + a + [i for i in items][0]")
    calls = []

    class Counting(MapScope):
        __slots__ = ()

        def lookup(self, name):
            calls.append(name)
            return super().lookup(name)

    scope = Counting({"a": 1, "items": [5]})
    expr.evaluate(scope)
    plain_calls, calls[:] = list(calls), []
    expr.evaluate_tracked(scope)
    assert calls == plain_calls and plain_calls.count("a") == 2


def test_a_scope_may_evaluate_another_expression_and_the_reads_do_not_mix():
    inner = build("p + q")

    class Nested:
        def lookup(self, name):
            if name == "xs":
                return [inner.evaluate_tracked(MapScope({"p": 1, "q": 2})).value]
            return 5

    result = build("[x + y for x in xs for y in [one]]").evaluate_tracked(Nested())
    assert result.value == [8] and result.reads == {"xs", "one"}


def test_tracked_evaluations_on_many_threads_keep_their_own_reads():
    expr = build("a if flag else b")
    barrier = threading.Barrier(8)

    def work(k):
        barrier.wait()
        flag = k % 2 == 0
        return [
            (flag, expr.evaluate_tracked(MapScope({"flag": flag, "a": 1, "b": 2})).reads)
            for _ in range(300)
        ]

    with ThreadPoolExecutor(8) as pool:
        for results in pool.map(work, range(8)):
            for flag, reads in results:
                assert reads == ({"flag", "a"} if flag else {"flag", "b"})


# -- templates ------------------------------------------------------------------------------------


def template(text, **kw):
    return tel.compile_template(text, language="0.1", **kw)


def test_a_template_reads_the_union_of_what_its_parts_read():
    t = template("{{ a }} and {{ b if flag else c }} and {{ a }}")
    result = t.evaluate_tracked(MapScope({"a": 1, "b": 2, "c": 3, "flag": True}))
    assert result.value == "1 and 2 and 1" and result.reads == {"a", "b", "flag"}
    assert t.names == {"a", "b", "c", "flag"}


def test_a_template_that_is_exactly_one_part_keeps_the_type_of_its_value():
    result = template("{{ items }}").evaluate_tracked(MapScope({"items": [1, 2]}))
    assert result == ([1, 2], frozenset({"items"}))


def test_a_template_with_parts_that_read_nothing_reads_nothing():
    assert template("pi is {{ 3 }}").evaluate_tracked(MapScope()) == ("pi is 3", frozenset())


def test_an_error_in_a_template_part_carries_the_reads_so_far():
    with pytest.raises(TelError) as raised:
        template("{{ a }} {{ nme }} {{ c }}").evaluate_tracked(MapScope({"a": 1, "c": 3}))
    assert raised.value.code == "unknown-name" and raised.value.reads == {"a", "nme"}


def test_a_template_gives_the_same_text_tracked_or_not():
    t = template("Hello {{ name }}, {{ n + 1 }}")
    scope = MapScope({"name": "Ada", "n": 1})
    assert t.evaluate_tracked(scope).value == t.evaluate(scope)


def test_the_public_names_include_tracked():
    assert "Tracked" in tel.__all__
