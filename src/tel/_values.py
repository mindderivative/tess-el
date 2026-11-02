"""Which values an expression may touch, and how.

The *inert rule* (`docs/language.md`, section 5): operators, truth tests, subscripts, formatting,
iteration, membership tests and the built-in functions only touch plain values. An object of any
other class may carry code in `__add__`, `__eq__`, `__bool__`, `__len__`, `__getitem__` or
`__format__`, so an expression may only read its attributes. The rule is shallow: a list is plain,
and what the host put inside it is the host's.
"""

import datetime
import decimal
import enum
import types
from collections.abc import Mapping

NoneType = type(None)

#: Things whose attributes an expression may never read.
DENIED_BASES: tuple[type, ...] = (
    types.ModuleType,
    type,
    types.FunctionType,
    types.BuiltinFunctionType,
    types.MethodType,
    types.CodeType,
    types.FrameType,
    types.GeneratorType,
    types.TracebackType,
    types.CoroutineType,
    types.AsyncGeneratorType,
    types.MethodWrapperType,
    types.WrapperDescriptorType,
    types.MethodDescriptorType,
)

#: Built-in types whose attributes are methods, never data.
PRIMITIVES: tuple[type, ...] = (str, int, float, bool, list, tuple, dict, set, frozenset, NoneType)

#: The only things an expression iterates over or tests membership in.
CONTAINERS: tuple[type, ...] = (str, list, tuple, dict, set, frozenset, range)

_PLAIN: tuple[type, ...] = (bool, int, float, str, NoneType, *CONTAINERS)

#: Plain values, by class (subclasses and the other inert kinds are checked with `isinstance`).
INERT_BASES: tuple[type, ...] = (
    *_PLAIN,
    Mapping,
    datetime.date,
    datetime.time,
    datetime.timedelta,
    decimal.Decimal,
    enum.Enum,
)

#: The exact types that are inert: a set lookup is the fast path.
INERT_TYPES: frozenset[type] = frozenset(_PLAIN) | {
    datetime.date,
    datetime.datetime,
    datetime.time,
    datetime.timedelta,
    decimal.Decimal,
}

#: Containers that are iterated in place (the rest are copied to a list first).
DIRECT_ITERABLES: frozenset[type] = frozenset({list, tuple, str, range, dict, set, frozenset})


def is_inert(value: object) -> bool:
    return type(value) in INERT_TYPES or isinstance(value, INERT_BASES)


def is_container(value: object) -> bool:
    return type(value) in DIRECT_ITERABLES or isinstance(value, (*CONTAINERS, Mapping))


SCALARS: frozenset[type] = frozenset({int, float, str, bool, NoneType})
_SEQUENCE_TYPES = (list, tuple, set, frozenset)


class TooMany(Exception):
    """`foreign_inside` looked at more elements than it was allowed to."""


def foreign_inside(value: object, allowed: int) -> object:
    """The first thing inside the container `value` that is not a plain value (a host object), or
    `None` when there is none. Looks through nested lists, tuples, sets and dicts (keys and values)
    without calling any method of theirs, once per container (a cycle ends), and raises `TooMany`
    after `allowed` elements. A flat container of scalars is settled by one pass in C."""
    stack: list[object] = [value]
    members: list[object]
    seen: set[int] = set()
    looked = 0
    while stack:
        item = stack.pop()
        kind = type(item)
        if kind in SCALARS:
            continue
        if isinstance(item, _SEQUENCE_TYPES):
            if id(item) in seen:
                continue
            seen.add(id(item))
            if isinstance(item, list):
                members = list(list.__iter__(item))
            elif isinstance(item, tuple):
                members = list(tuple.__iter__(item))
            elif isinstance(item, set):
                members = list(set.__iter__(item))
            else:
                members = list(frozenset.__iter__(item))
        elif isinstance(item, dict):
            if id(item) in seen:
                continue
            seen.add(id(item))
            members = [*dict.keys(item), *dict.values(item)]
        elif not is_inert(item):
            return item
        else:
            continue  # a str subclass, a date, a Decimal, an Enum, a Mapping that is not a dict
        looked += len(members)
        if looked > allowed:
            raise TooMany
        if not set(map(type, members)) <= SCALARS:
            stack.extend(m for m in members if type(m) not in SCALARS)
    return None


def truthy(value: object) -> bool:
    """Truth of a value; an object that is not inert is true without asking it."""
    if type(value) in INERT_TYPES or isinstance(value, INERT_BASES):
        return bool(value)
    return True
