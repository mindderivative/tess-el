"""Conditions (step 5, phase 2): an expression read as yes or no, and the first that holds."""

import copy
import pickle

import pytest

import tel
from tel import Condition, MapScope, TelError, TelEvaluationError, TelSyntaxError, Tracked


def cond(text, **kw):
    return tel.compile_condition(text, language="0.1", **kw)


def scope(**values):
    return MapScope(values)


class Recording(MapScope):
    """An independent oracle: a scope that writes down every name it is asked for, in order."""

    __slots__ = ("asked",)

    def __init__(self, values):
        super().__init__(values)
        self.asked = []

    def lookup(self, name):
        self.asked.append(name)
        return super().lookup(name)


class Thing:
    """A host object: not a plain value."""


# -- what a condition gives -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "values", "expected"),
    [
        ("unread > 0", {"unread": 3}, True),
        ("unread > 0", {"unread": 0}, False),
        ("items", {"items": [1]}, True),
        ("items", {"items": []}, False),
        ("name", {"name": "x"}, True),
        ("name", {"name": ""}, False),
        ("count", {"count": 0}, False),
        ("value", {"value": None}, False),
        ("not flag", {"flag": False}, True),
        ("flag and other", {"flag": 1, "other": "a"}, True),
        ("d", {"d": {}}, False),
    ],
)
def test_a_condition_is_the_truth_of_its_value_as_a_plain_bool(text, values, expected):
    result = cond(text).holds(scope(**values))
    assert result is expected  # a real bool, never the value itself


def test_a_value_that_is_not_plain_is_refused():
    with pytest.raises(TelEvaluationError) as raised:
        cond("thing").holds(scope(thing=Thing()))
    assert raised.value.code == "value-not-plain"
    assert raised.value.line == 1 and raised.value.column == 1


def test_an_attribute_of_a_host_object_is_fine():
    class Box:
        count = 2

    assert cond("box.count > 1").holds(scope(box=Box())) is True


def test_a_bad_condition_fails_when_it_is_compiled():
    with pytest.raises(TelSyntaxError):
        cond("a +")
    with pytest.raises(TelSyntaxError) as raised:
        cond("")
    assert raised.value.code == "empty-expression"


def test_a_missing_name_is_the_usual_error_with_the_names_read():
    with pytest.raises(TelError) as raised:
        cond("a and b").holds_tracked(scope(a=1))
    assert raised.value.code == "unknown-name"
    assert raised.value.reads == {"a", "b"}


def test_the_host_registrations_and_the_origin_carry_over():
    c = cond("double(n) > 4", functions={"double": lambda n: n * 2})
    assert c.holds(scope(n=3)) is True
    with pytest.raises(TelError) as raised:
        cond("n / 0", origin=tel.Origin(file="f.yaml", line=7, column=5)).holds(scope(n=1))
    assert (raised.value.file, raised.value.line) == ("f.yaml", 7)


def test_the_methods_and_the_limits_carry_over():
    class Price:
        pass

    c = cond("p.big()", methods={Price: {"big": lambda p: True}})
    assert c.holds(scope(p=Price())) is True
    with pytest.raises(tel.TelLimitError) as raised:
        cond("a + b", limits=tel.Limits(max_source=3))
    assert raised.value.code == "limit-source"


def test_the_language_version_is_checked():
    with pytest.raises(tel.TelVersionError):
        tel.compile_condition("a", language="9.9")


# -- tracking -------------------------------------------------------------------------------------


def test_a_tracked_condition_reports_the_paths_it_read():
    result = cond("a.b > 0 or c").holds_tracked(scope(a=type("A", (), {"b": 0})(), c=1))
    assert isinstance(result, Tracked)
    assert result.value is True
    assert result.reads == {"a.b", "c"}


def test_a_short_circuit_reads_only_what_it_needed():
    result = cond("a or b").holds_tracked(scope(a=1, b=2))
    assert result.reads == {"a"}


