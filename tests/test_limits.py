import dataclasses
import math

import pytest

from tel import DEFAULT_LIMITS, Limits
from tel.limits import limit_code

DEFAULTS = {
    "max_source": 2_000,
    "max_depth": 40,
    "max_nodes": 1_000,
    "max_steps": 200_000,
    "max_range": 100_000,
    "max_sequence": 1_000_000,
    "max_pow_exponent": 64,
    "max_int_bits": 4_096,
    "max_string": 1_000_000,
}
FIELDS = list(DEFAULTS)


def test_the_defaults_are_the_documented_ones():
    assert dataclasses.asdict(Limits()) == DEFAULTS
    assert DEFAULT_LIMITS == Limits()
    assert [f.name for f in dataclasses.fields(Limits)] == FIELDS


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("bad", [0, -1, -(10**9)])
def test_a_limit_below_one_is_refused_so_nothing_turns_a_limit_off(field, bad):
    with pytest.raises(ValueError, match=field):
        Limits(**{field: bad})


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("bad", [None, 1.5, math.inf, float("nan"), "5", True, False, [1]])
def test_a_limit_that_is_not_an_int_is_refused(field, bad):
    with pytest.raises(TypeError, match=field):
        Limits(**{field: bad})


@pytest.mark.parametrize("field", FIELDS)
def test_any_positive_int_is_accepted(field):
    assert getattr(Limits(**{field: 1}), field) == 1
    assert getattr(Limits(**{field: 10**12}), field) == 10**12


def test_limits_are_keyword_only_so_two_numbers_cannot_be_swapped():
    with pytest.raises(TypeError):
        Limits(2_000, 40)  # type: ignore[misc]


def test_limits_are_frozen_hashable_and_replaceable():
    limits = Limits(max_steps=500)
    with pytest.raises(dataclasses.FrozenInstanceError):
        limits.max_steps = 1  # type: ignore[misc]
    assert hash(limits) == hash(Limits(max_steps=500))
    assert dataclasses.replace(limits, max_depth=3).max_depth == 3


def test_replace_cannot_smuggle_in_a_bad_value():
    with pytest.raises(ValueError):
        dataclasses.replace(Limits(), max_depth=0)


def test_an_unknown_limit_is_an_error_not_ignored():
    with pytest.raises(TypeError):
        Limits(max_stepz=5)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "field, code",
    [
        ("max_source", "limit-source"),
        ("max_depth", "limit-depth"),
        ("max_nodes", "limit-nodes"),
        ("max_steps", "limit-steps"),
        ("max_range", "limit-range"),
        ("max_sequence", "limit-sequence"),
        ("max_pow_exponent", "limit-pow-exponent"),
        ("max_int_bits", "limit-int-bits"),
        ("max_string", "limit-string"),
    ],
)
def test_each_limit_has_a_stable_error_code(field, code):
    assert limit_code(field) == code


def test_limit_code_refuses_a_name_that_is_not_a_limit():
    with pytest.raises(ValueError):
        limit_code("max_nothing")
