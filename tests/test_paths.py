"""Path tracking (step 4, phase 4b; decision D13): which attribute paths an evaluation read."""

import pickle
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import tess_el
from tess_el import MapScope, TelError, Tracked


def build(text, **kw):
    return tess_el.compile_expression(text, language="0.1", **kw)


class Spy:
    """An independent oracle: a node of a tree that writes down the path of every attribute asked of
    it. A dict among its children becomes a node; anything else is returned as it is."""

    def __init__(self, path, log, kids):
        self._path, self._log, self._kids = path, log, kids

    def __getattr__(self, name):
        path = f"{self._path}.{name}"
        self._log.append(path)
        if name not in self._kids:
            raise AttributeError(name)
        kid = self._kids[name]
        return Spy(path, self._log, kid) if isinstance(kid, dict) else kid


TREE = {
    "DP1": {
        "Top_Bar": {"Width": 300, "Height": 30, "Inner": {"Deep": {"Leaf": 7}}},
        "Left": {"Width": 10},
    },
    "Name": "root",
    "items": [10, 20],
}


def spy_scope(**extra):
    log = []
    values = {"RootShell": Spy("RootShell", log, TREE), "flag": True, "n": 3, "ws": [{"y": 1}]}
    return MapScope({**values, **extra}), log


def check(source, expected, **extra):
    """Evaluate tracked against the spy; `reads` must be `expected`, every reported attribute path
    must really have been asked, and nothing asked may be off the way to a reported path."""
    scope, log = spy_scope(**extra)
    result = build(source).evaluate_tracked(scope)
    assert result.reads == frozenset(expected), (source, sorted(result.reads))
    accessed = set(log)
    assert {p for p in result.reads if "." in p and p.startswith("RootShell")} <= accessed
    for path in accessed:
        assert any(r == path or r.startswith(path + ".") for r in result.reads), (source, path)
    return result


# -- what a chain reads ---------------------------------------------------------------------------


def test_a_chain_reads_its_full_path_and_not_its_prefixes():
    result = check("RootShell.DP1.Top_Bar.Width", {"RootShell.DP1.Top_Bar.Width"})
    assert result.value == 300 and result.names == {"RootShell"}


@pytest.mark.parametrize(
    "source, reads",
    [
        ("RootShell.Name", {"RootShell.Name"}),
        (
            "RootShell.DP1.Left.Width + RootShell.DP1.Top_Bar.Height",
            {"RootShell.DP1.Left.Width", "RootShell.DP1.Top_Bar.Height"},
        ),
        ("RootShell.DP1.Top_Bar.Inner.Deep.Leaf", {"RootShell.DP1.Top_Bar.Inner.Deep.Leaf"}),
        ("RootShell.DP1.Left.Width + RootShell.DP1.Left.Width", {"RootShell.DP1.Left.Width"}),
        (
            "f'{RootShell.Name}: {RootShell.DP1.Left.Width}'",
            {"RootShell.Name", "RootShell.DP1.Left.Width"},
        ),
        ("[RootShell.Name for _ in range(2)]", {"RootShell.Name"}),
        ("n + RootShell.DP1.Left.Width", {"n", "RootShell.DP1.Left.Width"}),
        ("RootShell.DP1.Left.Width * 2 + 1", {"RootShell.DP1.Left.Width"}),
        ("(n - 1) + flag", {"n", "flag"}),
        ("n + (n - 1)", {"n"}),
        ("ws[0]['y'] + ws[-1]['y']", {"ws"}),
    ],
)
def test_paths_read_by_an_expression(source, reads):
    check(source, reads)


def test_a_chain_that_is_a_prefix_of_another_is_reported_too_when_it_is_read_as_a_value():
    check(
        "RootShell.DP1 is not None and RootShell.DP1.Left.Width",
        {"RootShell.DP1", "RootShell.DP1.Left.Width"},
    )


def test_a_bare_name_is_a_path_of_one_step():
    assert tess_el.compile_expression("n + 1", language="0.1").evaluate_tracked(
        MapScope({"n": 1})
    ).reads == {"n"}


