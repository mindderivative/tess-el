"""The scope contract (step 4, phase 4): one test group per clause of docs/language.md section 12.2.

What a host may rely on when it hands TEL a scope, and what TEL may rely on from the host. Every
clause is checked on plain evaluation, tracked evaluation and templates where they differ.
"""

import threading

import pytest

import tess_el
from tess_el import MapScope, TelError


def build(text, **kw):
    return tess_el.compile_expression(text, language="0.1", **kw)


def template(text, **kw):
    return tess_el.compile_template(text, language="0.1", **kw)


def runners(source):
    """The same expression through every way of evaluating it."""
    expr = build(source)
    tmpl = template("{{ " + source + " }}")
    return [
        expr.evaluate,
        lambda scope: expr.evaluate_tracked(scope).value,
        tmpl.evaluate,
        lambda scope: tmpl.evaluate_tracked(scope).value,
    ]


class Logging:
    """A scope that writes down every name it is asked for."""

    def __init__(self, values, log=None):
        self.values, self.asked = values, [] if log is None else log

    def lookup(self, name):
        self.asked.append(name)
        return self.values[name]


# -- clause 1: KeyError is "unknown name", anything else is the host's bug ------------------------


@pytest.mark.parametrize("run", runners("x"), ids=["plain", "tracked", "template", "tmpl-tracked"])
def test_clause_1_key_error_is_an_unknown_name(run):
    with pytest.raises(TelError) as raised:
        run(MapScope({"y": 1}))
    assert raised.value.code == "unknown-name"


@pytest.mark.parametrize("run", runners("x"), ids=["plain", "tracked", "template", "tmpl-tracked"])
@pytest.mark.parametrize("exc", [RuntimeError("boom"), ValueError("v"), AttributeError("a")])
def test_clause_1_any_other_exception_propagates_unchanged(run, exc):
    class Broken:
        def lookup(self, name):
            raise exc

    with pytest.raises(type(exc)) as raised:
        run(Broken())
    assert raised.value is exc


def test_clause_1_a_key_error_subclass_is_still_an_unknown_name():
    class Missing(KeyError):
        pass

    class Scope:
        def lookup(self, name):
            raise Missing(name)

    with pytest.raises(TelError) as raised:
        build("x").evaluate(Scope())
    assert raised.value.code == "unknown-name"


# -- clause 2: asked any number of times, in any order, never cached ------------------------------


def test_clause_2_the_same_name_is_asked_every_time_it_is_used():
    scope = Logging({"a": 1})
    assert build("a + a + a").evaluate(scope) == 3
    assert scope.asked == ["a", "a", "a"]


def test_clause_2_a_name_the_expression_does_not_use_is_never_asked():
    scope = Logging({"a": 1, "b": 2, "c": 3})
    build("a + 1").evaluate(scope)
    assert scope.asked == ["a"]


def test_clause_2_nothing_is_cached_between_evaluations_or_within_one():
    class Counter:
        n = 0

        def lookup(self, name):
            self.n += 1
            return self.n

    assert build("a + a").evaluate(Counter()) == 1 + 2
    scope = Counter()
    expr = build("a")
    assert [expr.evaluate(scope) for _ in range(3)] == [1, 2, 3]


def test_clause_2_the_order_is_the_order_of_evaluation_not_the_order_of_the_text():
    scope = Logging({"a": 1, "b": 2, "c": 3})
    build("a if c > b else b").evaluate(scope)
    assert scope.asked == ["c", "b", "a"]


def test_clause_2_a_tracked_evaluation_asks_exactly_what_a_plain_one_asks():
    for source in ("a + a", "a if b else c", "[x for x in xs if x > t]", "p.q + p.r"):
        values = {"a": 1, "b": True, "c": 2, "xs": [1, 2], "t": 0, "p": {"q": 1, "r": 2}}
        plain, tracked = Logging(values), Logging(values)
        build(source).evaluate(plain)
        build(source).evaluate_tracked(tracked)
        assert plain.asked == tracked.asked, source


# -- clause 3: quick, no effect, re-entrant -------------------------------------------------------


def test_clause_3_only_what_the_expression_needs_is_asked_under_short_circuit():
    scope = Logging({"flag": False, "a": 1, "b": 2})
    assert build("flag and a").evaluate(scope) is False
    assert scope.asked == ["flag"]
    scope = Logging({"flag": True, "a": 1, "b": 2})
    assert build("flag or a").evaluate(scope) is True
    assert scope.asked == ["flag"]
    scope = Logging({"flag": True, "a": 1, "b": 2})
    assert build("a if flag else b").evaluate(scope) == 1
    assert scope.asked == ["flag", "a"]


def test_clause_3_a_lookup_may_evaluate_another_expression_with_the_same_one():
    inner = build("n * 2")
    outer = build("m + 1")

    class Reentrant:
        def lookup(self, name):
            if name == "m":
                return inner.evaluate(MapScope({"n": 20}))
            raise KeyError(name)

    assert outer.evaluate(Reentrant()) == 41


