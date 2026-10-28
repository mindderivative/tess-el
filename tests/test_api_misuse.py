"""The public API under misuse (step 3, phase 7: the `sharp-edges` review).

A host that passes the wrong thing has a bug, and the error should say what, at the call that is
wrong, not deep inside. What an expression author can do is covered by the other tests.
"""

import copy
import pickle

import pytest

import tel
from tel import Limits, MapScope, Origin, TelError


def build(text="x + 1", **kw):
    return tel.compile_expression(text, language="0.1", **kw)


# -- the text -------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [None, 123, b"1 + 1", bytearray(b"1"), ["1"], 1.5])
@pytest.mark.parametrize("compile_", [tel.compile_expression, tel.compile_template])
def test_text_that_is_not_a_str_is_a_type_error_that_says_so(compile_, bad):
    with pytest.raises(TypeError, match="must be a str, not"):
        compile_(bad, language="0.1")


class Evil(str):
    """A str subclass that records every method the library calls on it (a YAML loader that keeps
    round-trip information makes such strings)."""

    calls: list[str] = []

    def __getattribute__(self, name):
        Evil.calls.append(name)
        return super().__getattribute__(name)

    def __len__(self):
        Evil.calls.append("__len__")
        return 0

    def __str__(self):
        Evil.calls.append("__str__")
        return "hijacked"

    def __getitem__(self, item):
        Evil.calls.append("__getitem__")
        return "z"

    def __iter__(self):
        Evil.calls.append("__iter__")
        return iter("z")

    def __contains__(self, item):
        Evil.calls.append("__contains__")
        return True


@pytest.mark.parametrize(
    "text", ["x + 1", "x +", "__class__", "x * 2000000", "[i for i in range(3)]"]
)
def test_a_str_subclass_is_used_as_plain_text_and_none_of_its_methods_run(text):
    Evil.calls.clear()
    try:
        result = build(Evil(text)).evaluate(MapScope({"x": 1}))
    except TelError as error:
        assert type(error.source) is str and type(error.message) is str
    else:
        assert result is not None
    assert Evil.calls == []


def test_a_str_subclass_template_is_used_as_plain_text_too():
    Evil.calls.clear()
    template = tel.compile_template(Evil("a {{ x }} b"), language="0.1")
    assert template.evaluate(MapScope({"x": 1})) == "a 1 b" and type(template.source) is str
    assert Evil.calls == []


# -- the other arguments --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [{"max_steps": 5}, None, 100, "limits"])
def test_limits_that_are_not_a_limits_object_are_a_type_error_that_says_so(bad):
    with pytest.raises(TypeError, match="limits must be a tel.Limits"):
        build(limits=bad)
    with pytest.raises(TypeError, match="limits must be a tel.Limits"):
        tel.compile_template("{{ x }}", language="0.1", limits=bad)


@pytest.mark.parametrize("bad", [("f.yaml", 1, 1), "f.yaml", 7, {"line": 1}])
def test_an_origin_that_is_not_an_origin_object_is_a_type_error_that_says_so(bad):
    with pytest.raises(TypeError, match="origin must be a tel.Origin or None"):
        build(origin=bad)
    with pytest.raises(TypeError, match="origin must be a tel.Origin or None"):
        tel.compile_template("{{ x }}", language="0.1", origin=bad)


def test_the_language_is_still_a_version_error_not_a_type_error():
    with pytest.raises(tel.TelVersionError):
        tel.compile_expression("x", language=None)


def test_a_limit_can_be_raised_as_far_as_the_host_likes_and_that_is_the_hosts_choice():
    limits = Limits(max_steps=10**30, max_string=10**30)
    assert limits.max_steps == 10**30
    assert build("[i for i in range(10)]", limits=limits).evaluate(MapScope()) == list(range(10))


# -- the scope ------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [{"x": 1}, None, object(), [("x", 1)]])
def test_a_scope_without_lookup_says_to_wrap_a_dict_in_map_scope(bad):
    with pytest.raises(TypeError, match=r"lookup\(name\).*MapScope"):
        build().evaluate(bad)
    with pytest.raises(TypeError, match=r"lookup\(name\).*MapScope"):
        tel.compile_template("a {{ x }}", language="0.1").evaluate(bad)
    with pytest.raises(TypeError, match=r"lookup\(name\).*MapScope"):
        tel.compile_template("{{ x }}", language="0.1").evaluate(bad)


def test_a_scope_whose_names_fails_does_not_hide_the_error_it_was_helping_with():
    class BadNames:
        def lookup(self, name):
            raise KeyError(name)

        def names(self):
            raise RuntimeError("the host's names() is broken")

    with pytest.raises(TelError) as raised:
        build("nme").evaluate(BadNames())
    assert raised.value.code == "unknown-name" and raised.value.hint is None


def test_a_scope_whose_names_returns_things_that_are_not_text_still_gives_the_error():
    class OddNames:
        def lookup(self, name):
            raise KeyError(name)

        def names(self):
            return [1, None, ("a",), "nme2"]

    with pytest.raises(TelError) as raised:
        build("nme").evaluate(OddNames())
    assert raised.value.code == "unknown-name" and raised.value.hint == "did you mean 'nme2'"


# -- the objects ----------------------------------------------------------------------------------


def test_an_expression_and_a_template_are_their_own_copies():
    expression = build()
    template = tel.compile_template("a {{ x }}", language="0.1")
    for thing in (expression, template):
        assert copy.copy(thing) is thing
        assert copy.deepcopy(thing) is thing
        assert copy.deepcopy({"k": [thing]})["k"][0] is thing


def test_an_expression_cannot_be_pickled_and_says_how_to_send_one():
    expression = build("x + 1")
    template = tel.compile_template("a {{ x }}", language="0.1")
    for thing, name in ((expression, "an Expression"), (template, "a Template")):
        with pytest.raises(
            TypeError, match=rf"{name} cannot be pickled.*compile it again from `\.source`"
        ):
            pickle.dumps(thing)
    assert build(expression.source).evaluate(MapScope({"x": 1})) == 2  # what the message says


def test_the_names_of_an_expression_are_a_new_frozenset_each_time():
    expression = build("a + b")
    assert expression.names == {"a", "b"} and isinstance(expression.names, frozenset)
    assert expression.names is not expression.names


def test_an_origin_with_a_wrong_position_is_refused_where_it_is_made():
    with pytest.raises(TypeError):
        Origin("f", "1", 1)
    with pytest.raises(ValueError):
        Origin("f", 0, 1)
