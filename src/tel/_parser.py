"""Read an expression: parse it with `ast`, then check every node against the whitelist.

Nothing is ever `eval`ed. `parse` returns a `Parsed` holding the checked tree, which the evaluator
turns into something that runs (phase 4).
"""

import ast
import re
import threading
import warnings
from collections.abc import Callable
from typing import Any, NamedTuple

from tel._spans import did_you_mean, node_span, split_lines
from tel._whitelist import (
    ALLOWED_NODES,
    BUILTIN_NAMES,
    DISALLOWED_NODES,
    FORMAT_METHODS,
    ISINSTANCE_TYPES,
    METHOD_NAMES,
)
from tel.errors import TelError, TelLimitError, TelSyntaxError
from tel.limits import DEFAULT_LIMITS, Limits, limit_code
from tel.origin import Origin

# `ast.parse` reports some problems as warnings, and the warnings filter is process-wide, so
# reading is serialised: concurrent calls neither print warnings nor change each other's filters.
_READ_LOCK = threading.Lock()

_PLAIN_CONSTANTS = (type(None), bool, int, float, str)
_STATEMENT_WORDS = "TEL is an expression language: it has no statements or assignment"


class Parsed(NamedTuple):
    """An expression that has been read and checked."""

    tree: ast.expr  # the checked syntax tree; positions in it refer to `text`
    source: str  # the text as given
    text: str  # `source` without surrounding whitespace: what was parsed
    origin: Origin | None  # where `text` starts in its file (the origin moved past leading space)
    names: frozenset[str]  # the names the expression reads (not those a comprehension binds)
    nodes: int  # syntax-tree nodes, not counting operators and contexts


def parse(
    source: str,
    *,
    origin: Origin | None = None,
    limits: Limits = DEFAULT_LIMITS,
    functions: frozenset[str] = BUILTIN_NAMES,
) -> Parsed:
    """Read `source` as one expression. Raises `TelSyntaxError` or `TelLimitError`, never anything
    else. `functions` are the names that may be called (the built-ins unless a host adds more)."""
    if len(source) > limits.max_source:
        raise TelLimitError(
            f"the expression is {len(source)} characters; the limit is {limits.max_source}",
            code=limit_code("max_source"),
        )
    text = source.strip()
    lead = source[: len(source) - len(source.lstrip())]
    here = origin.advance(lead) if origin is not None else None
    if not text:
        raise TelSyntaxError(
            "the expression is empty", code="empty-expression", line=1, column=1, origin=here
        )
    _check_text(text, here)
    tree = _read(text, here, limits)
    checker = _Checker(text, here, limits, functions)
    try:
        checker.visit(tree, 1)
    except RecursionError:
        raise _too_deep(text, here, limits) from None
    assert isinstance(tree, ast.Expression)
    return Parsed(tree.body, source, text, here, frozenset(checker.names), checker.nodes)


def _too_deep(text: str, origin: Origin | None, limits: Limits) -> TelLimitError:
    return TelLimitError(
        f"the expression is nested more than {limits.max_depth} deep",
        code=limit_code("max_depth"),
        source=text,
        line=1,
        column=1,
        origin=origin,
    )


def _position(text: str, index: int) -> tuple[int, int]:
    """The 1-based line and column of a character index."""
    before = text[:index]
    lines = split_lines(before)
    return len(lines), len(lines[-1]) + 1


def _check_text(text: str, origin: Origin | None) -> None:
    """Refuse text Python cannot read at all: a null byte or a lone surrogate."""
    if "\x00" in text:
        index, what = text.index("\x00"), "a null byte"
    elif text.isascii():
        return
    else:
        try:
            text.encode("utf-8")
        except UnicodeEncodeError as exc:
            index, what = exc.start, "a lone surrogate (a character that cannot be encoded)"
        else:
            return
    line, column = _position(text, index)
    raise TelSyntaxError(
        f"the text contains {what}",
        code="invalid-text",
        source=text,
        line=line,
        column=column,
        end_column=column + 1,
        origin=origin,
    )


# The reader warns about two things only: a backslash that is not an escape, and a number written
# straight against a keyword (`1if`, `0x1for`). Text with neither is read without the (slower,
# process-wide) warnings guard. Any digit before a letter counts, which over-matches `x1y`.
_MAY_WARN = re.compile(r"\\|[0-9][A-Za-z_]")