# -- where a path stops ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, reads",
    [
        ("RootShell.items[0]", {"RootShell.items"}),
        ("RootShell.items[0] + RootShell.items[1]", {"RootShell.items"}),
        ("RootShell.items[1:]", {"RootShell.items"}),
        ("len(RootShell.items)", {"RootShell.items"}),
        ("RootShell.Name.upper()", {"RootShell.Name"}),
        ("RootShell.Name.upper().lower()", {"RootShell.Name"}),
        ("[i for i in RootShell.items]", {"RootShell.items"}),
        ("sum(RootShell.items)", {"RootShell.items"}),
        ("RootShell.Name + 'x'", {"RootShell.Name"}),
    ],
)
def test_a_path_stops_at_a_subscript_a_call_or_any_other_expression(source, reads):
    check(source, reads)


def test_a_function_name_and_a_method_name_are_not_reads():
    fmt = {"fmt": lambda x: x}
    expr = build("fmt(RootShell.Name)", functions=fmt)
    scope, _ = spy_scope()
    assert expr.evaluate_tracked(scope).reads == {"RootShell.Name"}
    assert expr.paths == {"RootShell.Name"} and expr.names == {"RootShell"}


def test_the_receiver_chain_of_a_host_method_is_a_read_and_the_method_name_is_not():
    class Price:
        def formatted(self):
            return "1"

    expr = build("p.box.formatted()", methods={Price: {"formatted": Price.formatted}})
    box = type("Box", (), {})()
    box.box = Price()
    assert expr.evaluate_tracked(MapScope({"p": box})).reads == {"p.box"}


# -- loop variables are not reads -----------------------------------------------------------------


def test_a_chain_on_a_loop_variable_is_not_a_read_and_its_iterable_is():
    result = tess_el.compile_expression("[w.y for w in ws]", language="0.1").evaluate_tracked(
        MapScope({"ws": [{"y": 1}, {"y": 2}]})
    )
    assert result == ([1, 2], frozenset({"ws"}))


def test_a_loop_variable_that_hides_a_scope_name_makes_its_chains_local():
    scope = MapScope({"x": {"y": 99}, "xs": [{"y": 1}]})
    result = build("[x.y for x in xs] + [x.y]").evaluate_tracked(scope)
    assert result.value == [1, 99] and result.reads == {"xs", "x.y"}


def test_a_chain_on_the_loop_variable_of_an_inner_loop_over_a_chain():
    scope = MapScope({"RootShell": {"groups": [[{"n": 1}], [{"n": 2}]]}})
    result = build("[i.n for g in RootShell.groups for i in g]").evaluate_tracked(scope)
    assert result.value == [1, 2] and result.reads == {"RootShell.groups"}


# -- branches and short-circuit -------------------------------------------------------------------


@pytest.mark.parametrize(
    "flag, reads",
    [
        (True, {"flag", "RootShell.DP1.Left.Width"}),
        (False, {"flag", "RootShell.DP1.Top_Bar.Width"}),
    ],
)
def test_a_conditional_reads_the_path_of_the_branch_it_takes(flag, reads):
    check("RootShell.DP1.Left.Width if flag else RootShell.DP1.Top_Bar.Width", reads, flag=flag)


def test_short_circuit_skips_the_paths_it_skips():
    check("flag or RootShell.DP1.Left.Width", {"flag"})
    check("not flag or RootShell.DP1.Left.Width", {"flag", "RootShell.DP1.Left.Width"}, flag=True)
    check("flag and RootShell.Name", {"flag", "RootShell.Name"})


# -- the static paths -----------------------------------------------------------------------------


def test_paths_are_known_from_the_text_and_cover_both_branches():
    expr = build("RootShell.DP1.Left.Width if flag else RootShell.DP1.Top_Bar.Width")
    assert expr.paths == {"flag", "RootShell.DP1.Left.Width", "RootShell.DP1.Top_Bar.Width"}
    assert expr.names == {"flag", "RootShell"} and type(expr.paths) is frozenset
    assert build("1 + 2").paths == frozenset()
    assert build("[w.y for w in ws]").paths == {"ws"}
    assert build("RootShell.items[0]").paths == {"RootShell.items"}


def test_the_static_paths_include_a_name_that_a_fused_closure_reads_itself():
    assert build("(a - 1) * b").paths == {"a", "b"}  # a name on the right of an expression
    assert build("a * (b - 1)").paths == {"a", "b"}  # a name on the left of an expression
    assert build("items[0] + items[-1]").paths == {"items"}
    assert build("d['k']").paths == {"d"}


