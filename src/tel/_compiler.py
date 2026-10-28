"""Turn a checked syntax tree into a tree of Python closures (`docs/language.md`, section 11).

Each node becomes a function `fn(lookup, run)` built once; evaluating is calling the root. `lookup`
is the scope's `lookup` method. `run` holds the state of one evaluation: the step count and the
slots a comprehension's loop variables live in. A compiled expression keeps no syntax tree: an
error site keeps its position as one packed int (`tel._spans.pack_position`).

Every rule here is a decision in the spec. Errors name types and names, never values from the
scope, so they are safe to log.
"""

import ast
import math
import operator
import types
from collections.abc import Callable, ItemsView, KeysView, Mapping, ValuesView
from typing import Any

from tel._builtins import FUNCTIONS, ISINSTANCE_TYPES, ITERATING
from tel._parser import _SINGLETONS, Parsed
from tel._spans import did_you_mean, pack_position, packed_span
from tel._values import (
    CONTAINERS,
    DENIED_BASES,
    DIRECT_ITERABLES,
    INERT_BASES,
    INERT_TYPES,
    PRIMITIVES,
    truthy,
)
from tel._whitelist import (
    BUILTIN_NAMES,
    DICT_METHODS,
    SEQUENCE_METHODS,
    STR_METHODS,
)
from tel.errors import TelError, TelEvaluationError, TelLimitError
from tel.limits import Limits, limit_code
from tel.origin import Origin


class Run:
    """The state of one evaluation. The defaults are class attributes: setting one makes an
    instance attribute, so a plain evaluation pays for nothing it does not use."""

    steps = 0
    slots: list[Any] | None = None
    scope: Any = None


_NO_KWARGS: Mapping[str, Any] = types.MappingProxyType({})  # shared: nothing ever changes it

Lookup = Callable[[str], Any]
Fn = Callable[[Lookup, Run], Any]


class Site:
    """What every closure of one compiled expression shares: the text, where it starts in its file,
    and the limits. Builds the errors."""

    __slots__ = ("limits", "origin", "text")

    def __init__(self, text: str, origin: Origin | None, limits: Limits) -> None:
        self.text, self.origin, self.limits = text, origin, limits

    def fail(
        self,
        pos: int,
        code: str,
        message: str,
        hint: str | None = None,
        cls: type[TelError] = TelEvaluationError,
    ) -> TelError:
        line, column, end = packed_span(self.text, pos)
        return cls(
            message,
            code=code,
            source=self.text,
            line=line,
            column=column,
            end_column=end,
            hint=hint,
            origin=self.origin,
        )

    def limit(self, pos: int, field: str, message: str) -> TelError:
        return self.fail(pos, limit_code(field), message, cls=TelLimitError)


def type_name(value: object) -> str:
    return type(value).__name__


def inert(value: object) -> bool:
    return type(value) in INERT_TYPES or isinstance(value, INERT_BASES)


# -- the step budget and sizes --------------------------------------------------------------------


def charge(S: Site, R: Run, pos: int, steps: int) -> None:
    R.steps += steps
    if R.steps > S.limits.max_steps:
        raise S.limit(
            pos,
            "max_steps",
            f"the expression is too expensive to evaluate (over {S.limits.max_steps} steps)",
        )


def measure(S: Site, R: Run, pos: int, value: Any, per: int = 1) -> None:
    """Check that `value` may be iterated, and charge its length (times `per`) to the budget."""
    if type(value) in DIRECT_ITERABLES or isinstance(value, (*CONTAINERS, Mapping)):
        size = len(value)
    else:
        raise S.fail(
            pos,
            "not-iterable",
            f"cannot iterate over a {type_name(value)}",
            "a list, tuple, dict, set, text or range",
        )
    charge(S, R, pos, size * per)
    if size > S.limits.max_sequence:
        raise S.limit(pos, "max_sequence", f"over {S.limits.max_sequence} items")


def items_of(value: Any) -> Any:
    """What to loop over: the built-in containers as they are, a subclass as a list."""
    return value if type(value) in DIRECT_ITERABLES else list(value)


def check_string(S: Site, pos: int, text: str) -> str:
    if len(text) > S.limits.max_string:
        raise S.limit(pos, "max_string", f"the text would be over {S.limits.max_string} characters")
    return text


def check_int(S: Site, pos: int, number: int) -> int:
    if number.bit_length() > S.limits.max_int_bits:
        raise S.limit(pos, "max_int_bits", "the number is too large")
    return number


def not_plain(S: Site, pos: int, value: Any, use: str) -> TelError:
    return S.fail(
        pos,
        "value-not-plain",
        f"a {type_name(value)} cannot be used {use}",
        "read one of its attributes instead",
    )


# -- operators ------------------------------------------------------------------------------------

_ARITHMETIC: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_SYMBOLS = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
    ast.FloorDiv: "//",
    ast.Mod: "%",
    ast.Pow: "**",
}
_COMPARISONS: dict[type[ast.cmpop], Callable[[Any, Any], Any]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}
_SEQUENCES = (str, list, tuple)


