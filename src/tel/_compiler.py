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


def _arithmetic_closure(S: Site, node: ast.BinOp, left: Fn, right: Fn) -> Fn:
    pos, op = pack_position(node), type(node.op)
    plain = _ARITHMETIC[op]
    maxbits = S.limits.max_int_bits
    if op in (ast.Add, ast.Sub, ast.Mult):

        def fast(L: Lookup, R: Run) -> Any:
            a = left(L, R)
            b = right(L, R)
            ta, tb = type(a), type(b)
            if (ta is int or ta is float) and (tb is int or tb is float):
                result = plain(a, b)
                if type(result) is int and result.bit_length() > maxbits:
                    raise S.limit(pos, "max_int_bits", "the number is too large")
                return result
            return arithmetic(S, R, pos, op, a, b)

        return fast

    def general(L: Lookup, R: Run) -> Any:
        return arithmetic(S, R, pos, op, left(L, R), right(L, R))

    return general


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


def check_arguments(S: Site, pos: int, who: str, args: list[Any], kwargs: dict[str, Any]) -> None:
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
    S: Site, R: Run, pos: int, base: Any, name: str, args: list[Any], kwargs: dict[str, Any]
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
    kwargs: dict[str, Any],
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


def make_range(S: Site, pos: int, args: list[Any], kwargs: dict[str, Any]) -> range:
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


def format_value(S: Site, pos: int, value: Any, conversion: int, spec: str) -> str:
    if not inert(value):
        raise not_plain(S, pos, value, "in text")
    if spec:
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
    return sum(1 for n in ast.walk(node) if type(n) not in _SINGLETONS)