def test_clause_3_a_lookup_may_evaluate_the_expression_that_is_asking():
    expr = build("a + 1")
    depth = []

    class Self:
        def lookup(self, name):
            depth.append(name)
            if len(depth) < 3:
                return expr.evaluate(self)
            return 0

    assert expr.evaluate(Self()) == 3


def test_clause_3_a_tracked_evaluation_inside_a_lookup_keeps_its_own_reads():
    inner = build("n + o")
    outer = build("m + k")
    seen = []

    class Reentrant:
        def lookup(self, name):
            if name == "m":
                tracked = inner.evaluate_tracked(MapScope({"n": 1, "o": 2}))
                seen.append(tracked.reads)
                return tracked.value
            return 10

    value, reads = outer.evaluate_tracked(Reentrant())
    assert value == 13 and reads == {"m", "k"} and seen == [{"n", "o"}]


def test_clause_3_a_lookup_called_from_many_threads_gets_one_call_per_use():
    expr = build("a + b")
    lock, asked = threading.Lock(), []

    class Safe:
        def lookup(self, name):
            with lock:
                asked.append(name)
            return 1

    barrier = threading.Barrier(8)

    def work():
        barrier.wait()
        for _ in range(200):
            assert expr.evaluate(Safe()) == 2

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(asked) == 8 * 200 * 2


# -- clause 4: plain values, and what happens to a value that is not ------------------------------


class Thing:
    """Not a plain value: its operators carry the host's code, which must never run."""

    label = "thing"
    size = 3

    def __init__(self):
        self.hits = []

    def _hit(self, what):
        self.hits.append(what)
        return 1

    def __add__(self, other):
        return self._hit("add")

    def __radd__(self, other):
        return self._hit("radd")

    def __eq__(self, other):
        self._hit("eq")
        return True

    __hash__ = object.__hash__

    def __bool__(self):
        self._hit("bool")
        return True

    def __len__(self):
        return self._hit("len")

    def __getitem__(self, key):
        return self._hit("getitem")

    def __iter__(self):
        self._hit("iter")
        return iter([])

    def __format__(self, spec):
        self._hit("format")
        return "x"

    def __str__(self):
        self._hit("str")
        return "x"


def test_clause_4_an_attribute_of_a_value_that_is_not_plain_can_be_read():
    thing = Thing()
    assert build("t.label").evaluate(MapScope({"t": thing})) == "thing"
    assert build("t.size + 1").evaluate(MapScope({"t": thing})) == 4
    assert thing.hits == []


@pytest.mark.parametrize(
    "source",
    ["t + 1", "1 + t", "t == 1", "t[0]", "len(t)", "str(t)", "[i for i in t]", "1 in t"],
)
def test_clause_4_no_operator_function_or_test_touches_a_value_that_is_not_plain(source):
    thing = Thing()
    with pytest.raises(TelError):
        build(source).evaluate(MapScope({"t": thing}))
    assert thing.hits == []


def test_clause_4_a_value_that_is_not_plain_is_true_and_its_bool_never_runs():
    thing = Thing()
    scope = MapScope({"t": thing})
    assert build("not t").evaluate(scope) is False
    assert build("1 if t else 2").evaluate(scope) == 1
    assert thing.hits == []


def test_clause_4_a_value_that_is_not_plain_can_be_returned_untouched():
    thing = Thing()
    assert build("t").evaluate(MapScope({"t": thing})) is thing
    assert build("t if True else 0").evaluate(MapScope({"t": thing})) is thing
    assert thing.hits == []


def test_clause_4_a_template_does_not_format_a_value_that_is_not_plain():
    thing = Thing()
    with pytest.raises(TelError):
        template("a {{ t }}").evaluate(MapScope({"t": thing}))
    assert thing.hits == []


def _function(): ...


@pytest.mark.parametrize("value", [_function, Thing, len, Thing().__add__], ids=str)
def test_clause_4_a_function_or_class_in_a_scope_is_a_value_and_nothing_else(value):
    scope = MapScope({"f": value})
    assert build("f").evaluate(scope) is value
    for source in ("f()", "f.__name__", "f.x", "f + 1", "f == f"):
        with pytest.raises(TelError):
            build(source).evaluate(scope)


# -- clause 5: names() is optional and only builds a hint -----------------------------------------


def test_clause_5_a_scope_without_names_works_and_the_error_has_no_hint():
    scope = Logging({"count": 1})
    assert build("count").evaluate(scope) == 1
    with pytest.raises(TelError) as raised:
        build("cout").evaluate(scope)
    assert raised.value.code == "unknown-name" and raised.value.hint is None