def _parse_quietly(text: str) -> ast.Expression:
    """`ast.parse` in eval mode, without a sound: the warnings guard is skipped for text that
    cannot cause a warning."""
    if _MAY_WARN.search(text) is None:
        return ast.parse(text, mode="eval")
    with _READ_LOCK, warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ast.parse(text, mode="eval")


def reads_as_expression(text: str) -> bool:
    """Whether Python can read `text` as one expression (the whitelist is not applied). Templates
    use it to find where a `{{ }}` part ends."""
    if not text.strip():
        return False
    try:
        _parse_quietly(text.strip())
    except SyntaxError, ValueError, RecursionError, MemoryError:
        return False
    return True


def _read(text: str, origin: Origin | None, limits: Limits) -> ast.AST:
    try:
        return _parse_quietly(text)
    except SyntaxError as exc:
        raise _syntax_error(text, origin, limits, exc) from None
    except (RecursionError, MemoryError) as exc:
        if isinstance(exc, MemoryError) and "stack overflowed" not in str(exc):
            raise
        raise _too_deep(text, origin, limits) from None
    except ValueError as exc:  # a text that cannot be read in some other way
        raise TelSyntaxError(
            f"the text cannot be read: {exc}", code="invalid-text", source=text, origin=origin
        ) from None


def _syntax_error(text: str, origin: Origin | None, limits: Limits, exc: SyntaxError) -> TelError:
    lines = split_lines(text)
    line = min(max(exc.lineno or 1, 1), len(lines))
    width = len(lines[line - 1]) + 1
    column = min(max(exc.offset or 1, 1), width)
    end = exc.end_offset if exc.end_lineno in (None, exc.lineno) else None
    end_column = min(end, width) if end is not None and end > column else None
    position = dict(source=text, line=line, column=column, end_column=end_column, origin=origin)
    message = exc.msg or "invalid syntax"
    if message.startswith("too many nested parentheses"):
        return TelLimitError(
            f"the expression is nested more than {limits.max_depth} deep",
            code=limit_code("max_depth"),
            **position,  # type: ignore[arg-type]
        )
    if "integer string conversion" in message:
        return TelLimitError(
            "an integer in the text has too many digits to read",
            code=limit_code("max_int_bits"),
            **position,  # type: ignore[arg-type]
        )
    hint = None
    try:
        with _READ_LOCK, warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ast.parse(text, mode="exec")
        hint = _STATEMENT_WORDS
    except SyntaxError, ValueError, RecursionError, MemoryError:
        pass
    return TelSyntaxError(
        f"syntax error: {message}",
        code="syntax-error",
        hint=hint,
        **position,  # type: ignore[arg-type]
    )


