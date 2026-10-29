"""Host functions and host methods (step 4, phase 3): what a host adds, and the rules it keeps."""

import datetime
import decimal
import enum
import keyword
import threading
import types
from concurrent.futures import ThreadPoolExecutor

import pytest
from reference.support import Trap

import tel
from tel import Limits, MapScope, TelError
from tel._whitelist import BUILTIN_NAMES, DICT_METHODS, SEQUENCE_METHODS, STR_METHODS


def build(text, **kw):
    return tel.compile_expression(text, language="0.1", **kw)


def run(text, scope=None, **kw):
    return build(text, **kw).evaluate(MapScope(scope or {}))


def fails(text, code, scope=None, **kw):
    with pytest.raises(TelError) as raised:
        run(text, scope, **kw)
    assert raised.value.code == code, str(raised.value)
    return raised.value


class Price:
    def __init__(self, amount):
        self.amount = amount

    def formatted(self, digits=0):
        return f"{self.amount:,.{digits}f}"


class Special(Price):
    def formatted(self, digits=0):
        return "special"


def fmt(x, digits=0):
    return f"{x:,.{digits}f}"


# -- host functions -------------------------------------------------------------------------------


def test_a_registered_function_is_called_with_its_arguments():
    assert run("fmt(1234.5, 1)", functions={"fmt": fmt}) == "1,234.5"
    assert run("fmt(x, digits=2)", {"x": 3}, functions={"fmt": fmt}) == "3.00"
    assert run("fmt(*args)", {"args": [7, 1]}, functions={"fmt": fmt}) == "7.0"
    assert run("[fmt(i) for i in range(3)]", functions={"fmt": fmt}) == ["0", "1", "2"]
    assert run("fmt(fmt(1))", functions={"fmt": lambda x: x}) == 1


def test_a_registered_function_works_in_a_template_too():
    template = tel.compile_template(
        "Total {{ fmt(total, 1) }}", language="0.1", functions={"fmt": fmt}
    )
    assert template.evaluate(MapScope({"total": 1234.5})) == "Total 1,234.5"


def test_the_function_name_is_not_a_name_the_expression_reads():
    expr = build("fmt(total, 1)", functions={"fmt": fmt})
    assert expr.names == {"total"}
    assert expr.evaluate_tracked(MapScope({"total": 1.0})).reads == {"total"}


def test_a_call_means_the_registered_function_whatever_the_scope_says():
    assert run("fmt(1)", {"fmt": "from the scope"}, functions={"fmt": fmt}) == "1"
    assert run("fmt", {"fmt": "from the scope"}, functions={"fmt": fmt}) == "from the scope"
    error = fails("fmt", "function-as-value", functions={"fmt": fmt})
    assert "'fmt' is a function" in error.message


def test_a_name_that_is_not_registered_is_still_not_a_function():
    with pytest.raises(tel.TelSyntaxError) as raised:
        build("frm(1)", functions={"fmt": fmt})
    assert raised.value.code == "call-not-function" and raised.value.hint == "did you mean 'fmt'"
    with pytest.raises(tel.TelSyntaxError):
        build("fmt(1)")  # not registered for this expression


def test_the_registration_is_copied_when_the_expression_is_compiled():
    functions = {"fmt": fmt}
    expr = build("fmt(1)", functions=functions)
    functions["fmt"] = lambda x: "changed"
    functions["other"] = fmt
    assert expr.evaluate(MapScope()) == "1"
    with pytest.raises(tel.TelSyntaxError):
        build("other(1)", functions={"fmt": fmt})


@pytest.mark.parametrize("name", sorted(BUILTIN_NAMES))
def test_a_built_in_function_can_never_be_replaced(name):
    with pytest.raises(ValueError, match=rf"'{name}'.*built-in"):
        build("1", functions={name: fmt})


