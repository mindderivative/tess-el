"""The fuzzer (step 7): random text and random programs, with the properties of the sandbox.

For every input TEL either gives a plain value or raises its own `TelError`; nothing else escapes,
nothing touches the `Trap` in the scope, nothing reaches a name outside the scope, and every input
ends quickly. The settings are fixed (derandomized, no database) so a failure repeats and the suite
takes a few seconds.
"""

import os
import time

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from reference.support import Plain, Trap

import tess_el
from tess_el import Limits, MapScope, TelError
from tess_el._values import is_inert

CEILING = 2.0  # seconds for one input; the real figure is milliseconds
FUZZ = settings(
    max_examples=int(os.environ.get("TEL_FUZZ_EXAMPLES", "400")),
    derandomize=True,
    database=None,
    deadline=None,
    suppress_health_check=list(HealthCheck),
)


def scope():
    return MapScope(
        {
            "a": 1,
            "b": 2.5,
            "n": 7,
            "s": "text",
            "t": "",
            "xs": [1, 2, 3],
            "ys": ["a", "b"],
            "d": {"k": 1, "j": [1, 2]},
            "flag": True,
            "nothing": None,
            "obj": Plain(),
            "trap": Trap(),
            "ws": [Plain(), Plain()],
        }
    )


def run(text, limits=None):
    """Compile and evaluate; return the value or the `TelError`. Anything else propagates."""
    Trap.tripped.clear()
    start = time.perf_counter()
    try:
        kw = {} if limits is None else {"limits": limits}
        outcome = tess_el.compile_expression(text, language="0.1", **kw).evaluate(scope())
    except TelError as error:
        outcome = error
    assert Trap.tripped == [], text
    assert time.perf_counter() - start < CEILING, text
    return outcome


def acceptable(outcome):
    """An error, or a value: plain, or a host object of the scope handed back as it is."""
    return isinstance(outcome, TelError | Plain | Trap) or is_inert(outcome)


def shape(value):
    """A value as comparable text: a host object is its class, since each run makes new ones."""
    if isinstance(value, list | tuple):
        return [shape(v) for v in value]
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items()}
    return value if is_inert(value) else type(value).__name__


# -- random text ----------------------------------------------------------------------------------

CHARS = st.sampled_from(
    list("abxn_.,:;()[]{}'\"\\#$?!=<>+-*/%@&|^~ \n\t01279") + ["é", "＿", "\x00"]
)


@FUZZ
@given(st.text(CHARS, max_size=60))
def test_random_text_is_a_value_or_a_tel_error(text):
    outcome = run(text)
    assert acceptable(outcome)


@FUZZ
@given(st.text(max_size=40))
def test_any_unicode_text_is_a_value_or_a_tel_error(text):
    outcome = run(text)
    assert acceptable(outcome)


# -- random programs from the allowed nodes -------------------------------------------------------

NAMES = ["a", "b", "n", "s", "t", "xs", "ys", "d", "flag", "nothing", "ws"]
ATOMS = st.one_of(
    st.sampled_from(NAMES),
    st.integers(-5, 50).map(str),
    st.sampled_from(["1.5", "None", "True", "False", "''", "'ab'", '"q"', "[]", "{}", "()"]),
    st.text("ab _é'", max_size=4).map(repr),
)
UNARY = st.sampled_from(["-{}", "not {}", "+{}", "({})", "[{}]", "str({})", "len({})", "abs({})"])
BINARY = st.sampled_from(
    ["{} + {}", "{} - {}", "{} * {}", "{} / {}", "{} // {}", "{} % {}", "{} ** {}", "{} < {}",
     "{} == {}", "{} in {}", "{} and {}", "{} or {}", "{}[{}]", "{} if {} else 0", "{} ? {} : 1",
     "max({}, {})", "sum([{}, {}])", "[{} for _ in {}]", "[v for v in {} if v > {}]",
     "{{{}: {}}}", "f'{{{}}}{}'", "{}.get({})", "{}.upper()", "{}[1:{}]"]
)  # fmt: skip


def programs():
    return st.recursive(
        ATOMS,
        lambda inner: st.one_of(
            st.tuples(UNARY, inner).map(lambda p: p[0].format(p[1])),
            st.tuples(BINARY, inner, inner).map(lambda p: p[0].format(p[1], p[2])),
        ),
        max_leaves=12,
    )


@FUZZ
@given(programs())
def test_a_random_program_is_a_plain_value_or_a_tel_error(text):
    outcome = run(text)
    assert acceptable(outcome)


FORBIDDEN = [
    ".__class__", ".__dict__", "._x", ".__init__.__globals__", "._secret",
    ".__class__.__mro__", ".__bases__",
]  # fmt: skip
FORBIDDEN_CALLS = ["__import__('os')", "eval('1')", "open('f')", "getattr(a, 'x')", "type(a)",
    "globals()", "(lambda: 1)()", "exec('1')", "compile('1','f','eval')"]  # fmt: skip


@FUZZ
@given(programs(), st.sampled_from(FORBIDDEN), st.sampled_from(NAMES))
def test_a_private_attribute_anywhere_is_refused_when_the_text_is_compiled(text, bad, name):
    refused = f"({text}) if flag else {name}{bad}"
    try:
        tess_el.compile_expression(refused, language="0.1")
    except TelError:
        return  # refused at compile time, as a private attribute must be
    raise AssertionError(f"compiled: {refused!r}")