class _Checker:
    """Walks the tree once. Every node is counted and its depth checked (operators and contexts
    are shared instances with no children: checked where they stand, not counted), its type must
    be on the whitelist, and the rules for names, attributes, calls and constants apply."""

    _RULES: dict[type[ast.AST], Callable[[_Checker, Any, int], None]] = {}

    def __init__(
        self, text: str, origin: Origin | None, limits: Limits, functions: frozenset[str]
    ) -> None:
        self.text, self.origin, self.limits, self.functions = text, origin, limits, functions
        self.names: set[str] = set()
        self._callee: ast.AST | None = None  # a call's function name: never read from the scope
        self.nodes = 0
        self._bound: list[set[str]] = []  # the names comprehensions bind, innermost last

    # -- errors -----------------------------------------------------------------------------

    def fail(
        self,
        node: ast.AST,
        code: str,
        message: str,
        *,
        cls: type[TelError] = TelSyntaxError,
        hint: str | None = None,
    ) -> TelError:
        line, column, end = node_span(self.text, node)
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

    def private_attribute(self, node: ast.AST, attr: str) -> TelError:
        message = f"the attribute '{attr}' is private (attributes starting with _ are not allowed)"
        return self.fail(node, "private-attribute", message)

    def limit(self, node: ast.AST, field: str, message: str) -> TelError:
        return self.fail(node, limit_code(field), message, cls=TelLimitError)

    def refuse(self, node: ast.AST) -> TelError:
        kind = type(node)
        named = DISALLOWED_NODES.get(kind)
        if named is not None:
            return self.fail(
                node, "disallowed-construct", f"{named} is not allowed in an expression"
            )
        return self.fail(
            node, "disallowed-construct", f"{kind.__name__} is not allowed in an expression"
        )

    # -- the walk ---------------------------------------------------------------------------

    def visit(self, node: ast.AST, depth: int) -> None:
        self.nodes += 1
        if depth > self.limits.max_depth:
            raise self.limit(
                node,
                "max_depth",
                f"the expression is nested more than {self.limits.max_depth} deep",
            )
        if self.nodes > self.limits.max_nodes:
            raise self.limit(
                node, "max_nodes", f"the expression has more than {self.limits.max_nodes} parts"
            )
        kind = type(node)
        rule = self._RULES.get(kind)
        if rule is not None:
            rule(self, node, depth)
        elif kind in _PLAIN_NODES:
            self.children(node, depth)
        else:
            raise self.refuse(node)

    def children(self, node: ast.AST, depth: int) -> None:
        depth += 1
        for field in type(node)._fields:
            value = getattr(node, field, None)
            if isinstance(value, ast.AST):
                if type(value) not in _SINGLETONS:
                    self.visit(value, depth)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST) and type(item) not in _SINGLETONS:
                        self.visit(item, depth)

    def is_bound(self, name: str) -> bool:
        return any(name in frame for frame in self._bound)

    # -- rules ------------------------------------------------------------------------------

    def _constant(self, node: ast.Constant, depth: int) -> None:
        value = node.value
        if type(value) not in _PLAIN_CONSTANTS:
            raise self.fail(
                node,
                "constant-type",
                f"a {type(value).__name__} value is not allowed in an expression",
            )
        if type(value) is int and value.bit_length() > self.limits.max_int_bits:
            raise self.limit(
                node, "max_int_bits", f"the number is over {self.limits.max_int_bits} bits"
            )
        if type(value) is str and len(value) > self.limits.max_string:
            raise self.limit(
                node, "max_string", f"the text is over {self.limits.max_string} characters"
            )

    def _name(self, node: ast.Name, depth: int) -> None:
        if isinstance(node.ctx, ast.Store):
            return  # a comprehension target: `_targets` has already checked and bound it
        if node is self._callee:
            return
        name = node.id
        if name.startswith("_") and not (name == "_" and self.is_bound("_")):
            raise self.fail(
                node,
                "private-name",
                f"the name '{name}' is private (names starting with _ are not visible)",
            )
        if not self.is_bound(name):
            self.names.add(name)

    def _attribute(self, node: ast.Attribute, depth: int) -> None:
        if node.attr.startswith("_"):
            raise self.private_attribute(node, node.attr)
        self.children(node, depth)

    def _compare(self, node: ast.Compare, depth: int) -> None:
        for op, right in zip(node.ops, node.comparators, strict=True):
            if isinstance(op, ast.Is | ast.IsNot) and not (
                isinstance(right, ast.Constant) and right.value in (None, True, False)
                and (right.value is None or isinstance(right.value, bool))
            ):  # fmt: skip
                raise self.fail(
                    node,
                    "is-operand",
                    "'is' only compares with None, True or False; use == for anything else",
                )
        self.children(node, depth)

    def _dict(self, node: ast.Dict, depth: int) -> None:
        for key, value in zip(node.keys, node.values, strict=True):
            if key is None:
                raise self.fail(value, "dict-unpack", "'**' in a dict display is not allowed")
        self.children(node, depth)

    def _binop(self, node: ast.BinOp, depth: int) -> None:
        right = node.right
        if (
            isinstance(node.op, ast.Pow)
            and isinstance(right, ast.Constant)
            and type(right.value) is int
            and right.value > self.limits.max_pow_exponent
        ):
            raise self.limit(
                right, "max_pow_exponent", f"the ** exponent is over {self.limits.max_pow_exponent}"
            )
        self.children(node, depth)

    def _call(self, node: ast.Call, depth: int) -> None:
        for keyword in node.keywords:
            if keyword.arg is None:
                raise self.fail(keyword.value, "call-unpack", "'**' in a call is not allowed")
            if keyword.arg.startswith("_"):
                raise self.fail(
                    keyword, "private-name", f"the argument name '{keyword.arg}' is private"
                )
        func = node.func
        if isinstance(func, ast.Name):
            bound = self.is_bound(func.id)
            if bound or func.id not in self.functions:
                raise self.fail(
                    func,
                    "call-not-function",
                    f"'{func.id}' is not a function you can call here",
                    hint=did_you_mean(func.id, sorted(self.functions)),
                )
            if func.id == "isinstance":
                self._isinstance(node)
            self._callee = func
        elif isinstance(func, ast.Attribute):
            if func.attr.startswith("_"):
                raise self.private_attribute(func, func.attr)
            if func.attr in FORMAT_METHODS:
                raise self.fail(
                    func,
                    "method-format",
                    f"str.{func.attr}() is not available (a format string can read attributes); "
                    "use an f-string",
                )
            if func.attr not in METHOD_NAMES:
                raise self.fail(
                    func,
                    "method-not-available",
                    f"the method '{func.attr}' is not available",
                    hint=did_you_mean(func.attr, sorted(METHOD_NAMES)),
                )
        else:
            raise self.fail(node, "call-target", "only a function or method can be called")
        self.children(node, depth)

    def _isinstance(self, node: ast.Call) -> None:
        args = node.args
        ok = (
            len(args) == 2
            and not node.keywords
            and isinstance(args[1], ast.Name)
            and args[1].id in ISINSTANCE_TYPES
            and not self.is_bound(args[1].id)
        )
        if not ok:
            raise self.fail(
                node,
                "isinstance-type",
                "isinstance compares with one of: " + ", ".join(sorted(ISINSTANCE_TYPES)),
            )

    def sized(self, node: ast.AST, depth: int) -> None:
        """Visit a part of a comprehension and record its node count on it: the compiler charges a
        loop for what its body costs and reads the number back instead of walking the tree again."""
        before = self.nodes
        self.visit(node, depth)
        node._tel_size = self.nodes - before  # type: ignore[attr-defined]

    def _comprehension_owner(self, node: Any, depth: int) -> None:
        """A list, set, dict or generator comprehension: its generators bind names, then its
        element sees them."""
        self._bound.append(set())
        try:
            for generator in node.generators:
                self.visit(generator, depth + 1)
            for field in type(node)._fields:
                if field != "generators":
                    value = getattr(node, field)
                    if isinstance(value, ast.AST):
                        self.sized(value, depth + 1)
        finally:
            self._bound.pop()

    def _generator(self, node: ast.comprehension, depth: int) -> None:
        if node.is_async:
            raise self.fail(
                node.iter, "comprehension-async", "async comprehensions are not allowed"
            )
        self.visit(node.iter, depth + 1)  # sees the names bound before this generator, not its own
        self._bound[-1] |= self._targets(node.target)
        self.sized(node.target, depth + 1)
        for condition in node.ifs:
            self.sized(condition, depth + 1)

    def _targets(self, target: ast.AST) -> set[str]:
        if isinstance(target, ast.Name):
            if target.id.startswith("_") and target.id != "_":
                raise self.fail(target, "private-name", f"the name '{target.id}' is private")
            return {target.id}
        if isinstance(target, ast.Tuple | ast.List):
            found: set[str] = set()
            for element in target.elts:
                found |= self._targets(element)
            return found
        raise self.fail(
            target, "comprehension-target", "a loop variable must be a name (or names in a tuple)"
        )


_Checker._RULES = {
    ast.Constant: _Checker._constant,
    ast.Name: _Checker._name,
    ast.Attribute: _Checker._attribute,
    ast.Compare: _Checker._compare,
    ast.Dict: _Checker._dict,
    ast.Call: _Checker._call,
    ast.BinOp: _Checker._binop,
    ast.ListComp: _Checker._comprehension_owner,
    ast.SetComp: _Checker._comprehension_owner,
    ast.GeneratorExp: _Checker._comprehension_owner,
    ast.DictComp: _Checker._comprehension_owner,
    ast.comprehension: _Checker._generator,
}

#: Operators and contexts: shared instances with no children, checked in place and not counted.
_SINGLETONS = frozenset(
    t
    for t in ALLOWED_NODES
    if issubclass(t, ast.expr_context | ast.operator | ast.unaryop | ast.boolop | ast.cmpop)
)
#: Allowed nodes that need no rule of their own: their children are walked.
_PLAIN_NODES = frozenset(ALLOWED_NODES) - _SINGLETONS - frozenset(_Checker._RULES)
