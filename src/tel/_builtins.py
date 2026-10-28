"""The built-in functions an expression may call (`docs/language.md`, section 6).

The names are `tel._whitelist.BUILTIN_NAMES`; a test pins that the two agree.
"""

from collections.abc import Callable
from typing import Any

#: Built-ins that take an iterable: it is bounded and charged to the step budget first.
ITERATING = frozenset(
    "min max sum sorted reversed enumerate zip any all list dict tuple set".split()
)


def _clamp(x: Any, low: Any, high: Any) -> Any:
    return max(low, min(high, x))


def _reversed(x: Any) -> list[Any]:
    return list(reversed(x))


def _enumerate(x: Any, start: Any = 0) -> list[Any]:
    return list(enumerate(x, start))


def _zip(*xs: Any) -> list[Any]:
    return list(zip(*xs, strict=False))


#: Built-ins that are called as they are. `range` and `isinstance` are compiled specially.
FUNCTIONS: dict[str, Callable[..., Any]] = {
    "len": len,
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "sum": sum,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "sorted": sorted,
    "reversed": _reversed,
    "enumerate": _enumerate,
    "zip": _zip,
    "any": any,
    "all": all,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "set": set,
    "clamp": _clamp,
}

#: The types `isinstance` may name.
ISINSTANCE_TYPES: dict[str, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
}