def test_a_tracked_read_is_always_one_of_the_paths():
    for source in (
        "RootShell.DP1.Left.Width",
        "RootShell.Name + str(n)",
        "[i for i in RootShell.items]",
    ):
        scope, _ = spy_scope()
        expr = build(source)
        assert expr.evaluate_tracked(scope).reads <= expr.paths


def test_tracked_has_the_value_and_the_reads_and_names_is_a_property():
    scope, _ = spy_scope()
    result = build("RootShell.DP1.Left.Width + n").evaluate_tracked(scope)
    value, reads = result
    assert (value, reads) == (13, {"RootShell.DP1.Left.Width", "n"})
    assert Tracked._fields == ("value", "reads") and result.names == {"RootShell", "n"}
    assert type(result.names) is frozenset


def test_a_mapping_read_by_attribute_is_a_path_too():
    result = build("cfg.a.b").evaluate_tracked(MapScope({"cfg": {"a": {"b": 5}}}))
    assert result == (5, frozenset({"cfg.a.b"}))


# -- when a step fails ----------------------------------------------------------------------------


def test_a_missing_attribute_reports_the_path_up_to_and_including_the_failing_step():
    scope, _ = spy_scope()
    with pytest.raises(TelError) as raised:
        build("RootShell.DP1.nope.x").evaluate_tracked(scope)
    error = raised.value
    assert error.code == "no-attribute" and error.reads == {"RootShell.DP1.nope"}


def test_a_missing_root_reports_the_root():
    with pytest.raises(TelError) as raised:
        build("nope.a.b + n").evaluate_tracked(MapScope({"n": 1}))
    assert raised.value.code == "unknown-name" and raised.value.reads == {"nope"}


def test_reads_before_the_failure_are_kept():
    scope, _ = spy_scope()
    with pytest.raises(TelError) as raised:
        build("RootShell.Name + RootShell.DP1.nope").evaluate_tracked(scope)
    assert raised.value.reads == {"RootShell.Name", "RootShell.DP1.nope"}


def test_a_later_error_in_the_same_expression_keeps_the_full_chains_that_succeeded():
    scope, _ = spy_scope()
    with pytest.raises(TelError) as raised:
        build("RootShell.DP1.Left.Width + 'a'").evaluate_tracked(scope)
    assert raised.value.code == "bad-operand" and raised.value.reads == {"RootShell.DP1.Left.Width"}


def test_a_plain_evaluation_still_leaves_reads_unknown():
    with pytest.raises(TelError) as raised:
        build("RootShell.nope").evaluate(MapScope({"RootShell": {"a": 1}}))
    assert raised.value.code == "no-key" and raised.value.reads is None


def test_the_reads_of_an_error_survive_pickling():
    with pytest.raises(TelError) as raised:
        build("a.b.nope").evaluate_tracked(MapScope({"a": {"b": {}}}))
    copy = pickle.loads(pickle.dumps(raised.value))
    assert copy.reads == {"a.b.nope"} and copy.code == "no-key"


def test_the_positions_of_a_failing_step_are_those_of_that_step():
    scope = MapScope({"RootShell": {"DP1": {}}})
    for tracked in (False, True):
        with pytest.raises(TelError) as raised:
            expr = build("RootShell.DP1.nope")
            expr.evaluate_tracked(scope) if tracked else expr.evaluate(scope)
        assert (raised.value.line, raised.value.column, raised.value.end_column) == (1, 1, 19)
    with pytest.raises(TelError) as raised:
        build("RootShell.nope.x").evaluate(MapScope({"RootShell": {}}))
    assert (raised.value.column, raised.value.end_column) == (1, 15)


def test_the_unknown_name_error_of_a_chain_root_points_at_the_name():
    with pytest.raises(TelError) as raised:
        build("1 + nme.a.b").evaluate(MapScope({"name": 1}))
    assert (raised.value.column, raised.value.end_column) == (5, 8)
    assert raised.value.hint == "did you mean 'name'"


# -- a property hides what it reads ---------------------------------------------------------------


def test_a_property_is_reported_by_its_own_path_and_not_by_what_it_reads():
    class Bar:
        Width, Height = 3, 4

        @property
        def Area(self):
            return self.Width * self.Height

    class Root:
        Top_Bar = Bar()

    result = build("r.Top_Bar.Area").evaluate_tracked(MapScope({"r": Root()}))
    assert result == (12, frozenset({"r.Top_Bar.Area"}))


# -- templates ------------------------------------------------------------------------------------


def template(text, **kw):
    return tess_el.compile_template(text, language="0.1", **kw)


