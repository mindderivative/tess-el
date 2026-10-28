"""Checks on what a host passes to the public functions, so a mistake is named where it is made."""

from typing import Any

from tel.limits import Limits
from tel.origin import Origin


def as_text(value: Any, what: str = "the text") -> str:
    """`value` as an exact `str`. A subclass (a YAML loader that keeps round-trip information
    makes them) is copied with `str.__str__`, which runs none of its methods."""
    if type(value) is str:
        return value
    if issubclass(type(value), str):
        return str.__str__(value)
    raise TypeError(f"{what} must be a str, not {type(value).__name__}")


def check_limits(limits: Any) -> Limits:
    if not isinstance(limits, Limits):
        raise TypeError(f"limits must be a tel.Limits, not {type(limits).__name__}")
    return limits


def check_origin(origin: Any) -> Origin | None:
    if origin is not None and not isinstance(origin, Origin):
        raise TypeError(f"origin must be a tel.Origin or None, not {type(origin).__name__}")
    return origin


def no_lookup() -> TypeError:
    return TypeError(
        "the scope needs a lookup(name) method that returns the value or raises KeyError; "
        "wrap a dict in tel.MapScope(...)"
    )