@pytest.mark.parametrize(
    "name, why",
    [
        ("_private", "start with _"),
        ("__import__", "start with _"),
        ("class", "keyword"),
        ("None", "keyword"),
        ("not an identifier", "identifier"),
        ("", "identifier"),
        ("a.b", "identifier"),
        ("1abc", "identifier"),
        ("ｆmt", "normal"),
    ],
)
def test_a_function_name_must_be_a_usable_name(name, why):
    with pytest.raises(ValueError, match=why):
        build("1", functions={name: fmt})


def test_the_registration_must_be_what_it_says():
    for bad in ([("fmt", fmt)], "fmt", 5):
        with pytest.raises(TypeError, match="functions must be a mapping"):
            build("1", functions=bad)
    with pytest.raises(TypeError, match="function name must be a str"):
        build("1", functions={5: fmt})
    for bad in (None, 5, "fmt", fmt.__name__):
        with pytest.raises(TypeError, match="'fmt' must be callable"):
            build("1", functions={"fmt": bad})
    with pytest.raises(TypeError, match="functions must be a mapping"):
        tel.compile_template("{{ 1 }}", language="0.1", functions=[fmt])


def test_the_keywords_are_all_refused_as_function_names():
    for word in keyword.kwlist:
        with pytest.raises(ValueError):
            build("1", functions={word: fmt})


def test_only_plain_values_are_handed_to_a_function():
    Trap.tripped.clear()
    for source in ("fmt(t)", "fmt(1, digits=t)", "fmt(*[t])", "fmt([t][0])"):
        fails(source, "value-not-plain", {"t": Trap()}, functions={"fmt": fmt})
    assert Trap.tripped == []


def test_lists_are_passed_as_they_are_so_a_function_that_changes_them_changes_the_hosts_data():
    items = [1, 2]
    run("grow(items)", {"items": items}, functions={"grow": lambda xs: xs.append(3)})
    assert items == [1, 2, 3]  # a host contract: TEL cannot check purity


@pytest.mark.parametrize(
    "result",
    [None, True, 3, 2.5, "x", [1], (1,), {"a": 1}, {1}, range(2), datetime.date(2026, 1, 1),
     decimal.Decimal("1.5"), datetime.timedelta(1)],
)  # fmt: skip
def test_a_plain_result_is_returned_as_it_is(result):
    assert run("make()", functions={"make": lambda: result}) is result


def test_an_enum_member_is_a_plain_result():
    class Mode(enum.Enum):
        A = 1

    assert run("make()", functions={"make": lambda: Mode.A}) is Mode.A


@pytest.mark.parametrize(
    "result",
    [object(), Price(1), Trap(), len, lambda: 1, types, int, (i for i in []), Price.formatted],
    ids=[
        "object",
        "instance",
        "trap",
        "builtin",
        "lambda",
        "module",
        "class",
        "generator",
        "method",
    ],
)
def test_a_result_that_is_not_plain_is_refused(result):
    Trap.tripped.clear()
    error = fails("make()", "result-not-plain", functions={"make": lambda: result})
    assert "make() returned" in error.message and Trap.tripped == []


def test_a_result_is_size_limited_like_a_built_ins():
    fails("make()", "limit-string", functions={"make": lambda: "x" * 2_000_000})
    fails("make()", "limit-int-bits", functions={"make": lambda: 2**5000})
    assert (
        run("make()", functions={"make": lambda: "x" * 5}, limits=Limits(max_string=5)) == "xxxxx"
    )
    fails(
        "make()", "limit-string", functions={"make": lambda: "x" * 6}, limits=Limits(max_string=5)
    )


def test_an_exception_from_a_function_is_bad_call_without_its_message():
    def broken():
        raise ValueError("secret-detail-xyzzy")

    error = fails("broken()", "bad-call", functions={"broken": broken})
    assert "broken() failed (ValueError)" in error.message
    assert "secret-detail-xyzzy" not in str(error) and "secret-detail-xyzzy" not in error.render()