def arithmetic(S: Site, R: Run, pos: int, op: type[ast.operator], a: Any, b: Any) -> Any:
    """`a op b` with every check: plain operands, sizes before the work, the result's size after."""
    if not inert(a):
        raise not_plain(S, pos, a, "in arithmetic")
    if not inert(b):
        raise not_plain(S, pos, b, "in arithmetic")
    limits = S.limits
    if op is ast.Mod and isinstance(a, str):
        raise S.fail(pos, "percent-format", "'%' formatting is not available", "use an f-string")
    if op is ast.Pow:
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if abs(b) > limits.max_pow_exponent:
                raise S.limit(
                    pos, "max_pow_exponent", f"the exponent is over {limits.max_pow_exponent}"
                )
            if a not in (0, 1, -1) and abs(b) * math.log2(abs(a) or 1) > limits.max_int_bits:
                raise S.limit(pos, "max_int_bits", "the result of ** is too large")
    elif op is ast.Mult:
        for seq, count in ((a, b), (b, a)):
            if (
                isinstance(seq, _SEQUENCES)
                and isinstance(count, int)
                and not isinstance(count, bool)
            ):
                size = len(seq) * max(count, 0)
                if size > limits.max_sequence:
                    raise S.limit(
                        pos,
                        "max_sequence",
                        f"the repeated sequence would have over {limits.max_sequence} items",
                    )
                charge(S, R, pos, size >> 6)
    elif op is ast.Add and isinstance(a, _SEQUENCES) and type(a) is type(b):
        size = len(a) + len(b)
        if size > limits.max_sequence:
            raise S.limit(
                pos,
                "max_sequence",
                f"the joined sequence would have over {limits.max_sequence} items",
            )
        charge(S, R, pos, size >> 6)
    try:
        result = _ARITHMETIC[op](a, b)
    except ZeroDivisionError:
        raise S.fail(pos, "division-by-zero", "division by zero") from None
    except OverflowError:
        raise S.fail(pos, "number-too-large", "the number is too large") from None
    except TypeError, ArithmeticError:
        raise S.fail(
            pos,
            "bad-operand",
            f"cannot use {_SYMBOLS[op]} on {type_name(a)} and {type_name(b)}",
        ) from None
    if type(result) is int:
        check_int(S, pos, result)
    elif type(result) is str:
        check_string(S, pos, result)
    elif type(result) is complex:
        raise S.fail(pos, "bad-operand", "the result is not a real number")
    return result


_FAST_ARITHMETIC = frozenset({ast.Add, ast.Sub, ast.Mult})
_RICH = frozenset({ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE})


def arithmetic_closure(S: Site, pos: int, op: type[ast.operator], left: Fn, right: Fn) -> Fn:
    """`left op right`. Closures bind what they use as default arguments: a captured variable
    costs a 40-byte cell, a default costs 8, and no closure is ever called with extra arguments."""
    if op in _FAST_ARITHMETIC:

        def fast(L, R, left=left, right=right, plain=_ARITHMETIC[op], S=S, pos=pos, op=op):
            a = left(L, R)
            b = right(L, R)
            ta = type(a)
            tb = type(b)
            if (ta is int or ta is float) and (tb is int or tb is float):
                result = plain(a, b)
                if type(result) is int and result.bit_length() > S.limits.max_int_bits:
                    raise S.limit(pos, "max_int_bits", "the number is too large")
                return result
            return arithmetic(S, R, pos, op, a, b)

        return fast

    def general(L, R, left=left, right=right, S=S, pos=pos, op=op):
        return arithmetic(S, R, pos, op, left(L, R), right(L, R))

    return general


def arithmetic_with_number(S: Site, pos: int, op: type[ast.operator], left: Fn, k: Any) -> Fn:
    """`left op k` where `k` is a number written in the text: one closure instead of two."""

    def fast(L, R, left=left, k=k, plain=_ARITHMETIC[op], S=S, pos=pos, op=op):
        a = left(L, R)
        ta = type(a)
        if ta is int or ta is float:
            result = plain(a, k)
            if type(result) is int and result.bit_length() > S.limits.max_int_bits:
                raise S.limit(pos, "max_int_bits", "the number is too large")
            return result
        return arithmetic(S, R, pos, op, a, k)

    return fast


def arithmetic_name_number(
    S: Site, pos: int, op: type[ast.operator], name: str, name_pos: int, k: Any
) -> Fn:
    """`name op k`: the most common shape (`count + 1`), with the name read inside the closure."""

    def fast(L, R, name=name, name_pos=name_pos, k=k, plain=_ARITHMETIC[op], S=S, pos=pos, op=op):
        try:
            a = L(name)
        except KeyError:
            raise unknown_name(S, name_pos, R, name) from None
        ta = type(a)
        if ta is int or ta is float:
            result = plain(a, k)
            if type(result) is int and result.bit_length() > S.limits.max_int_bits:
                raise S.limit(pos, "max_int_bits", "the number is too large")
            return result
        return arithmetic(S, R, pos, op, a, k)

    return fast


def comparison_name_constant(
    S: Site, pos: int, op: type[ast.cmpop], name: str, name_pos: int, k: Any
) -> Fn:
    """`name op k` for ==, !=, <, <=, > and >=: the name is read inside the closure."""

    def with_constant(
        L, R, name=name, name_pos=name_pos, k=k, fn=_COMPARISONS[op], S=S, pos=pos, op=op
    ):
        try:
            a = L(name)
        except KeyError:
            raise unknown_name(S, name_pos, R, name) from None
        ta = type(a)
        if ta is type(k) or (ta is int or ta is float) and type(k) is not str:
            return fn(a, k)
        return compare_pair(S, pos, op, a, k)

    return with_constant


