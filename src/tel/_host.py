"""What a host adds to the language: its own functions and its own methods.

The host lists them when it compiles; TEL validates the lists, copies them, and from then on asks
only this registry what may be called. A value is never asked what it can do (section 5).
"""

import keyword
import unicodedata
from collections.abc import Callable, Mapping
from typing import Any

from tel._values import DENIED_BASES
from tel._whitelist import (
    BUILTIN_NAMES,
    DICT_METHODS,
    FORMAT_METHODS,
    METHOD_NAMES,
    SEQUENCE_METHODS,
    STR_METHODS,
)


def _usable(name: Any, what: str) -> str:
    """The checks every host-chosen name passes: text, a plain name, nothing hidden or reserved."""
    if not isinstance(name, str):
        raise TypeError(f"a {what} name must be a str, not {type(name).__name__}")
    if not name.isidentifier():
        raise ValueError(f"{what} name {name!r} must be an identifier")
    if unicodedata.normalize("NFKC", name) != name:
        raise ValueError(
            f"{what} name {name!r} must be in normal form (NFKC), or it could not be written"
        )
    if name.startswith("_"):
        raise ValueError(f"{what} name {name!r} must not start with _ (private names are refused)")
    if keyword.iskeyword(name):
        raise ValueError(f"{what} name {name!r} is a Python keyword")
    return name


def _callable(value: Any, name: str) -> Callable[..., Any]:
    if not callable(value):
        raise TypeError(f"{name!r} must be callable, not {type(value).__name__}")
    return value  # type: ignore[no-any-return]


def _built_in_methods(kind: type) -> frozenset[str]:
    """The built-in method names of the whitelist that a value of this type already has."""
    found: frozenset[str] = frozenset()
    if issubclass(kind, str):
        found |= STR_METHODS
    if issubclass(kind, (list, tuple)):
        found |= SEQUENCE_METHODS
    if issubclass(kind, Mapping):
        found |= DICT_METHODS
    return found


def _check_functions(
    functions: Mapping[str, Callable[..., Any]] | None,
) -> dict[str, Callable[..., Any]]:
    """A validated copy of the host's functions."""
    if functions is None:
        return {}
    if not isinstance(functions, Mapping):
        raise TypeError(
            f"functions must be a mapping of name to callable, not {type(functions).__name__}"
        )
    own: dict[str, Callable[..., Any]] = {}
    for name, function in functions.items():
        _usable(name, "function")
        if name in BUILTIN_NAMES:
            raise ValueError(
                f"function name {name!r} is the name of a built-in function and cannot be replaced"
            )
        own[name] = _callable(function, name)
    return own


def _check_methods(
    methods: Mapping[type, Mapping[str, Callable[..., Any]]] | None,
) -> dict[type, dict[str, Callable[..., Any]]]:
    """A validated copy of the host's methods."""
    if methods is None:
        return {}
    if not isinstance(methods, Mapping):
        raise TypeError(
            f"methods must be a mapping of type to methods, not {type(methods).__name__}"
        )
    own: dict[type, dict[str, Callable[..., Any]]] = {}
    for kind, table in methods.items():
        if not isinstance(kind, type):
            raise TypeError(f"a methods key must be a class, not {type(kind).__name__}")
        if kind is object or issubclass(kind, DENIED_BASES):
            raise ValueError(
                f"methods cannot be registered for {kind.__name__}: "
                "its attributes are never readable"
            )
        if not isinstance(table, Mapping):
            raise TypeError(
                f"the methods for {kind.__name__} must be a mapping of name to callable, "
                f"not {type(table).__name__}"
            )
        covered = _built_in_methods(kind)
        mine: dict[str, Callable[..., Any]] = {}
        for name, method in table.items():
            _usable(name, "method")
            if name in FORMAT_METHODS:
                raise ValueError(
                    f"method name {name!r} cannot be registered: "
                    "a format string can read attributes (use an f-string)"
                )
            if name in covered:
                raise ValueError(
                    f"method name {name!r} is a built-in method of {kind.__name__} "
                    "and cannot be replaced"
                )
            mine[name] = _callable(method, name)
        own[kind] = mine
    return own


class Registry:
    """The host's functions and methods, validated and copied. Immutable once made."""

    __slots__ = ("call_names", "functions", "method_names", "methods")

    functions: dict[str, Callable[..., Any]]  # the host's functions, by name
    methods: dict[type, dict[str, Callable[..., Any]]]  # the host's methods, by type, then name
    call_names: frozenset[str]  # every name that may be called: the built-ins and the functions
    method_names: frozenset[str]  # every name that may follow a `.` in a call

    def __init__(
        self,
        functions: Mapping[str, Callable[..., Any]] | None,
        methods: Mapping[type, Mapping[str, Callable[..., Any]]] | None,
    ) -> None:
        own_functions = _check_functions(functions)
        own_methods = _check_methods(methods)
        object.__setattr__(self, "functions", own_functions)
        object.__setattr__(self, "methods", own_methods)
        object.__setattr__(self, "call_names", BUILTIN_NAMES | frozenset(own_functions))
        object.__setattr__(
            self, "method_names", METHOD_NAMES.union(*(t.keys() for t in own_methods.values()))
        )

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("a Registry is immutable")

    def method(self, receiver: Any, name: str) -> Callable[..., Any] | None:
        """The host's method `name` for this value: the nearest class in its type's base classes
        that registered it. The value itself is not asked anything."""
        if not self.methods:
            return None
        for kind in type(receiver).__mro__:
            table = self.methods.get(kind)
            if table is not None and name in table:
                found: Callable[..., Any] = table[name]
                return found
        return None


EMPTY = Registry(None, None)
