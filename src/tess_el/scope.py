"""What an expression reads its names from."""

from collections.abc import Iterable, Mapping
from typing import Any, Protocol


class Scope(Protocol):
    """The caller's side of evaluation. TEL asks it for names and never touches anything else.

    `lookup` returns the value of a name or raises `KeyError`. `names` is optional: with it an
    "unknown name" error can suggest the nearest name. A scope returns plain values: a host with
    reactive types unwraps them in `lookup`. Any other exception from `lookup` is the host's bug
    and propagates unchanged.
    """

    def lookup(self, name: str) -> Any: ...

    def names(self) -> Iterable[str]: ...


class MapScope:
    """A scope over a mapping: for plain values, tests, and standalone use."""

    __slots__ = ("values",)

    def __init__(self, values: Mapping[str, Any] | None = None) -> None:
        self.values = dict(values or {})

    def lookup(self, name: str) -> Any:
        return self.values[name]

    def names(self) -> list[str]:
        return list(self.values)