@FUZZ
@given(programs(), st.sampled_from(FORBIDDEN_CALLS))
def test_a_forbidden_call_anywhere_is_never_run(text, call):
    for refused in (
        f"[{call}, {text}]",
        f"({text}) if flag else {call}",
        f"[{text} for _ in xs if {call}]",
    ):
        outcome = run(refused)
        assert isinstance(outcome, TelError), refused


@FUZZ
@given(programs())
def test_the_canonical_text_of_a_program_means_the_same_and_is_a_fixed_point(text):
    try:
        first = tess_el.compile_expression(text, language="0.1")
    except TelError:
        return
    again = tess_el.compile_expression(first.canonical, language="0.1")
    assert again.canonical == first.canonical
    a, b = run(text), run(first.canonical)
    if isinstance(a, TelError):
        assert isinstance(b, TelError) and a.code == b.code
    else:
        assert shape(a) == shape(b)


@FUZZ
@given(programs())
def test_a_tracked_evaluation_reads_a_subset_of_what_the_text_could_read(text):
    try:
        expression = tess_el.compile_expression(text, language="0.1")
        result = expression.evaluate_tracked(scope())
    except TelError:
        return
    assert result.reads <= expression.paths | expression.names
    assert result.names <= expression.names


# -- the limits hold for any size ---------------------------------------------------------------

DEEP = st.sampled_from(["-", "not ", "+", "~"]).flatmap(
    lambda op: st.integers(1, 3000).map(lambda n: op * n + "1")
)


@FUZZ
@given(DEEP)
def test_deep_nesting_is_a_depth_error_or_a_value_never_a_crash(text):
    big = Limits(max_source=100_000, max_depth=100_000, max_nodes=100_000)
    outcome = run(text, big)
    assert acceptable(outcome)
    outcome = run(text)
    assert acceptable(outcome)


@FUZZ
@given(st.integers(1, 400), st.integers(1, 400), st.integers(0, 12))
def test_loops_and_repeats_end_as_a_value_or_a_limit_error(n, m, power):
    for text in (
        f"[x for x in range({n}) for y in range({m})]",
        f"sum([x * y for x in range({n}) for y in range({m})])",
        f"'a' * {n} * {m}",
        f"[0] * {n} * {m} * {10**power}",
        f"{n} ** {m}",
        f"str({n} ** {power}) * {m}",
        f"{10**power} ** {n}",
    ):
        outcome = run(text)
        assert acceptable(outcome), text


PIECES = CHARS | st.sampled_from(["{{", "}}", "{{ ", " }}"])


# -- the other entry points -----------------------------------------------------------------------


@FUZZ
@given(st.text(CHARS, max_size=50), st.text(CHARS, max_size=30))
def test_a_random_header_and_key_are_a_repeater_or_a_tel_error(header, key):
    Trap.tripped.clear()
    try:
        repeater = tess_el.compile_repeater(header, key=key, name="W", language="0.1")
        repeater.reconcile(scope(), tess_el.RepeaterState())
    except TelError:
        pass
    assert Trap.tripped == []


@FUZZ
@given(st.text(CHARS, max_size=50), st.text(CHARS, max_size=40), st.text(CHARS, max_size=30))
def test_random_pieces_are_a_repeater_or_a_tel_error(names, items, key):
    Trap.tripped.clear()
    try:
        repeater = tess_el.compile_repeater_parts(names, items, key=key, name="W", language="0.1")
        repeater.items(scope())
    except TelError:
        pass
    assert Trap.tripped == []


@FUZZ
@given(st.lists(PIECES, max_size=30).map("".join))
def test_random_template_text_is_a_template_or_a_tel_error(text):
    Trap.tripped.clear()
    try:
        template = tess_el.compile_template(text, language="0.1")
        template.evaluate(scope())
        assert template.canonical is not None
    except TelError:
        pass
    assert Trap.tripped == []


@FUZZ
@given(st.lists(PIECES | st.sampled_from(["$a", "$b"]), max_size=24).map("".join))
def test_random_fill_text_is_filled_or_refused_and_a_filled_text_is_still_checked(text):
    try:
        filled = tess_el.fill(text, {"a": 1, "b": "x"})
    except ValueError, TelError:
        return
    run(filled)
    try:
        tess_el.fill_template(text, {"a": 1, "b": "x"})
    except ValueError, TelError:
        pass


VALUES = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(-(10**12), 10**12),
        st.floats(allow_nan=False, allow_infinity=False),
        st.text(max_size=8),
    ),
    lambda inner: st.one_of(
        st.lists(inner, max_size=4),
        st.lists(inner, max_size=4).map(tuple),
        st.dictionaries(st.one_of(st.text(max_size=4), st.integers(-9, 9)), inner, max_size=3),
    ),
    max_leaves=10,
)


@FUZZ
@given(VALUES)
def test_a_literal_reads_back_as_the_same_value(value):
    text = tess_el.literal(value)
    got = run(text)
    assert not isinstance(got, TelError), (value, text)
    assert repr(got) == repr(value)
    got = run(tess_el.fill("[$v, $v]", {"v": value}))
    assert repr(got) == repr([value, value])
