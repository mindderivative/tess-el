"""Templates (step 3, phase 6): text with `{{ }}` parts."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from reference.support import Trap

import tel
from tel import (
    Limits,
    MapScope,
    Origin,
    TelError,
    TelEvaluationError,
    TelLimitError,
    TelSyntaxError,
)


def build(text, **kw):
    return tel.compile_template(text, language="0.1", **kw)


def run(text, scope=None, **values):
    template = build(text)
    assert template is not None, text
    return template.evaluate(scope if scope is not None else MapScope(values))


def fails(text, code, scope=None, **values):
    with pytest.raises(TelError) as raised:
        run(text, scope, **values)
    assert raised.value.code == code, str(raised.value)
    return raised.value


# -- what is a template, and what it gives --------------------------------------------------------


def test_text_without_a_part_is_not_a_template():
    assert build("plain") is None
    assert build("") is None
    assert build("a } b { c }} d") is None
    assert build("{ x }") is None


def test_text_with_parts_is_text():
    assert run("Hello {{ name }}!", name="Ada") == "Hello Ada!"
    assert run("{{ n }} of {{ n * 2 }}", n=3) == "3 of 6"
    assert run("{{a}}{{b}}", a=1, b=2) == "12"
    assert run("  {{ x }}", x=3) == "  3"
    assert run("{{ x }}  ", x=3) == "3  "
    assert run("a }} b {{ x }} c }} d", x=1) == "a }} b 1 c }} d"


def test_a_template_that_is_exactly_one_part_keeps_the_type_of_its_value():
    assert run("{{ n }}", n=3) == 3
    assert run("{{ flag }}", flag=True) is True
    assert run("{{ nothing }}", nothing=None) is None
    assert run("{{ items }}", items=[1, 2]) == [1, 2]
    assert run("{{  n  }}", n=3) == 3
    assert run("{{n}}", n=3) == 3
    assert run("{{ n + 1 }}", n=3) == 4


@pytest.mark.parametrize(
    "value, text",
    [
        (None, ""),
        (True, "True"),
        (False, "False"),
        (0, "0"),
        (1.5, "1.5"),
        ("x", "x"),
        ([1, "a"], "[1, 'a']"),
    ],
)
def test_a_value_in_text_is_its_text_and_none_is_nothing(value, text):
    assert run("[{{ v }}]", v=value) == f"[{text}]"


def test_the_literal_text_is_taken_as_it_is():
    assert run("{{ x }} {{ y }}\n{{ x }}", x=1, y=2) == "1 2\n1"
    assert run("é{{ x }}ü", x=1) == "é1ü"
    assert run("100% {{ x }}", x=1) == "100% 1"


# -- where a part ends ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("{{ {'a': 2}['a'] }}", 2),
        ("{{ '}}' + 'x' }}", "}}x"),
        ('{{ "}}" + "x" }}', "}}x"),
        ("a {{ d['a'] }} b", "a 1 b"),
        ("{{ [x for x in [1, 2]] }}", [1, 2]),
        ("{{ {1: {2: 3}}[1] }}", {2: 3}),
        ("{{ {'a': {'b': 1}}['a'] }}", {"b": 1}),
        ("{{ f'{{x}}' }}", "{x}"),
        ("{{ f'{n}}}' }}", "3}"),
        ("{{ f\"{d['a']}\" }}", "1"),
        ("{{ {'a': 1}}}", {"a": 1}),
        ("x{{ {'a': 1}['a'] }}y", "x1y"),
        ("{{ '{{' }}", "{{"),
        ("literal {{ '{{' }} and {{ n }}", "literal {{ and 3"),
        ("{{ (1 +\n  2) }}", 3),
    ],
)
def test_a_closing_braces_inside_a_string_or_brackets_belongs_to_the_expression(text, expected):
    assert run(text, d={"a": 1}, n=3) == expected


def test_the_first_closing_that_reads_as_an_expression_ends_the_part():
    # the part is `x`; what follows is text, even if it looks like more of a part
    assert run("{{ x }} y }}", x=1) == "1 y }}"
    assert run("{{ x }}}}", x=1) == "1}}"


# -- errors in the template text ------------------------------------------------------------------


def test_a_part_that_is_never_closed_is_an_error_at_its_opening_braces():
    with pytest.raises(TelSyntaxError) as raised:
        build("Hello {{ name", origin=Origin("A_View.yaml", 4, 9))
    error = raised.value
    assert error.code == "template-unclosed"
    assert (error.line, error.column) == (4, 15)  # expr.py: column 14, 0-based
    assert str(error).startswith("A_View.yaml:4:15: ")


def test_an_empty_part_is_an_error_at_its_opening_braces():
    for text in ("a {{ }} b", "{{}}", "{{   }}", "{{\n}}"):
        with pytest.raises(TelSyntaxError) as raised:
            build(text)
        assert raised.value.code == "template-empty", text
    with pytest.raises(TelSyntaxError) as raised:
        build("ab {{ }}")
    assert (raised.value.line, raised.value.column) == (1, 4)


def test_a_part_that_is_not_an_expression_reports_its_own_syntax_error_in_the_file():
    with pytest.raises(TelSyntaxError) as raised:
        build("Total {{ 1 + }} items", origin=Origin("A.yaml", 3, 5))
    error = raised.value
    assert error.code == "syntax-error" and error.line == 3
    assert error.column >= 5 + len("Total {{ ")


def test_a_part_the_whitelist_refuses_is_refused_at_compile_time_with_its_position():
    with pytest.raises(TelSyntaxError) as raised:
        build("a {{ __class__ }} b", origin=Origin("V.yaml", 2, 10))
    error = raised.value
    assert error.code == "private-name"
    assert (error.line, error.column) == (2, 10 + len("a {{ "))


def test_the_second_part_is_placed_after_the_first_in_the_file():
    with pytest.raises(TelSyntaxError) as raised:
        build("{{ a }} and {{ _b }}", origin=Origin("V.yaml", 7, 3))
    assert (raised.value.line, raised.value.column) == (7, 3 + len("{{ a }} and {{ "))


def test_a_part_on_a_later_line_is_placed_on_that_line():
    with pytest.raises(TelSyntaxError) as raised:
        build("first line\nsecond {{ _x }}", origin=Origin("V.yaml", 5, 4))
    assert (raised.value.line, raised.value.column) == (6, len("second {{ ") + 1)


def test_the_language_version_is_required_and_checked():
    with pytest.raises(TypeError):
        tel.compile_template("{{ x }}")  # type: ignore[call-arg]
    with pytest.raises(tel.TelVersionError):
        tel.compile_template("{{ x }}", language="9.9")
    with pytest.raises(tel.TelVersionError):
        tel.compile_template("plain", language="9.9")  # even when it is not a template


# -- errors when it is evaluated ------------------------------------------------------------------


def test_an_error_inside_a_part_points_into_the_file():
    template = build("Hello {{ nme }}!", origin=Origin("A.yaml", 2, 5))
    with pytest.raises(TelEvaluationError) as raised:
        template.evaluate(MapScope({"name": "x"}))
    error = raised.value
    assert error.code == "unknown-name" and error.hint == "did you mean 'name'"
    assert (error.line, error.column, error.end_column) == (
        2,
        5 + len("Hello {{ "),
        5 + len("Hello {{ nme"),
    )


def test_an_object_that_is_not_plain_cannot_be_put_in_text():
    Trap.tripped.clear()
    error = fails("a {{ t }} b", "value-not-plain", t=Trap())
    assert Trap.tripped == [] and "Trap" in error.message
    assert (error.line, error.column) == (1, 6)


def test_a_part_that_is_one_whole_template_may_return_an_object():
    trap = Trap()
    assert run("{{ t }}", t=trap) is trap


def test_the_text_is_limited():
    fails("{{ s }}{{ s }}", "limit-string", s="x" * 600_000)
    assert len(run("{{ s }}{{ s }}", MapScope({"s": "x" * 400_000}))) == 800_000


def test_the_whole_text_is_limited_by_the_source_limit():
    with pytest.raises(TelLimitError) as raised:
        build("a" * 100 + "{{ x }}", limits=Limits(max_source=50))
    assert raised.value.code == "limit-source"


def test_the_parts_share_one_budget_of_steps():
    part = "{{ [i for i in range(10)] }}"  # 30 steps
    text = " ".join([part] * 4)
    limits = Limits(max_steps=130)
    assert build(text, limits=limits).evaluate(MapScope()) == " ".join(
        ["[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]"] * 4
    )
    with pytest.raises(TelLimitError) as raised:
        build(text, limits=Limits(max_steps=100)).evaluate(MapScope())
    assert raised.value.code == "limit-steps"


def test_the_budget_starts_again_for_every_evaluation():
    template = build(
        "{{ [i for i in range(10)] }}-{{ [i for i in range(10)] }}", limits=Limits(max_steps=60)
    )
    for _ in range(4):
        assert template.evaluate(MapScope()).startswith("[0")


def test_the_loop_variables_of_one_part_do_not_leak_into_the_next():
    assert run("{{ [i for i in range(2)] }}{{ [j for j in range(2)] }}") == "[0, 1][0, 1]"
    fails("{{ [i for i in range(2)] }}{{ i }}", "unknown-name")


# -- the object ------------------------------------------------------------------------------------


def test_a_template_describes_itself():
    template = build("Hello {{ name }}, {{ count + 1 }} new, {{ name }}")
    assert template.source == "Hello {{ name }}, {{ count + 1 }} new, {{ name }}"
    assert template.names == {"name", "count"}
    assert template.limits == tel.DEFAULT_LIMITS
    assert repr(template) == "Template('Hello {{ name }}, {{ count + 1 }} new, {{ name }}')"
    assert build("{{ x }}").names == {"x"}


def test_a_template_cannot_be_changed():
    template = build("{{ x }}")
    with pytest.raises(AttributeError):
        template.source = "other"
    with pytest.raises(AttributeError):
        del template.names


def test_a_template_evaluates_against_any_scope_and_from_many_threads():
    template = build("{{ a }}-{{ [b * 2 for b in items] }}")
    barrier = threading.Barrier(8)

    def work(k):
        barrier.wait()
        return [template.evaluate(MapScope({"a": k, "items": [k, 1]})) for _ in range(200)]

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(work, range(8)))
    for k, out in enumerate(results):
        assert all(r == f"{k}-[{2 * k}, 2]" for r in out)


def test_an_exception_from_the_scope_other_than_key_error_is_the_hosts():
    class Broken:
        def lookup(self, name):
            raise RuntimeError("the host's own bug")

    with pytest.raises(RuntimeError, match="the host's own bug"):
        build("a {{ x }}").evaluate(Broken())


def test_no_error_message_contains_a_value_from_the_scope():
    secret = "hunter2-xyzzy"
    for text in ("{{ int(s) }}", "a {{ s + 1 }}", "{{ s.nope }} b", "{{ s[100] }}"):
        template = build(text)
        with pytest.raises(TelError) as raised:
            template.evaluate(MapScope({"s": secret}))
        assert secret not in str(raised.value) and secret not in raised.value.render()


def test_a_deep_or_pathological_part_is_a_limit_error_and_never_a_crash():
    huge = Limits(max_source=1_000_000, max_depth=10_000, max_nodes=100_000)
    with pytest.raises(TelError):
        build("{{ " + "-" * 5000 + "1 }}", limits=huge)
    with pytest.raises(TelError):
        build("{{ " + "(" * 500 + "1" + ")" * 500 + " }}")


def test_many_candidate_endings_stay_fast():
    import time

    text = "{{ " + "x " + "}} " * 600 + "("
    start = time.perf_counter()
    try:
        build(text)
    except TelError:
        pass
    assert time.perf_counter() - start < 1.0


def test_parts_that_are_not_text_at_all_are_still_errors_not_crashes():
    for text in ("{{ \x00 }}", "{{ '\ud800' }}"):
        with pytest.raises(TelError):
            build(text)


@pytest.mark.parametrize(
    "text", ["Total {{ 'a' + }} items", "x {{ {1: }} y", "{{ f'{' }}", "{{ 'a' 'b' ) }}"]
)
def test_when_no_ending_reads_as_an_expression_the_first_endings_own_error_is_reported(text):
    with pytest.raises(TelSyntaxError) as raised:
        build(text, origin=Origin("A.yaml", 2, 3))
    assert raised.value.code == "syntax-error"
    assert raised.value.line == 2 and raised.value.column >= 3 + text.index("{{") + 2