def comparison_closure(
    S: Site, pos: int, ops: list[type[ast.cmpop]], left: Fn, rights: list[Fn], nodes: list[ast.expr]
) -> Fn:
    if len(ops) > 1:

        def chain(L, R, left=left, ops=tuple(ops), rights=tuple(rights), S=S, pos=pos):
            a = left(L, R)
            for op, right in zip(ops, rights, strict=True):
                b = right(L, R)
                if not compare_pair(S, pos, op, a, b):
                    return False
                a = b
            return True

        return chain
    op, right, node = ops[0], rights[0], nodes[0]
    if op not in _RICH:

        def single(L, R, left=left, right=right, S=S, pos=pos, op=op):
            return compare_pair(S, pos, op, left(L, R), right(L, R))

        return single
    fn = _COMPARISONS[op]
    if isinstance(node, ast.Constant) and type(node.value) in (int, float, str):

        def with_constant(L, R, left=left, k=node.value, fn=fn, S=S, pos=pos, op=op):
            a = left(L, R)
            ta = type(a)
            if ta is type(k) or (ta is int or ta is float) and type(k) is not str:
                return fn(a, k)
            return compare_pair(S, pos, op, a, k)

        return with_constant

    def rich(L, R, left=left, right=right, fn=fn, S=S, pos=pos, op=op):
        a = left(L, R)
        b = right(L, R)
        ta = type(a)
        if ta is type(b) and (ta is int or ta is float or ta is str):
            return fn(a, b)
        return compare_pair(S, pos, op, a, b)

    return rich


def compare_pair(S: Site, pos: int, op: type[ast.cmpop], a: Any, b: Any) -> bool:
    """One comparison. `is` looks at identity; the rest touch plain values only."""
    if op is ast.Is or op is ast.IsNot:
        return bool(_COMPARISONS[op](a, b))
    if not inert(a):
        raise not_plain(S, pos, a, "in a comparison")
    if not inert(b):
        raise not_plain(S, pos, b, "in a comparison")
    if (op is ast.In or op is ast.NotIn) and not (
        type(b) in DIRECT_ITERABLES or isinstance(b, (*CONTAINERS, Mapping))
    ):
        raise S.fail(
            pos,
            "not-iterable",
            f"cannot test membership in a {type_name(b)}",
            "a list, tuple, dict, set, text or range",
        )
    try:
        return bool(_COMPARISONS[op](a, b))
    except TypeError:
        raise S.fail(
            pos, "bad-comparison", f"cannot compare {type_name(a)} and {type_name(b)}"
        ) from None


# -- attributes and indexing ----------------------------------------------------------------------


def read_attribute(S: Site, pos: int, base: Any, name: str) -> Any:
    if isinstance(base, Mapping):
        try:
            return base[name]
        except KeyError:
            hint = did_you_mean(name, [str(k) for k in base])
            raise S.fail(pos, "no-key", f"no key '{name}'", hint) from None
    if isinstance(base, DENIED_BASES):
        raise S.fail(pos, "attribute-denied", f"cannot read '{name}' of {type_name(base)}")
    if isinstance(base, PRIMITIVES):
        if callable(getattr(type(base), name, None)):
            raise S.fail(pos, "attribute-is-method", f"'{name}' is a method: call it, as {name}()")
        raise S.fail(pos, "no-attribute", f"{type_name(base)} has no readable attribute '{name}'")
    try:
        value = getattr(base, name)
    except AttributeError:
        public = [a for a in dir(type(base)) if not a.startswith("_")]
        public += [a for a in getattr(base, "__dict__", {}) if not a.startswith("_")]
        raise S.fail(
            pos,
            "no-attribute",
            f"{type_name(base)} has no attribute '{name}'",
            did_you_mean(name, public),
        ) from None
    except Exception as exc:  # the host's own property failed
        raise S.fail(
            pos, "attribute-failed", f"reading '{name}' failed ({type(exc).__name__})"
        ) from None
    if callable(value):
        raise S.fail(
            pos,
            "attribute-is-method",
            f"'{name}' is a method of {type_name(base)}: it cannot be read as a value",
        )
    return value


def index_value(S: Site, pos: int, base: Any, index: Any) -> Any:
    if isinstance(base, DENIED_BASES):
        raise S.fail(pos, "attribute-denied", f"cannot index a {type_name(base)}")
    if not inert(base):
        raise not_plain(S, pos, base, "with [ ]")
    if not inert(index) and type(index) is not slice:
        raise not_plain(S, pos, index, "as an index")
    try:
        return base[index]
    except (IndexError, KeyError, TypeError, ValueError, OverflowError) as exc:
        raise S.fail(
            pos, "bad-index", f"cannot index a {type_name(base)} with that ({type(exc).__name__})"
        ) from None


# -- calls ----------------------------------------------------------------------------------------

_VIEWS = (KeysView, ValuesView, ItemsView)
_WIDTH_METHODS = frozenset({"center", "ljust", "rjust", "zfill"})


def methods_for(base: Any) -> frozenset[str] | None:
    """The method names this kind of value may be called with."""
    if isinstance(base, str):
        return STR_METHODS
    if isinstance(base, (list, tuple)):
        return SEQUENCE_METHODS
    if isinstance(base, Mapping):
        return DICT_METHODS
    return None