def test_a_template_reads_the_union_of_its_parts_paths():
    t = template("{{ RootShell.Name }} {{ RootShell.DP1.Left.Width }} {{ RootShell.Name }} {{ n }}")
    scope, _ = spy_scope()
    result = t.evaluate_tracked(scope)
    assert result.value == "root 10 root 3"
    assert result.reads == {"RootShell.Name", "RootShell.DP1.Left.Width", "n"}
    assert result.names == {"RootShell", "n"}
    assert t.paths == result.reads and t.names == {"RootShell", "n"}


def test_a_template_that_is_exactly_one_part_keeps_the_type_and_the_path():
    scope, _ = spy_scope()
    assert template("{{ RootShell.items }}").evaluate_tracked(scope) == (
        [10, 20],
        {"RootShell.items"},
    )


def test_an_error_in_a_template_part_carries_the_paths_read_so_far():
    scope, _ = spy_scope()
    with pytest.raises(TelError) as raised:
        template("{{ RootShell.Name }} {{ RootShell.DP1.nope }} {{ n }}").evaluate_tracked(scope)
    assert raised.value.reads == {"RootShell.Name", "RootShell.DP1.nope"}


# -- behaviour that must not change ---------------------------------------------------------------


def test_the_value_is_the_one_evaluate_gives():
    scope, _ = spy_scope()
    for source in ("RootShell.DP1.Left.Width", "RootShell.items[1] + n", "[w.y for w in ws]"):
        expr = build(source)
        assert expr.evaluate_tracked(scope).value == expr.evaluate(scope)


def test_a_tracked_evaluation_asks_the_scope_once_per_chain():
    asked = []

    class Counting(MapScope):
        __slots__ = ()

        def lookup(self, name):
            asked.append(name)
            return super().lookup(name)

    scope = Counting({"a": {"b": 1}})
    build("a.b + a.b").evaluate(scope)
    plain, asked[:] = list(asked), []
    build("a.b + a.b").evaluate_tracked(scope)
    assert asked == plain == ["a", "a"]


def test_tracked_chains_on_many_threads_keep_their_own_paths():
    expr = build("RootShell.DP1.Left.Width if flag else RootShell.Name")
    barrier = threading.Barrier(8)

    def work(k):
        barrier.wait()
        flag = k % 2 == 0
        out = []
        for _ in range(300):
            scope, _ = spy_scope(flag=flag)
            out.append((flag, expr.evaluate_tracked(scope).reads))
        return out

    with ThreadPoolExecutor(8) as pool:
        for results in pool.map(work, range(8)):
            for flag, reads in results:
                assert reads == (
                    {"flag", "RootShell.DP1.Left.Width"} if flag else {"flag", "RootShell.Name"}
                )


def test_a_chain_on_an_object_that_is_not_plain_can_still_be_read_but_not_operated_on():
    class Box:
        value = 5

    scope = MapScope({"b": Box()})
    assert build("b.value + 1").evaluate_tracked(scope) == (6, frozenset({"b.value"}))
    with pytest.raises(TelError) as raised:
        build("b + 1").evaluate_tracked(scope)
    assert raised.value.code == "value-not-plain" and raised.value.reads == {"b"}


def test_private_attributes_and_methods_are_still_refused_in_a_chain():
    for source, code in (("a._x", "private-attribute"), ("a.b.__class__", "private-attribute")):
        with pytest.raises(tess_el.TelSyntaxError) as raised:
            build(source)
        assert raised.value.code == code
    with pytest.raises(TelError) as raised:
        build("a.method").evaluate_tracked(
            MapScope({"a": type("A", (), {"method": lambda s: 1})()})
        )
    assert raised.value.code == "attribute-is-method" and raised.value.reads == {"a.method"}


@pytest.mark.parametrize("text", ["nme.a", "1 + nme.a.b", "nme.a.b.c"])
def test_a_missing_root_is_the_same_error_for_chains_of_every_length(text):
    scope = MapScope({"name": {"a": {"b": {"c": 1}}}})
    for tracked in (False, True):
        with pytest.raises(TelError) as raised:
            expr = build(text)
            expr.evaluate_tracked(scope) if tracked else expr.evaluate(scope)
        error = raised.value
        assert error.code == "unknown-name" and error.hint == "did you mean 'name'"
        assert error.text_column == text.index("nme") + 1
        assert error.reads == ({"nme"} if tracked else None)