class Compiler:
    """Builds the closure for each node of a checked tree."""

    def __init__(self, site: Site) -> None:
        self.S = site
        self.scopes: list[dict[str, int]] = []  # comprehension variables, innermost last
        self.slots = 0

    def compile(self, node: ast.AST) -> Fn:
        method = getattr(self, "node_" + type(node).__name__, None)
        if method is None:  # the parser allows nothing else; defence in depth
            raise self.S.fail(
                pack_position(node), "disallowed-construct", f"{type(node).__name__} cannot run"
            )
        return method(node)  # type: ignore[no-any-return]

    # -- leaves ---------------------------------------------------------------------------------

    def node_Constant(self, node: ast.Constant) -> Fn:
        value = node.value

        def constant(L: Lookup, R: Run) -> Any:
            return value

        return constant

    def node_Name(self, node: ast.Name) -> Fn:
        name, pos = node.id, pack_position(node)
        for frame in reversed(self.scopes):
            if name in frame:
                return self.local(frame[name])

        def read(L: Lookup, R: Run) -> Any:
            try:
                return L(name)
            except KeyError:
                raise self.unknown(pos, R, name) from None

        return read

    @staticmethod
    def local(slot: int) -> Fn:
        def read_local(L: Lookup, R: Run) -> Any:
            return R.slots[slot]  # type: ignore[index]

        return read_local

    def unknown(self, pos: int, R: Run, name: str) -> TelError:
        S = self.S
        if name in BUILTIN_NAMES:
            return S.fail(
                pos,
                "function-as-value",
                f"'{name}' is a function: call it, as {name}(...)",
            )
        names = getattr(R.scope, "names", None)
        known = [str(n) for n in names()] if callable(names) else []
        return S.fail(
            pos,
            "unknown-name",
            f"'{name}' is not defined",
            did_you_mean(name, known) or did_you_mean(name, sorted(BUILTIN_NAMES)),
        )

    # -- attributes and indexing ----------------------------------------------------------------

    def node_Attribute(self, node: ast.Attribute) -> Fn:
        base, name, S, pos = self.compile(node.value), node.attr, self.S, pack_position(node)

        def attribute(L: Lookup, R: Run) -> Any:
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
            parts = [
                None if p is None else self.compile(p)
                for p in (node.slice.lower, node.slice.upper, node.slice.step)
            ]

            def sliced(L: Lookup, R: Run) -> Any:
                value = base(L, R)
                bounds = [None if p is None else p(L, R) for p in parts]
                return index_value(S, pos, value, slice(*bounds))

            return sliced
        index = self.compile(node.slice)

        def subscript(L: Lookup, R: Run) -> Any:
            return index_value(S, pos, base(L, R), index(L, R))

        return subscript

    # -- operators ------------------------------------------------------------------------------

    def node_UnaryOp(self, node: ast.UnaryOp) -> Fn:
        operand, S, pos = self.compile(node.operand), self.S, pack_position(node)
        if isinstance(node.op, ast.Not):

            def negate(L: Lookup, R: Run) -> Any:
                return not truthy(operand(L, R))

            return negate
        minus = isinstance(node.op, ast.USub)

        def sign(L: Lookup, R: Run) -> Any:
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

    def node_BinOp(self, node: ast.BinOp) -> Fn:
        return _arithmetic_closure(self.S, node, self.compile(node.left), self.compile(node.right))

    def node_BoolOp(self, node: ast.BoolOp) -> Fn:
        values = [self.compile(v) for v in node.values]
        is_and = isinstance(node.op, ast.And)

        def boolean(L: Lookup, R: Run) -> Any:
            result: Any = None
            for value in values:
                result = value(L, R)
                if truthy(result) != is_and:
                    return result
            return result

        return boolean

    def node_Compare(self, node: ast.Compare) -> Fn:
        left, S, pos = self.compile(node.left), self.S, pack_position(node)
        ops = [type(op) for op in node.ops]
        rights = [self.compile(c) for c in node.comparators]
        if len(ops) == 1:
            op, right = ops[0], rights[0]

            def single(L: Lookup, R: Run) -> Any:
                a = left(L, R)
                b = right(L, R)
                ta = type(a)
                if (ta is int or ta is float) and type(b) is ta and op is ast.Lt:
                    return a < b
                return compare_pair(S, pos, op, a, b)

            return single

        def chain(L: Lookup, R: Run) -> Any:
            a = left(L, R)
            for op, right in zip(ops, rights, strict=True):
                b = right(L, R)
                if not compare_pair(S, pos, op, a, b):
                    return False
                a = b
            return True

        return chain

    def node_IfExp(self, node: ast.IfExp) -> Fn:
        test, body, orelse = (self.compile(n) for n in (node.test, node.body, node.orelse))

        def conditional(L: Lookup, R: Run) -> Any:
            return body(L, R) if truthy(test(L, R)) else orelse(L, R)

        return conditional

    # -- displays -------------------------------------------------------------------------------

    def elements(self, nodes: list[ast.expr]) -> Callable[[Lookup, Run], list[Any]]:
        S = self.S
        parts = [
            (isinstance(n, ast.Starred), self.compile(n.value if isinstance(n, ast.Starred) else n))
            for n in nodes
        ]
        positions = [pack_position(n) for n in nodes]

        def build(L: Lookup, R: Run) -> list[Any]:
            out: list[Any] = []
            for (spread, fn), pos in zip(parts, positions, strict=True):
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
        build = self.elements(node.elts)

        def make(L: Lookup, R: Run) -> Any:
            return tuple(build(L, R))

        return make

    def node_Set(self, node: ast.Set) -> Fn:
        build, S, pos = self.elements(node.elts), self.S, pack_position(node)

        def make(L: Lookup, R: Run) -> Any:
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
        S, pos = self.S, pack_position(node)
        pairs = [
            (self.compile(k), self.compile(v), pack_position(k))
            for k, v in zip(node.keys, node.values, strict=True)
            if k is not None
        ]

        def make(L: Lookup, R: Run) -> Any:
            out: dict[Any, Any] = {}
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
        S, pos = self.S, pack_position(node)
        parts: list[Any] = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                parts.append(str(part.value))
            else:
                assert isinstance(part, ast.FormattedValue)
                parts.append(self.formatted(part))
        if all(isinstance(p, str) for p in parts):
            literal = check_string(S, pos, "".join(parts))
            return self.node_Constant(ast.Constant(value=literal))
        limit = S.limits.max_string

        def joined(L: Lookup, R: Run) -> Any:
            out: list[str] = []
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
        value, S, pos = self.compile(node.value), self.S, pack_position(node)
        conversion = node.conversion
        spec = self.node_JoinedStr(node.format_spec) if node.format_spec is not None else None  # type: ignore[arg-type]

        def format_part(L: Lookup, R: Run) -> Any:
            text = spec(L, R) if spec is not None else ""
            return format_value(S, pos, value(L, R), conversion, text)

        return format_part

    # -- comprehensions -------------------------------------------------------------------------

    def bind(self, target: ast.AST) -> Callable[[list[Any], Any, Run], None]:
        """A function that stores one item into the slots for a loop target."""
        S, pos = self.S, pack_position(target)
        if isinstance(target, ast.Name):
            slot = self.scopes[-1][target.id]

            def one(slots: list[Any], item: Any, R: Run) -> None:
                slots[slot] = item

            return one
        assert isinstance(target, (ast.Tuple, ast.List))
        inner = [self.bind(t) for t in target.elts]

        def unpack(slots: list[Any], item: Any, R: Run) -> None:
            measure(S, R, pos, item)
            values = items_of(item)
            if len(values) != len(inner):
                raise S.fail(
                    pos,
                    "bad-unpack",
                    f"cannot unpack {len(values)} values into {len(inner)} names",
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
        store: Callable[..., None],
        conditions: list[Fn],
        cost: int,
        pos: int,
        inner: Callable[[Lookup, Run, Any], None],
    ) -> Callable[[Lookup, Run, Any], None]:
        S = self.S

        def run_loop(L: Lookup, R: Run, out: Any) -> None:
            source = iterable(L, R)
            measure(S, R, pos, source, cost)  # the whole loop is paid for before it starts
            slots = R.slots
            assert slots is not None
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
        make_emit: Callable[..., Callable[[Lookup, Run, Any], None]],
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

        def comprehension(L: Lookup, R: Run) -> Any:
            out = make()
            run(L, R, out)
            return out

        return comprehension

    def node_ListComp(self, node: ast.ListComp) -> Fn:
        def emitter(elt: Fn) -> Callable[[Lookup, Run, Any], None]:
            def emit(L: Lookup, R: Run, out: Any) -> None:
                out.append(elt(L, R))

            return emit

        return self.comprehension(node, list, [node.elt], emitter)

    node_GeneratorExp = node_ListComp  # evaluated eagerly: the result is a list

    def node_SetComp(self, node: ast.SetComp) -> Fn:
        S, pos = self.S, pack_position(node)

        def emitter(elt: Fn) -> Callable[[Lookup, Run, Any], None]:
            def emit(L: Lookup, R: Run, out: Any) -> None:
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

        def emitter(key: Fn, value: Fn) -> Callable[[Lookup, Run, Any], None]:
            def emit(L: Lookup, R: Run, out: Any) -> None:
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
        S = self.S
        positional = [
            (
                isinstance(a, ast.Starred),
                self.compile(a.value if isinstance(a, ast.Starred) else a),
                pack_position(a),
            )
            for a in node.args
        ]
        keywords = [(k.arg, self.compile(k.value)) for k in node.keywords if k.arg is not None]

        def evaluate(L: Lookup, R: Run) -> tuple[list[Any], dict[str, Any]]:
            args: list[Any] = []
            for spread, fn, pos in positional:
                value = fn(L, R)
                if spread:
                    measure(S, R, pos, value)
                    args.extend(items_of(value))
                else:
                    args.append(value)
            return args, {name: fn(L, R) for name, fn in keywords if name is not None}

        return evaluate

    def node_Call(self, node: ast.Call) -> Fn:
        S, pos = self.S, pack_position(node)
        func = node.func
        if isinstance(func, ast.Attribute):
            base, name, arguments = self.compile(func.value), func.attr, self.arguments(node)

            def method(L: Lookup, R: Run) -> Any:
                value = base(L, R)
                args, kwargs = arguments(L, R)
                return call_method(S, R, pos, value, name, args, kwargs)

            return method
        assert isinstance(func, ast.Name)
        name = func.id
        arguments = self.arguments(node)
        if name == "isinstance":
            target = ISINSTANCE_TYPES[node.args[1].id]  # type: ignore[attr-defined]
            subject = self.compile(node.args[0])

            def is_instance(L: Lookup, R: Run) -> Any:
                return issubclass(type(subject(L, R)), target)

            return is_instance
        if name == "range":

            def make(L: Lookup, R: Run) -> Any:
                args, kwargs = arguments(L, R)
                check_arguments(S, pos, "range", args, kwargs)
                return make_range(S, pos, args, kwargs)

            return make
        impl = FUNCTIONS[name]

        def builtin(L: Lookup, R: Run) -> Any:
            args, kwargs = arguments(L, R)
            return call_builtin(S, R, pos, name, impl, args, kwargs)

        return builtin


def compile_tree(parsed: Parsed, limits: Limits) -> tuple[Fn, int]:
    """The closure for a checked expression, and how many loop-variable slots it needs."""
    site = Site(parsed.text, parsed.origin, limits)
    compiler = Compiler(site)
    return compiler.compile(parsed.tree), compiler.slots
