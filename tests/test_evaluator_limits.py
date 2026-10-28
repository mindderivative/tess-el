"""The evaluator's limits, secrets, threads and public API (step 3, phase 4)."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from reference.expectations import EVALUATION_LEVEL_ESCAPES, EVALUATION_LEVEL_LIMITS

import tel
from tel import Limits, MapScope, Origin, TelError, TelLimitError, TelVersionError

CEILING = 0.5  # seconds: generous for a slow CI machine; the real figure is a few milliseconds


def build(source, **kw):
    return tel.compile_expression(source, language="0.1", **kw)


def run(source, limits=None, **values):
    kw = {} if limits is None else {"limits": limits}
    return build(source, **kw).evaluate(MapScope(values))


def refused(source, code, limits=None, **values):
    with pytest.raises(TelError) as raised:
        run(source, limits, **values)
    assert raised.value.code == code, str(raised.value)
    return raised.value


# -- the step budget ------------------------------------------------------------------------------
# A loop is paid for before it starts: iterations x (1 + target + conditions + element nodes).


def test_the_cost_of_a_loop_is_known_and_the_boundary_is_exact():
    # [i for i in range(10)]: 10 iterations x (1 loop + 1 target + 1 element) = 30 steps
    assert run("[i for i in range(10)]", Limits(max_steps=30)) == list(range(10))
    refused("[i for i in range(10)]", "limit-steps", Limits(max_steps=29))


def test_conditions_and_bigger_elements_cost_more():
    # i % 2 == 0 is 3 nodes... counted as nodes of the condition; the element i * 2 is 3 nodes
    cheap = "[i for i in range(10)]"
    dear = "[i * 2 for i in range(10) if i > 1]"
    limits = Limits(max_steps=30)
    assert run(cheap, limits)
    refused(dear, "limit-steps", limits)


def test_nested_loops_multiply():
    # the outer loop costs 100 x 2; each of its 100 iterations runs the inner loop at 100 x 3
    assert run("[1 for a in range(100) for b in range(100)]")
    refused("[1 for a in range(1000) for b in range(1000)]", "limit-steps")


def test_an_iterating_built_in_charges_its_input_before_it_runs():
    refused("sum(range(60000))", "limit-steps", Limits(max_steps=50_000, max_range=100_000))
    assert run("sum(range(60000))", Limits(max_steps=60_000, max_range=100_000)) == sum(
        range(60000)
    )


def test_building_a_long_text_costs_steps_so_a_chain_of_them_is_stopped():
    big = "x" * 300_000
    assert run("s * 2", s=big)  # one is fine
    refused("s * 2", "limit-steps", Limits(max_steps=100), s=big)


def test_the_budget_starts_again_for_every_evaluation():
    expr = build("[i for i in range(10)]", limits=Limits(max_steps=30))
    for _ in range(5):
        assert len(expr.evaluate(MapScope())) == 10


def test_a_loop_that_cannot_be_afforded_does_no_work():
    calls = []

    class Counting:
        def lookup(self, name):
            calls.append(name)
            return 1

    expr = build("[x for x in range(1000)]", limits=Limits(max_steps=100))
    with pytest.raises(TelLimitError):
        expr.evaluate(Counting())
    assert calls == []  # the element never ran


# -- sizes ----------------------------------------------------------------------------------------


def test_each_size_limit_is_honoured_when_it_is_changed():
    refused("range(6)", "limit-range", Limits(max_range=5))
    assert run("list(range(5))", Limits(max_range=5)) == [0, 1, 2, 3, 4]
    refused("[0] * 4", "limit-sequence", Limits(max_sequence=3))
    refused("list(range(4))", "limit-sequence", Limits(max_sequence=3))
    refused("'a' * 10", "limit-string", Limits(max_string=5, max_sequence=100))
    refused("int('9' * 50)", "limit-int-bits", Limits(max_int_bits=100))
    refused("3 ** 40 * 3 ** 40", "limit-int-bits", Limits(max_int_bits=100))
    assert run("3 ** 40", Limits(max_int_bits=100)) == 3**40
    refused("2 ** n", "limit-pow-exponent", n=65)
    refused("2 ** n", "limit-pow-exponent", n=70.0)
    assert run("2 ** n", n=10) == 1024


def test_the_result_of_a_power_is_stopped_before_it_is_made():
    refused("x ** 64", "limit-int-bits", Limits(max_int_bits=1000), x=10**20)


def test_replace_cannot_grow_a_string_a_million_fold():
    start = time.perf_counter()
    refused("s.replace('a', t)", "limit-string", s="a" * 500_000, t="b" * 500_000)
    refused("s.replace('', t)", "limit-string", s="a" * 500_000, t="b" * 500_000)
    assert time.perf_counter() - start < CEILING
    assert run("s.replace('a', 'bb', 1)", s="aaa") == "bbaa"
    assert run("s.replace('a', 'b')", s="a" * 10) == "b" * 10


def test_join_cannot_build_a_text_larger_than_its_limit():
    start = time.perf_counter()
    refused("'x'.join(items)", "limit-string", items=["y" * 900_000] * 3)
    assert time.perf_counter() - start < CEILING


def test_a_format_spec_width_or_precision_is_a_size():
    refused("f'{x:>{w}}'", "limit-string", x=1, w=2_000_000)
    assert run("f'{x:>{w}}'", x=1, w=5) == "    1"


# -- everything that is refused is refused quickly ------------------------------------------------


def test_every_refusal_that_needs_a_value_is_prompt():
    from reference import cases

    limits_by_source = {c[0]: c[2] for c in cases.LIMIT_CASES}
    start = time.perf_counter()
    worst = 0.0
    for source in list(EVALUATION_LEVEL_LIMITS) + list(EVALUATION_LEVEL_ESCAPES):
        limits = Limits(**limits_by_source.get(source, {}))
        scope = MapScope({**cases.ESCAPE_SCOPE_VALUES, "obj": object(), "trap": object()})
        t0 = time.perf_counter()
        with pytest.raises(TelError):
            build(source, limits=limits).evaluate(scope)
        worst = max(worst, time.perf_counter() - t0)
    assert worst < CEILING and time.perf_counter() - start < 5 * CEILING


# -- messages never carry a value from the scope --------------------------------------------------

SECRET = "hunter2-xyzzy"


@pytest.mark.parametrize(
    "source",
    [
        "int(secret)",
        "float(secret)",
        "secret + 1",
        "1 + secret",
        "secret < 1",
        "secret[100]",
        "secret[1.5]",
        "secret.nope",
        "secret.upper",
        "secret()",
        "secret % 3",
        "secret.center(secret)",
        "secret.split(secret, secret)",
        "secret.nope()",
        "{}[secret]",
        "d[secret]",
        "d.get(secret, secret, secret)",
        "range(secret)",
        "len(secret, secret)",
        "f'{secret:d}'",
        "-secret",
        "[a for a, b in [secret]]",
        "[a for a in secret.nope]",
        "1 in secret.nope",
        "isinstance(secret, secret)",
        "o.title.nope",
        "o.missing",
        "d.missing",
        "sorted([secret, 1])",
        "max(secret, 1)",
    ],
)
def test_no_error_message_contains_a_value_from_the_scope(source):
    class Holder:
        title = SECRET

    scope = MapScope({"secret": SECRET, "d": {"key": SECRET}, "o": Holder()})
    try:
        tel.compile_expression(source, language="0.1").evaluate(scope)
    except TelError as error:
        assert SECRET not in str(error) and SECRET not in error.render()
        assert SECRET not in (error.hint or "") and SECRET not in error.message
    # an expression that does not fail is not what this test is about


# -- threads, re-entrancy and depth ---------------------------------------------------------------


def test_one_compiled_expression_can_be_evaluated_from_many_threads():
    expr = build("[x * k for x in items if x > lo]")
    barrier = threading.Barrier(8)

    def work(k):
        barrier.wait()
        out = []
        for _ in range(200):
            out.append(expr.evaluate(MapScope({"items": [1, 2, 3, 4], "k": k, "lo": 1})))
        return out

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(work, range(8)))
    for k, out in enumerate(results):
        assert all(r == [2 * k, 3 * k, 4 * k] for r in out)


def test_a_scope_may_evaluate_another_expression_while_looking_up_a_name():
    inner = build("[i for i in range(3)]")

    class Nested:
        def lookup(self, name):
            return inner.evaluate(MapScope()) if name == "xs" else 5

    assert build("[x + y for x in xs for y in [one]]").evaluate(Nested()) == [5, 6, 7]


@pytest.mark.parametrize("n", [50, 200, 450, 700])
def test_a_deep_expression_is_a_result_or_a_limit_error_and_never_a_stack_overflow(n):
    huge = Limits(max_source=10_000, max_depth=10_000, max_nodes=10_000)
    try:
        expr = build("-" * n + "1", limits=huge)
        assert expr.evaluate(MapScope()) == (-1) ** n
    except TelLimitError as error:
        assert error.code == "limit-depth"


# -- the public surface ---------------------------------------------------------------------------


def test_the_language_version_is_required_and_checked():
    with pytest.raises(TypeError):
        tel.compile_expression("1")  # type: ignore[call-arg]
    with pytest.raises(TelVersionError):
        tel.compile_expression("1", language="9.9")
    with pytest.raises(TelVersionError) as raised:
        tel.compile_expression("1", language=0.1)  # type: ignore[arg-type]
    assert raised.value.code == "language-not-text"
    assert tel.compile_expression("1", language=tel.LANGUAGE).evaluate(MapScope()) == 1


def test_an_expression_describes_itself_and_cannot_be_changed():
    expr = build("  count + 1 ", origin=Origin("A.yaml", 3, 5))
    assert expr.source == "  count + 1 " and expr.text == "count + 1"
    assert expr.origin == Origin("A.yaml", 3, 7)
    assert expr.names == {"count"} and expr.nodes == 4
    assert expr.limits == tel.DEFAULT_LIMITS
    assert repr(expr) == "Expression('count + 1')"
    with pytest.raises(AttributeError):
        expr.text = "other"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        del expr.names


def test_a_compiled_expression_evaluates_against_any_scope():
    expr = build("a + b")
    assert expr.evaluate(MapScope({"a": 1, "b": 2})) == 3
    assert expr.evaluate(MapScope({"a": "x", "b": "y"})) == "xy"
    assert expr.evaluate(MapScope({"a": [1], "b": [2]})) == [1, 2]


def test_compile_errors_are_the_parsers_and_come_before_any_scope_is_needed():
    with pytest.raises(tel.TelSyntaxError):
        build("__class__")
    with pytest.raises(tel.TelLimitError):
        build("x" * 5000)


def test_the_package_exports_exactly_its_public_names():
    expected = """
        DEFAULT_LIMITS LANGUAGE Expression Limits MapScope Origin Scope TelError
        TelEvaluationError TelLimitError TelSyntaxError TelVersionError __version__
        compile_expression
    """.split()
    assert sorted(tel.__all__) == sorted(expected)
    for name in tel.__all__:
        assert hasattr(tel, name)


# -- rules found by the removal check -------------------------------------------------------------


@pytest.mark.parametrize("source", ["a + a", "a * 2", "a * a", "a - -a"])
def test_the_integer_fast_paths_still_check_the_size_of_the_result(source):
    refused(source, "limit-int-bits", Limits(max_int_bits=100), a=2**99)


def test_the_power_exponent_boundary_is_exact():
    assert run("2 ** n", n=64) == 2**64
    refused("2 ** n", "limit-pow-exponent", n=65)


def test_the_result_of_a_built_in_or_a_method_is_checked_too():
    refused("str(items)", "limit-string", Limits(max_string=10), items=list(range(10)))
    refused("s.upper()", "limit-string", Limits(max_string=5), s="abcdef")
    refused("sum(items)", "limit-int-bits", Limits(max_int_bits=100), items=[2**99, 2**99])


def test_a_twelve_digit_width_is_a_size_even_though_it_is_not_a_number_python_could_hold_as_text():
    refused("f'{x:>123456789012}'", "limit-string", x=1)
    refused("f'{x:.123456789012f}'", "limit-string", x=1.5)


def test_a_text_literal_in_an_f_string_is_checked_when_the_expression_is_compiled():
    with pytest.raises(TelLimitError) as raised:
        build("f'abcd'", limits=Limits(max_string=3))
    assert raised.value.code == "limit-string"


def test_the_evaluator_survives_running_out_of_stack():
    import inspect
    import sys

    expr = build("-" * 30 + "1")
    old = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(len(inspect.stack()) + 22)
        with pytest.raises(TelLimitError) as raised:
            expr.evaluate(MapScope())
    finally:
        sys.setrecursionlimit(old)
    assert raised.value.code == "limit-depth"