def check_arguments(
    S: Site, pos: int, who: str, args: list[Any], kwargs: Mapping[str, Any]
) -> None:
    for value in (*args, *kwargs.values()):
        if not inert(value):
            raise S.fail(
                pos,
                "value-not-plain",
                f"{who}() takes lists, tuples, dicts, sets, text, ranges and plain values, "
                f"not a {type_name(value)}",
            )


def check_replace(S: Site, pos: int, base: str, args: list[Any]) -> None:
    """`replace` can grow a string a million-fold: decide from the sizes before doing it."""
    if len(args) >= 2 and isinstance(args[0], str) and isinstance(args[1], str):
        old, new = args[0], args[1]
        count = args[2] if len(args) > 2 and type(args[2]) is int else -1
        found = len(base) + 1 if old == "" else base.count(old)
        if count >= 0:
            found = min(found, count)
        if len(base) + found * (len(new) - len(old)) > S.limits.max_string:
            raise S.limit(
                pos, "max_string", f"the text would be over {S.limits.max_string} characters"
            )


def check_join(S: Site, pos: int, separator: str, items: Any) -> None:
    if all(isinstance(i, str) for i in items):
        total = sum(map(len, items)) + len(separator) * max(len(items) - 1, 0)
        if total > S.limits.max_string:
            raise S.limit(
                pos, "max_string", f"the text would be over {S.limits.max_string} characters"
            )


def call_method(
    S: Site, R: Run, pos: int, base: Any, name: str, args: list[Any], kwargs: Mapping[str, Any]
) -> Any:
    allowed = methods_for(base)
    if allowed is None:
        raise S.fail(
            pos,
            "method-not-for-type",
            f"cannot call .{name}() on a {type_name(base)}",
            "an expression may call the built-in functions and methods of text, lists and dicts",
        )
    if name not in allowed:
        raise S.fail(
            pos,
            "method-not-for-type",
            f"{type_name(base)}.{name}() is not available",
            "allowed: " + ", ".join(sorted(allowed)),
        )
    check_arguments(S, pos, name, args, kwargs)
    limits = S.limits
    if name in _WIDTH_METHODS and args and type(args[0]) is int and args[0] > limits.max_string:
        raise S.limit(pos, "max_string", f"the width is over {limits.max_string}")
    if name == "replace":
        check_replace(S, pos, base, args)
    elif name == "join" and args:
        measure(S, R, pos, args[0])
        if isinstance(args[0], (list, tuple)):
            check_join(S, pos, base, args[0])
    try:
        result = getattr(base, name)(*args, **kwargs)
    except TelError:
        raise
    except Exception as exc:
        raise S.fail(pos, "bad-call", f"{name}() failed ({type(exc).__name__})") from None
    if isinstance(result, _VIEWS):
        result = list(result)
    elif isinstance(result, str):
        check_string(S, pos, result)
        charge(S, R, pos, len(result) >> 6)
    return result


def call_builtin(
    S: Site,
    R: Run,
    pos: int,
    name: str,
    impl: Callable[..., Any],
    args: list[Any],
    kwargs: Mapping[str, Any],
) -> Any:
    check_arguments(S, pos, name, args, kwargs)
    if name in ITERATING:
        for value in args:
            if type(value) in DIRECT_ITERABLES or isinstance(value, (*CONTAINERS, Mapping)):
                measure(S, R, pos, value)
    try:
        result = impl(*args, **kwargs)
    except TelError:
        raise
    except Exception as exc:
        raise S.fail(pos, "bad-call", f"{name}() failed ({type(exc).__name__})") from None
    if type(result) is str:
        check_string(S, pos, result)
    elif type(result) is int:
        check_int(S, pos, result)
    return result


def make_range(S: Site, pos: int, args: list[Any], kwargs: Mapping[str, Any]) -> range:
    if kwargs or not 1 <= len(args) <= 3 or not all(type(a) is int for a in args):
        raise S.fail(pos, "bad-call", "range() takes whole numbers")
    try:
        result = range(*args)
    except ValueError:
        raise S.fail(pos, "bad-call", "range() step cannot be zero") from None
    try:
        size = len(result)
    except OverflowError:
        size = S.limits.max_range + 1
    if size > S.limits.max_range:
        raise S.limit(pos, "max_range", f"the range is over {S.limits.max_range} items")
    return result


# -- formatting -----------------------------------------------------------------------------------


def check_format_spec(S: Site, pos: int, spec: str) -> None:
    """A width or precision in a format spec makes text as long as the number says."""
    run = ""
    for char in spec + " ":
        if char.isdigit():
            run += char
        elif run:
            if len(run) > 9 or int(run) > S.limits.max_string:
                raise S.limit(
                    pos, "max_string", f"the text would be over {S.limits.max_string} characters"
                )
            run = ""


def format_value(
    S: Site, pos: int, value: Any, conversion: int, spec: str, checked: bool = False
) -> str:
    """Format one value. `checked` says the spec was already checked (it is written in the text)."""
    if not inert(value):
        raise not_plain(S, pos, value, "in text")
    if spec and not checked:
        check_format_spec(S, pos, spec)
    try:
        if conversion == 115:
            value = str(value)
        elif conversion == 114:
            value = repr(value)
        elif conversion == 97:
            value = ascii(value)
        return format(value, spec)
    except (ValueError, TypeError, OverflowError) as exc:
        raise S.fail(
            pos, "bad-format", f"cannot format a {type_name(value)} that way ({type(exc).__name__})"
        ) from None