def test_clause_5_names_is_not_called_unless_an_error_needs_a_hint():
    calls = []

    class Counting(MapScope):
        __slots__ = ()

        def names(self):
            calls.append("names")
            return super().names()

    scope = Counting({"count": 1})
    assert build("count + 1").evaluate(scope) == 2
    assert build("[count for _ in [1]]").evaluate_tracked(scope).value == [1]
    assert calls == []
    with pytest.raises(TelError) as raised:
        build("cout").evaluate(scope)
    assert calls == ["names"] and raised.value.hint == "did you mean 'count'"


@pytest.mark.parametrize("bad", [RuntimeError("x"), KeyError("k"), TypeError("t")])
def test_clause_5_names_that_fails_leaves_the_real_error(bad):
    class Scope:
        def lookup(self, name):
            raise KeyError(name)

        def names(self):
            raise bad

    with pytest.raises(TelError) as raised:
        build("x").evaluate(Scope())
    assert raised.value.code == "unknown-name" and raised.value.hint is None


# -- clause 6: a scope is not copied or inspected beyond lookup and names -------------------------


def test_clause_6_tel_asks_the_scope_for_lookup_and_names_and_nothing_else():
    touched = set()

    class Watched:
        def __getattribute__(self, name):
            touched.add(name)
            return object.__getattribute__(self, name)

        def lookup(self, name):
            if name == "a":
                return 1
            raise KeyError(name)

        def names(self):
            return ["a"]

    scope = Watched()
    build("a + 1").evaluate(scope)
    build("a + 1").evaluate_tracked(scope)
    template("{{ a }} and {{ a + 1 }}").evaluate(scope)
    with pytest.raises(TelError):
        build("b").evaluate(scope)
    assert touched <= {"lookup", "names"}


def test_clause_6_a_map_scope_copies_its_mapping_once_when_it_is_made():
    source = {"a": 1}
    scope = MapScope(source)
    source["a"] = 2
    source["b"] = 3
    assert build("a").evaluate(scope) == 1
    with pytest.raises(TelError):
        build("b").evaluate(scope)


def test_clause_6_the_expression_does_not_keep_a_scope_between_evaluations():
    import gc
    import weakref

    class Scope:
        def lookup(self, name):
            return 1

    expr = build("a + a")
    scope = Scope()
    ref = weakref.ref(scope)
    expr.evaluate(scope)
    expr.evaluate_tracked(scope)
    del scope
    gc.collect()
    assert ref() is None


# -- clause 7 (added by path tracking): attribute steps on what a scope returns -------------------


class Node:
    """A host object that writes down every attribute asked of it."""

    def __init__(self, log, **attrs):
        object.__setattr__(self, "_log", log)
        object.__setattr__(self, "_attrs", attrs)

    def __getattr__(self, name):
        self._log.append(name)
        try:
            return self._attrs[name]
        except KeyError:
            raise AttributeError(name) from None


def test_clause_7_each_step_of_a_chain_is_one_getattr_in_order_and_nothing_else():
    log: list[str] = []
    leaf = Node(log, width=5, height=7)
    root = Node(log, bar=Node(log, inner=leaf), other=Node(log, never=1))
    scope = MapScope({"root": root})
    assert build("root.bar.inner.width").evaluate(scope) == 5
    assert log == ["bar", "inner", "width"]
    log.clear()
    assert build("root.bar.inner.width").evaluate_tracked(scope).value == 5
    assert log == ["bar", "inner", "width"]


def test_clause_7_attributes_are_read_again_every_evaluation_and_every_use():
    log: list[str] = []
    scope = MapScope({"n": Node(log, w=1)})
    expr = build("n.w + n.w")
    expr.evaluate(scope)
    expr.evaluate(scope)
    assert log == ["w"] * 4


def test_clause_7_an_attribute_that_is_not_used_is_never_read():
    log: list[str] = []
    scope = MapScope({"n": Node(log, a=1, b=2)})
    build("n.a if False else 0").evaluate(scope)
    build("False and n.b").evaluate(scope)
    assert log == []


def test_clause_7_a_property_that_raises_is_an_error_with_no_text_from_the_host():
    class Holder:
        @property
        def broken(self):
            raise RuntimeError("secret detail from the host")

    with pytest.raises(TelError) as raised:
        build("h.broken").evaluate(MapScope({"h": Holder()}))
    assert raised.value.code == "attribute-failed"
    assert "secret detail" not in str(raised.value)


def test_clause_7_a_missing_attribute_is_an_error_not_an_unknown_name():
    with pytest.raises(TelError) as raised:
        build("n.nope").evaluate(MapScope({"n": Node([], a=1)}))
    assert raised.value.code == "no-attribute"


def test_clause_7_a_method_is_not_an_attribute():
    class Holder:
        def method(self): ...

    with pytest.raises(TelError) as raised:
        build("h.method").evaluate(MapScope({"h": Holder()}))
    assert raised.value.code == "attribute-is-method"


def test_clause_7_the_attribute_is_read_as_a_step_not_looked_up_in_the_scope():
    scope = Logging({"n": Node([], w=1)})
    build("n.w").evaluate(scope)
    assert scope.asked == ["n"]