def test_the_names_and_paths_of_a_condition_come_from_its_expression():
    c = cond("a.b and c")
    assert c.names == {"a", "c"}
    assert c.paths == {"a.b", "c"}


# -- the chain ------------------------------------------------------------------------------------


def chain(*texts):
    return [cond(t) for t in texts]


def test_select_gives_the_index_of_the_first_condition_that_holds():
    conds = chain("a", "b", "c")
    assert tel.select(conds, scope(a=0, b=1, c=1)) == 1
    assert tel.select(conds, scope(a=1, b=1, c=1)) == 0
    assert tel.select(conds, scope(a=0, b=0, c=1)) == 2


def test_select_gives_none_when_nothing_holds_that_is_the_else():
    assert tel.select(chain("a", "b"), scope(a=0, b=0)) is None
    assert tel.select([], scope()) is None


def test_select_never_asks_about_a_condition_after_the_winner():
    rec = Recording({"a": 0, "b": 1, "c": 1})
    assert tel.select(chain("a", "b", "c"), rec) == 1
    assert rec.asked == ["a", "b"]  # `c` is not even looked up


def test_a_condition_after_the_winner_may_be_broken_without_harm():
    assert tel.select(chain("a", "missing"), scope(a=1)) == 0


def test_a_condition_before_the_winner_that_fails_is_an_error():
    with pytest.raises(TelError) as raised:
        tel.select(chain("missing", "a"), scope(a=1))
    assert raised.value.code == "unknown-name"


def test_select_tracked_reports_every_condition_tested_up_to_the_winner():
    result = tel.select_tracked(chain("a > 1", "b", "c"), scope(a=0, b=1, c=1))
    assert isinstance(result, Tracked)
    assert result.value == 1
    assert result.reads == {"a", "b"}  # `a` too: if it flips, the winner changes


def test_select_tracked_with_no_winner_reads_every_condition():
    result = tel.select_tracked(chain("a", "b.c"), scope(a=0, b=type("B", (), {"c": 0})()))
    assert result.value is None
    assert result.reads == {"a", "b.c"}


def test_an_error_in_a_chain_carries_the_reads_of_the_earlier_conditions_too():
    with pytest.raises(TelError) as raised:
        tel.select_tracked(chain("a", "b.x"), scope(a=0, b=1))
    assert raised.value.reads == {"a", "b.x"}


def test_a_chain_that_is_not_made_of_conditions_is_a_type_error():
    with pytest.raises(TypeError, match="Condition"):
        tel.select(["a"], scope(a=1))
    with pytest.raises(TypeError, match="Condition"):
        tel.select_tracked(["a"], scope(a=1))


def test_a_chain_that_is_a_single_condition_is_a_type_error_that_says_so():
    with pytest.raises(TypeError, match="sequence of Condition"):
        tel.select(cond("a"), scope(a=1))
    with pytest.raises(TypeError, match="sequence of Condition"):
        tel.select_tracked(cond("a"), scope(a=1))


def test_a_string_is_not_a_chain():
    with pytest.raises(TypeError, match="Condition objects, not str"):
        tel.select("a", scope(a=1))


def test_a_generator_is_read_once_and_only_as_far_as_the_winner():
    seen = []

    def gen():
        for text in ("a", "b", "c"):
            seen.append(text)
            yield cond(text)

    assert tel.select(gen(), scope(a=0, b=1, c=1)) == 1
    assert seen == ["a", "b"]


# -- the object -----------------------------------------------------------------------------------


def test_a_condition_is_immutable_and_cannot_be_pickled():
    c = cond("a")
    assert isinstance(c, Condition)
    with pytest.raises(AttributeError):
        c.expression = None
    with pytest.raises(AttributeError):
        del c.expression
    with pytest.raises(TypeError):
        pickle.dumps(c)
    assert copy.copy(c) is c and copy.deepcopy(c) is c
    assert repr(c) == "Condition('a')"


def test_a_condition_keeps_its_text():
    c = cond("  a > 1  ")
    assert c.source == "  a > 1  " and c.text == "a > 1"