# -- the compiler ---------------------------------------------------------------------------------


def count_nodes(node: ast.AST) -> int:
    """Nodes in a subtree, not counting operators and contexts. The parser records this on every
    part of a comprehension (`_tel_size`), so walking the tree again is only a fallback."""
    size: int | None = getattr(node, "_tel_size", None)
    return (
        size if size is not None else sum(1 for n in ast.walk(node) if type(n) not in _SINGLETONS)
    )


def unknown_name(S: Site, pos: int, R: Run, name: str) -> TelError:
    if name in BUILTIN_NAMES:
        return S.fail(pos, "function-as-value", f"'{name}' is a function: call it, as {name}(...)")
    names = getattr(R.scope, "names", None)
    known: list[str] = []
    if callable(names):
        try:  # a hint is a favour: the host's names() failing must not hide the real error
            known = [str(n) for n in names()]
        except Exception:
            known = []
    return S.fail(
        pos,
        "unknown-name",
        f"'{name}' is not defined",
        did_you_mean(name, known) or did_you_mean(name, sorted(BUILTIN_NAMES)),
    )


class Compiler:
    """Builds the closure for each node of a checked tree. A closure binds what it uses as
    default arguments (see `arithmetic_closure`) and holds no reference to the compiler."""

    def __init__(self, site: Site) -> None:
        self.S = site
        self.scopes: list[dict[str, int]] = []  # comprehension variables, innermost last
        self.slots = 0

    def compile(self, node: ast.AST) -> Fn:
        method = _DISPATCH.get(type(node))
        if method is None:  # the parser allows nothing else; defence in depth
            raise self.S.fail(
                pack_position(node), "disallowed-construct", f"{type(node).__name__} cannot run"
            )
        return method(self, node)

    # -- leaves ---------------------------------------------------------------------------------

    def node_Constant(self, node: ast.Constant) -> Fn:
        def constant(L, R, value=node.value):
            return value

        return constant

    def node_Name(self, node: ast.Name) -> Fn:
        for frame in reversed(self.scopes):
            if node.id in frame:
                return self.local(frame[node.id])

        def read(L, R, name=node.id, S=self.S, pos=pack_position(node)):
            try:
                return L(name)
            except KeyError:
                raise unknown_name(S, pos, R, name) from None

        return read

    @staticmethod
    def local(slot: int) -> Fn:
        def read_local(L, R, slot=slot):
            return R.slots[slot]

        return read_local

    # -- attributes and indexing ----------------------------------------------------------------

    def node_Attribute(self, node: ast.Attribute) -> Fn:
        def attribute(
            L, R, base=self.compile(node.value), name=node.attr, S=self.S, pos=pack_position(node)
        ):
            value = base(L, R)
            if type(value) is dict:
                try:
                    return value[name]
                except KeyError:
                    pass
            return read_attribute(S, pos, value, name)

        return attribute

    def node_Subscript(self, node: ast.Subscript) -> Fn:
        base, S, pos = self.compile(node.value), self.S, pack_position(node)
        if isinstance(node.slice, ast.Slice):
            parts = tuple(
                None if p is None else self.compile(p)
                for p in (node.slice.lower, node.slice.upper, node.slice.step)
            )

            def sliced(L, R, base=base, parts=parts, S=S, pos=pos):
                value = base(L, R)
                bounds = [None if p is None else p(L, R) for p in parts]
                for bound in bounds:
                    if bound is not None and not inert(bound):
                        raise not_plain(S, pos, bound, "as a slice bound")
                return index_value(S, pos, value, slice(*bounds))

            return sliced

        def subscript(L, R, base=base, index=self.compile(node.slice), S=S, pos=pos):
            return index_value(S, pos, base(L, R), index(L, R))

        return subscript

    # -- operators ------------------------------------------------------------------------------

    def node_UnaryOp(self, node: ast.UnaryOp) -> Fn:
        operand, S, pos = self.compile(node.operand), self.S, pack_position(node)
        if isinstance(node.op, ast.Not):

            def negate(L, R, operand=operand):
                return not truthy(operand(L, R))

            return negate

        def sign(L, R, operand=operand, minus=isinstance(node.op, ast.USub), S=S, pos=pos):
            value = operand(L, R)
            if not inert(value):
                raise not_plain(S, pos, value, "with a sign")
            try:
                return -value if minus else +value
            except TypeError:
                raise S.fail(
                    pos, "bad-operand", f"cannot use a sign on a {type_name(value)}"
                ) from None

        return sign

    def is_free_name(self, node: ast.AST) -> bool:
        """A name read from the scope: not a comprehension variable."""
        return isinstance(node, ast.Name) and not any(node.id in f for f in self.scopes)

    def node_BinOp(self, node: ast.BinOp) -> Fn:
        S, pos, op, right = self.S, pack_position(node), type(node.op), node.right
        if (
            op in _FAST_ARITHMETIC
            and isinstance(right, ast.Constant)
            and type(right.value) in (int, float)
        ):
            if isinstance(node.left, ast.Name) and self.is_free_name(node.left):
                left = node.left
                return arithmetic_name_number(S, pos, op, left.id, pack_position(left), right.value)
            return arithmetic_with_number(S, pos, op, self.compile(node.left), right.value)
        return arithmetic_closure(S, pos, op, self.compile(node.left), self.compile(right))

    def node_BoolOp(self, node: ast.BoolOp) -> Fn:
        def boolean(
            L,
            R,
            values=tuple(self.compile(v) for v in node.values),
            is_and=isinstance(node.op, ast.And),
        ):
            result = None
            for value in values:
                result = value(L, R)
                if truthy(result) != is_and:
                    return result
            return result

        return boolean

    def node_Compare(self, node: ast.Compare) -> Fn:
        S, pos = self.S, pack_position(node)
        ops = [type(op) for op in node.ops]
        right = node.comparators[0]
        if (
            len(ops) == 1
            and ops[0] in _RICH
            and isinstance(right, ast.Constant)
            and type(right.value) in (int, float, str)
            and isinstance(node.left, ast.Name)
            and self.is_free_name(node.left)
        ):
            left = node.left
            return comparison_name_constant(
                S, pos, ops[0], left.id, pack_position(left), right.value
            )
        rights = [self.compile(c) for c in node.comparators]
        return comparison_closure(S, pos, ops, self.compile(node.left), rights, node.comparators)

    def node_IfExp(self, node: ast.IfExp) -> Fn:
        def conditional(
            L,
            R,
            test=self.compile(node.test),
            body=self.compile(node.body),
            orelse=self.compile(node.orelse),
        ):
            return body(L, R) if truthy(test(L, R)) else orelse(L, R)

        return conditional

    # -- displays -------------------------------------------------------------------------------

    def elements(self, nodes: list[ast.expr]) -> Fn:
        parts = tuple(
            (
                isinstance(n, ast.Starred),
                self.compile(n.value if isinstance(n, ast.Starred) else n),
                pack_position(n),
            )
            for n in nodes
        )

        def build(L, R, parts=parts, S=self.S):
            out = []
            for spread, fn, pos in parts:
                value = fn(L, R)
                if spread:
                    measure(S, R, pos, value)
                    out.extend(items_of(value))
                else:
                    out.append(value)
            return out

        return build

    def node_List(self, node: ast.List) -> Fn:
        return self.elements(node.elts)

    def node_Tuple(self, node: ast.Tuple) -> Fn:
        def make(L, R, build=self.elements(node.elts)):
            return tuple(build(L, R))

        return make

    def node_Set(self, node: ast.Set) -> Fn:
        def make(L, R, build=self.elements(node.elts), S=self.S, pos=pack_position(node)):
            items = build(L, R)
            for item in items:
                if not inert(item):
                    raise not_plain(S, pos, item, "in a set")
            try:
                return set(items)
            except TypeError:
                raise S.fail(pos, "bad-key", "a set member must be hashable") from None

        return make

    def node_Dict(self, node: ast.Dict) -> Fn:
        pairs = tuple(
            (self.compile(k), self.compile(v), pack_position(k))
            for k, v in zip(node.keys, node.values, strict=True)
            if k is not None
        )

        def make(L, R, pairs=pairs, S=self.S, pos=pack_position(node)):
            out = {}
            for key, value, kpos in pairs:
                k = key(L, R)
                if not inert(k):
                    raise not_plain(S, kpos, k, "as a key")
                try:
                    out[k] = value(L, R)
                except TypeError:
                    raise S.fail(pos, "bad-key", f"a {type_name(k)} cannot be a key") from None
            return out

        return make

    # -- text -----------------------------------------------------------------------------------

    def node_JoinedStr(self, node: ast.JoinedStr) -> Fn:
        parts: list[Any] = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                parts.append(str(part.value))
            else:
                assert isinstance(part, ast.FormattedValue)
                parts.append(self.formatted(part))
        if all(isinstance(p, str) for p in parts):  # the parser already limited the literal
            return self.node_Constant(ast.Constant(value="".join(parts)))

        def joined(L, R, parts=tuple(parts), S=self.S, pos=pack_position(node)):
            limit = S.limits.max_string
            out = []
            total = 0
            for part in parts:
                text = part if type(part) is str else part(L, R)
                total += len(text)
                if total > limit:
                    raise S.limit(pos, "max_string", f"the text would be over {limit} characters")
                out.append(text)
            return "".join(out)

        return joined

    def formatted(self, node: ast.FormattedValue) -> Fn:
        pos, S, value = pack_position(node), self.S, self.compile(node.value)
        spec_node = node.format_spec
        assert spec_node is None or isinstance(spec_node, ast.JoinedStr)
        if spec_node is None or all(isinstance(v, ast.Constant) for v in spec_node.values):
            # the spec is written in the text: check it once, here, and not at every evaluation
            text = ""
            if spec_node is not None:
                text = "".join(
                    str(v.value) for v in spec_node.values if isinstance(v, ast.Constant)
                )
            if text:
                check_format_spec(S, pos, text)

            def format_static(
                L, R, value=value, conversion=node.conversion, text=text, S=S, pos=pos
            ):
                return format_value(S, pos, value(L, R), conversion, text, True)

            return format_static
        spec = self.node_JoinedStr(spec_node)

        def format_part(L, R, value=value, conversion=node.conversion, spec=spec, S=S, pos=pos):
            return format_value(S, pos, value(L, R), conversion, spec(L, R))

        return format_part

    # -- comprehensions -------------------------------------------------------------------------

    def bind(self, target: ast.AST) -> Callable[[list[Any], Any, Run], None]:
        """A function that stores one item into the slots for a loop target."""
        if isinstance(target, ast.Name):

            def one(slots, item, R, slot=self.scopes[-1][target.id]):
                slots[slot] = item

            return one
        assert isinstance(target, (ast.Tuple, ast.List))

        def unpack(
            slots,
            item,
            R,
            inner=tuple(self.bind(t) for t in target.elts),
            S=self.S,
            pos=pack_position(target),
        ):
            measure(S, R, pos, item)
            values = items_of(item)
            if len(values) != len(inner):
                raise S.fail(
                    pos, "bad-unpack", f"cannot unpack {len(values)} values into {len(inner)} names"
                )
            for store, value in zip(inner, values, strict=True):
                store(slots, value, R)

        return unpack

    def declare(self, target: ast.AST) -> None:
        if isinstance(target, ast.Name):
            self.scopes[-1][target.id] = self.slots
            self.slots += 1
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self.declare(element)

    def loop(
        self,
        iterable: Fn,
        store: Callable[..., Any],
        conditions: list[Fn],
        cost: int,
        pos: int,
        inner: Callable[..., Any],
    ) -> Callable[..., Any]:
        def run_loop(
            L,
            R,
            out,
            iterable=iterable,
            store=store,
            conditions=tuple(conditions),
            cost=cost,
            pos=pos,
            inner=inner,
            S=self.S,
        ):
            source = iterable(L, R)
            measure(S, R, pos, source, cost)  # the whole loop is paid for before it starts
            slots = R.slots
            for item in items_of(source):
                store(slots, item, R)
                for condition in conditions:
                    if not truthy(condition(L, R)):
                        break
                else:
                    inner(L, R, out)

        return run_loop

    def comprehension(
        self,
        node: Any,
        make: Callable[[], Any],
        elements: list[ast.expr],
        make_emit: Callable[..., Any],
    ) -> Fn:
        """A comprehension: the generators are compiled first (they declare the loop variables,
        and each iterable sees only the variables before it), then the element or key and value,
        then the loops are built from the innermost out."""
        frame: dict[str, int] = {}
        levels: list[list[Any]] = []
        for index, generator in enumerate(node.generators):
            iterable = self.compile(generator.iter)
            if index == 0:
                self.scopes.append(frame)
            self.declare(generator.target)
            store = self.bind(generator.target)
            conditions = [self.compile(c) for c in generator.ifs]
            cost = 1 + count_nodes(generator.target) + sum(count_nodes(c) for c in generator.ifs)
            levels.append([iterable, store, conditions, cost, pack_position(generator.iter)])
        compiled = [self.compile(e) for e in elements]
        self.scopes.pop()
        levels[-1][3] += sum(count_nodes(e) for e in elements)
        run = make_emit(*compiled)
        for iterable, store, conditions, cost, pos in reversed(levels):
            run = self.loop(iterable, store, conditions, cost, pos, run)

        def comprehension(L, R, make=make, run=run):
            out = make()
            run(L, R, out)
            return out

        return comprehension

    def node_ListComp(self, node: ast.ListComp) -> Fn:
        generators = node.generators
        if len(generators) == 1 and isinstance(generators[0].target, ast.Name):
            return self.simple_list_comprehension(node)

        def emitter(elt):
            def emit(L, R, out, elt=elt):
                out.append(elt(L, R))

            return emit

        return self.comprehension(node, list, [node.elt], emitter)

    def simple_list_comprehension(self, node: ast.ListComp) -> Fn:
        """`[element for name in iterable if ...]`, the common shape, as one closure."""
        generator = node.generators[0]
        target = generator.target
        assert isinstance(target, ast.Name)
        iterable = self.compile(generator.iter)  # sees the names bound before, not its own
        frame: dict[str, int] = {}
        self.scopes.append(frame)
        self.declare(target)
        conditions = tuple(self.compile(c) for c in generator.ifs)
        element = self.compile(node.elt)
        self.scopes.pop()
        cost = (
            1
            + count_nodes(target)
            + sum(count_nodes(c) for c in generator.ifs)
            + count_nodes(node.elt)
        )

        def comprehension(
            L,
            R,
            iterable=iterable,
            slot=frame[target.id],
            conditions=conditions,
            element=element,
            cost=cost,
            pos=pack_position(generator.iter),
            S=self.S,
        ):
            source = iterable(L, R)
            measure(S, R, pos, source, cost)  # the whole loop is paid for before it starts
            slots = R.slots
            out: list[Any] = []
            append = out.append
            if conditions:
                for item in items_of(source):
                    slots[slot] = item
                    for condition in conditions:
                        if not truthy(condition(L, R)):
                            break
                    else:
                        append(element(L, R))
            else:
                for item in items_of(source):
                    slots[slot] = item
                    append(element(L, R))
            return out

        return comprehension

    def node_SetComp(self, node: ast.SetComp) -> Fn:
        S, pos = self.S, pack_position(node)

        def emitter(elt):
            def emit(L, R, out, elt=elt, S=S, pos=pos):
                value = elt(L, R)
                if not inert(value):
                    raise not_plain(S, pos, value, "in a set")
                try:
                    out.add(value)
                except TypeError:
                    raise S.fail(pos, "bad-key", "a set member must be hashable") from None

            return emit

        return self.comprehension(node, set, [node.elt], emitter)

    def node_DictComp(self, node: ast.DictComp) -> Fn:
        S, pos = self.S, pack_position(node)

        def emitter(key, value):
            def emit(L, R, out, key=key, value=value, S=S, pos=pos):
                k = key(L, R)
                if not inert(k):
                    raise not_plain(S, pos, k, "as a key")
                try:
                    out[k] = value(L, R)
                except TypeError:
                    raise S.fail(pos, "bad-key", f"a {type_name(k)} cannot be a key") from None

            return emit

        return self.comprehension(node, dict, [node.key, node.value], emitter)

    # -- calls ----------------------------------------------------------------------------------

    def arguments(
        self, node: ast.Call
    ) -> Callable[[Lookup, Run], tuple[list[Any], dict[str, Any]]]:
        positional = tuple(
            (
                isinstance(a, ast.Starred),
                self.compile(a.value if isinstance(a, ast.Starred) else a),
                pack_position(a),
            )
            for a in node.args
        )
        keywords = tuple((k.arg, self.compile(k.value)) for k in node.keywords if k.arg is not None)

        def evaluate(L, R, positional=positional, keywords=keywords, S=self.S):
            args = []
            for spread, fn, pos in positional:
                value = fn(L, R)
                if spread:
                    measure(S, R, pos, value)
                    args.extend(items_of(value))
                else:
                    args.append(value)
            return args, {name: fn(L, R) for name, fn in keywords}

        return evaluate

    def node_Call(self, node: ast.Call) -> Fn:
        S, pos = self.S, pack_position(node)
        func = node.func
        plain = not node.keywords and not any(isinstance(a, ast.Starred) for a in node.args)
        if isinstance(func, ast.Attribute):
            base, name = self.compile(func.value), func.attr
            if plain:
                fns = tuple(self.compile(a) for a in node.args)

                def method_plain(L, R, base=base, name=name, fns=fns, S=S, pos=pos):
                    value = base(L, R)
                    return call_method(S, R, pos, value, name, [f(L, R) for f in fns], _NO_KWARGS)

                return method_plain

            def method(L, R, base=base, name=name, arguments=self.arguments(node), S=S, pos=pos):
                value = base(L, R)
                args, kwargs = arguments(L, R)
                return call_method(S, R, pos, value, name, args, kwargs)

            return method
        assert isinstance(func, ast.Name)
        name = func.id
        if name == "isinstance":
            target = ISINSTANCE_TYPES[node.args[1].id]  # type: ignore[attr-defined]

            def is_instance(L, R, subject=self.compile(node.args[0]), target=target):
                return issubclass(type(subject(L, R)), target)

            return is_instance
        if name == "range":
            arguments = self.arguments(node)

            def make(L, R, arguments=arguments, S=S, pos=pos):
                args, kwargs = arguments(L, R)
                check_arguments(S, pos, "range", args, kwargs)
                return make_range(S, pos, args, kwargs)

            return make
        if plain:
            fns = tuple(self.compile(a) for a in node.args)

            def builtin_plain(L, R, fns=fns, name=name, impl=FUNCTIONS[name], S=S, pos=pos):
                return call_builtin(S, R, pos, name, impl, [f(L, R) for f in fns], _NO_KWARGS)

            return builtin_plain

        def builtin(
            L, R, arguments=self.arguments(node), name=name, impl=FUNCTIONS[name], S=S, pos=pos
        ):
            args, kwargs = arguments(L, R)
            return call_builtin(S, R, pos, name, impl, args, kwargs)

        return builtin