def test_a_tel_error_raised_inside_a_function_is_passed_on():
    inner = build("1 + 'a'")

    def nested():
        return inner.evaluate(MapScope())

    error = fails("nested()", "bad-operand", functions={"nested": nested})
    assert error.source == "1 + 'a'"


def test_a_call_costs_a_step():
    expr = build("f(1) + f(1) + f(1)", functions={"f": lambda x: x}, limits=Limits(max_steps=2))
    with pytest.raises(tel.TelLimitError) as raised:
        expr.evaluate(MapScope())
    assert raised.value.code == "limit-steps"
    ok = build("f(1) + f(1) + f(1)", functions={"f": lambda x: x}, limits=Limits(max_steps=3))
    assert ok.evaluate(MapScope()) == 3


def test_a_long_text_result_costs_steps_in_proportion_to_its_length():
    one_step = Limits(max_steps=1)
    assert run("make()", functions={"make": lambda: "x" * 63}, limits=one_step) == "x" * 63
    fails("make()", "limit-steps", functions={"make": lambda: "x" * 128}, limits=one_step)
    fails(
        "p.make()",
        "limit-steps",
        {"p": Price(1)},
        methods={Price: {"make": lambda self: "x" * 128}},
        limits=one_step,
    )


def test_a_function_may_evaluate_another_expression():
    inner = build("a * 2")
    result = run(
        "twice(5) + 1",
        functions={"twice": lambda a: inner.evaluate(MapScope({"a": a}))},
    )
    assert result == 11


def test_the_arguments_error_names_the_function():
    error = fails("fmt(t)", "value-not-plain", {"t": Trap()}, functions={"fmt": fmt})
    assert "fmt() takes" in error.message and "Trap" in error.message


def test_errors_in_a_call_point_at_the_call():
    error = fails("1 + fmt(t)", "value-not-plain", {"t": Trap()}, functions={"fmt": fmt})
    assert (error.line, error.column, error.end_column) == (1, 5, 11)


# -- host methods ---------------------------------------------------------------------------------


def methods():
    return {Price: {"formatted": Price.formatted}}


def test_a_registered_method_is_called_on_a_value_of_its_type():
    assert run("p.formatted()", {"p": Price(1234.5)}, methods=methods()) == "1,234"
    assert run("p.formatted(2)", {"p": Price(1234.5)}, methods=methods()) == "1,234.50"
    assert run("p.formatted(digits=1).upper()", {"p": Price(1.5)}, methods=methods()) == "1.5"
    assert run("[p.formatted() for p in ps]", {"ps": [Price(1), Price(2)]}, methods=methods()) == [
        "1",
        "2",
    ]


def test_a_registered_method_works_in_a_template_too():
    template = tel.compile_template("{{ p.formatted(1) }}!", language="0.1", methods=methods())
    assert template.evaluate(MapScope({"p": Price(2)})) == "2.0!"


def test_a_subclass_is_served_and_the_nearest_class_wins():
    both = {
        Price: {"formatted": lambda self, digits=0: "base"},
        Special: {"formatted": Special.formatted},
    }
    assert run("p.formatted()", {"p": Special(1)}, methods=both) == "special"
    assert run("p.formatted()", {"p": Price(1)}, methods=both) == "base"
    only_base = {Price: {"formatted": Price.formatted}}
    assert run("p.formatted()", {"p": Special(1)}, methods=only_base) == "1"


def test_the_method_is_looked_up_name_by_name_down_the_base_classes():
    class A:
        pass

    class B(A):
        pass

    registered = {A: {"one": lambda self: 1, "two": lambda self: "A"}, B: {"two": lambda self: "B"}}
    assert run("b.one() + 1", {"b": B()}, methods=registered) == 2
    assert run("b.two()", {"b": B()}, methods=registered) == "B"


def test_a_value_of_another_type_has_no_such_method():
    fails("n.formatted()", "method-not-for-type", {"n": 3}, methods=methods())
    fails("p.formatted()", "method-not-for-type", {"p": object()}, methods=methods())
    error = fails("s.formatted()", "method-not-for-type", {"s": "text"}, methods=methods())
    assert "str" in error.message


