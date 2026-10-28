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


def truthy(value: object) -> bool:
    """Truth of a value; an object that is not inert is true without asking it."""
    if type(value) in INERT_TYPES or isinstance(value, INERT_BASES):
        return bool(value)
    return True