_DISPATCH: dict[type, Callable[[Compiler, Any], Fn]] = {
    ast.Constant: Compiler.node_Constant,
    ast.Name: Compiler.node_Name,
    ast.Attribute: Compiler.node_Attribute,
    ast.Subscript: Compiler.node_Subscript,
    ast.UnaryOp: Compiler.node_UnaryOp,
    ast.BinOp: Compiler.node_BinOp,
    ast.BoolOp: Compiler.node_BoolOp,
    ast.Compare: Compiler.node_Compare,
    ast.IfExp: Compiler.node_IfExp,
    ast.List: Compiler.node_List,
    ast.Tuple: Compiler.node_Tuple,
    ast.Set: Compiler.node_Set,
    ast.Dict: Compiler.node_Dict,
    ast.JoinedStr: Compiler.node_JoinedStr,
    ast.ListComp: Compiler.node_ListComp,
    ast.GeneratorExp: Compiler.node_ListComp,  # evaluated eagerly: the result is a list
    ast.SetComp: Compiler.node_SetComp,
    ast.DictComp: Compiler.node_DictComp,
    ast.Call: Compiler.node_Call,
}


def compile_tree(parsed: Parsed, limits: Limits) -> tuple[Fn, int]:
    """The closure for a checked expression, and how many loop-variable slots it needs."""
    site = Site(parsed.text, parsed.origin, limits)
    compiler = Compiler(site)
    return compiler.compile(parsed.tree), compiler.slots