def test_a_method_name_nobody_registered_is_refused_when_the_text_is_read():
    with pytest.raises(tel.TelSyntaxError) as raised:
        build("p.formated()", methods=methods())
    assert (
        raised.value.code == "method-not-available"
        and raised.value.hint == "did you mean 'formatted'"
    )
    with pytest.raises(tel.TelSyntaxError):
        build("p.formatted()")  # no registration at all


def test_a_method_without_a_call_is_still_not_a_value():
    fails("p.formatted", "attribute-is-method", {"p": Price(1)}, methods=methods())


def test_the_object_is_never_asked_what_it_can_do():
    Trap.tripped.clear()
    registered = {Trap: {"dangerous": lambda self: "registered"}}
    assert run("t.dangerous()", {"t": Trap()}, methods=registered) == "registered"
    assert Trap.tripped == []  # the object's own `dangerous` did not run
    fails(
        "t.other()",
        "method-not-for-type",
        {"t": Trap()},
        methods={Price: {"other": Price.formatted}},
    )
    assert Trap.tripped == []


def test_the_receiver_is_a_read_and_the_method_name_is_not():
    expr = build("p.formatted()", methods=methods())
    assert expr.names == {"p"}
    assert expr.evaluate_tracked(MapScope({"p": Price(1)})).reads == {"p"}


def test_plain_types_can_be_given_methods_too():
    registered = {
        str: {"titlecase": str.title},
        int: {"doubled": lambda n: n * 2},
        list: {"second": lambda xs: xs[1]},
        dict: {"size": len},
    }
    scope = {"s": "ada lovelace", "n": 21, "xs": [1, 2], "d": {"a": 1}}
    assert run("s.titlecase()", scope, methods=registered) == "Ada Lovelace"
    assert run("n.doubled()", scope, methods=registered) == 42
    assert run("True.doubled()", scope, methods=registered) == 2  # bool is an int
    assert run("xs.second()", scope, methods=registered) == 2
    assert run("d.size()", scope, methods=registered) == 1
    assert run("'x'.titlecase()", scope, methods=registered) == "X"


def test_a_built_in_method_still_runs_the_built_in_when_a_host_method_is_registered():
    assert run("s.upper()", {"s": "a"}, methods={str: {"titlecase": str.title}}) == "A"


@pytest.mark.parametrize(
    "kind, name",
    [(str, n) for n in sorted(STR_METHODS)]
    + [(list, n) for n in sorted(SEQUENCE_METHODS)]
    + [(tuple, n) for n in sorted(SEQUENCE_METHODS)]
    + [(dict, n) for n in sorted(DICT_METHODS)],
)
def test_a_built_in_method_can_never_be_replaced(kind, name):
    with pytest.raises(ValueError, match=rf"'{name}'.*built-in"):
        build("1", methods={kind: {name: lambda self: 0}})


def test_a_subclass_of_a_plain_type_cannot_replace_its_built_in_methods_either():
    class Text(str):
        pass

    class Table(dict):
        pass

    with pytest.raises(ValueError, match="built-in"):
        build("1", methods={Text: {"upper": lambda s: s}})
    with pytest.raises(ValueError, match="built-in"):
        build("1", methods={Table: {"get": lambda s: s}})
    build("1", methods={Text: {"shout": lambda s: s}})


@pytest.mark.parametrize(
    "name, why",
    [
        ("format", "format"),
        ("format_map", "format"),
        ("_hidden", "start with _"),
        ("__class__", "start with _"),
        ("class", "keyword"),
        ("not valid", "identifier"),
        ("", "identifier"),
    ],
)
def test_a_method_name_must_be_a_usable_name(name, why):
    with pytest.raises(ValueError, match=why):
        build("1", methods={Price: {name: Price.formatted}})


@pytest.mark.parametrize(
    "bad_type",
    [
        object,
        type,
        types.ModuleType,
        types.FunctionType,
        types.CodeType,
        types.FrameType,
        len.__class__,
    ],
)
def test_a_method_cannot_be_registered_for_a_type_whose_attributes_are_denied(bad_type):
    with pytest.raises(ValueError, match="cannot be registered"):
        build("1", methods={bad_type: {"x": lambda self: 1}})


def test_the_method_registration_must_be_what_it_says():
    for bad in ([(Price, {})], "Price", 5):
        with pytest.raises(TypeError, match="methods must be a mapping"):
            build("1", methods=bad)
    with pytest.raises(TypeError, match="a methods key must be a class, not str"):
        build("1", methods={"Price": {"formatted": Price.formatted}})
    with pytest.raises(TypeError, match="a methods key must be a class, not Price"):
        build("1", methods={Price(1): {"formatted": Price.formatted}})
    with pytest.raises(TypeError, match=r"methods for Price must be a mapping"):
        build("1", methods={Price: [("formatted", Price.formatted)]})
    with pytest.raises(TypeError, match="'formatted' must be callable"):
        build("1", methods={Price: {"formatted": "no"}})
    with pytest.raises(TypeError, match="method name must be a str"):
        build("1", methods={Price: {5: Price.formatted}})


def test_the_method_registration_is_copied_when_compiled():
    registered = {Price: {"formatted": Price.formatted}}
    expr = build("p.formatted()", methods=registered)
    registered[Price]["formatted"] = lambda self: "changed"
    registered[Price]["more"] = lambda self: "more"
    assert expr.evaluate(MapScope({"p": Price(1)})) == "1"


def test_arguments_and_results_of_a_method_follow_the_rules_of_a_function():
    Trap.tripped.clear()
    registered = {Price: {"take": lambda self, x: x, "give": lambda self: object()}}
    fails("p.take(t)", "value-not-plain", {"p": Price(1), "t": Trap()}, methods=registered)
    fails("p.give()", "result-not-plain", {"p": Price(1)}, methods=registered)
    assert Trap.tripped == []
    fails(
        "p.big()",
        "limit-string",
        {"p": Price(1)},
        methods={Price: {"big": lambda self: "x" * 2_000_000}},
    )


def test_an_exception_from_a_method_is_bad_call_without_its_message():
    def broken(self):
        raise RuntimeError("secret-detail-xyzzy")

    error = fails("p.broken()", "bad-call", {"p": Price(1)}, methods={Price: {"broken": broken}})
    assert "broken() failed (RuntimeError)" in error.message and "secret-detail" not in str(error)


def test_functions_and_methods_together():
    registered = {Price: {"formatted": Price.formatted}}
    assert (
        run(
            "fmt(p.amount) + p.formatted(1)",
            {"p": Price(2)},
            functions={"fmt": fmt},
            methods=registered,
        )
        == "22.0"
    )


def test_a_host_method_name_does_not_make_a_function_callable_and_the_reverse():
    with pytest.raises(tel.TelSyntaxError):
        build("formatted(1)", methods=methods())
    with pytest.raises(tel.TelSyntaxError):
        build("x.fmt()", functions={"fmt": fmt})


def test_the_default_compile_is_unchanged():
    assert run("[s.upper() for s in xs]", {"xs": ["a"]}) == ["A"]
    assert run("len(xs)", {"xs": [1]}) == 1


# -- threads --------------------------------------------------------------------------------------


def test_one_compiled_expression_with_host_calls_can_be_used_from_many_threads():
    expr = build("fmt(n, 1) + p.formatted(1)", functions={"fmt": fmt}, methods=methods())
    barrier = threading.Barrier(8)

    def work(k):
        barrier.wait()
        return [expr.evaluate(MapScope({"n": k, "p": Price(k)})) for _ in range(200)]

    with ThreadPoolExecutor(8) as pool:
        for k, out in enumerate(pool.map(work, range(8))):
            assert all(r == f"{k:,.1f}{k:,.1f}" for r in out)
