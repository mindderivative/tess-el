"""Read an expression: parse it with `ast`, then check every node against the whitelist.

Nothing is ever `eval`ed. `parse` returns a `Parsed` holding the checked tree, which the evaluator
turns into something that runs (phase 4).
"""

import ast
import threading
import warnings
from collections.abc import Callable
from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class Parsed:
    """An expression that has been read and checked."""

    tree: ast.expr  # the checked syntax tree; positions in it refer to `text`
    source: str  # the text as given
    text: str  # `source` without surrounding whitespace: what was parsed
    origin: (
        Origin | None
    )  # where `text` starts in its file (the given origin moved past leading whitespace)
    names: frozenset[str]  # the names the expression reads (not those a comprehension binds)
    nodes: int  # nodes in the syntax tree


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
    for index, char in enumerate(text):
        what = None
        if char == "\x00":
            what = "a null byte"
        elif "\ud800" <= char <= "\udfff":
            what = "a lone surrogate (a character that cannot be encoded)"
        if what is not None:
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


def _read(text: str, origin: Origin | None, limits: Limits) -> ast.AST:
    try:
        with _READ_LOCK, warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return ast.parse(text, mode="eval")
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
    """Walks the tree once. Every node is counted, its depth is checked, its type must be on the
    whitelist, and the rules for names, attributes, calls and constants are applied."""

    def __init__(
        self, text: str, origin: Origin | None, limits: Limits, functions: frozenset[str]
    ) -> None:
        self.text, self.origin, self.limits, self.functions = text, origin, limits, functions
        self.names: set[str] = set()
        self.nodes = 0
        self._bound: list[set[str]] = []  # the names comprehensions bind, innermost last
        self._rules: dict[type[ast.AST], Callable[[ast.AST, int], None]] = {
            ast.Constant: self._constant,  # type: ignore[dict-item]
            ast.Name: self._name,  # type: ignore[dict-item]
            ast.Attribute: self._attribute,  # type: ignore[dict-item]
            ast.Compare: self._compare,  # type: ignore[dict-item]
            ast.Dict: self._dict,  # type: ignore[dict-item]
            ast.Call: self._call,  # type: ignore[dict-item]
            ast.BinOp: self._binop,  # type: ignore[dict-item]
            ast.ListComp: self._comprehension_owner,
            ast.SetComp: self._comprehension_owner,
            ast.GeneratorExp: self._comprehension_owner,
            ast.DictComp: self._comprehension_owner,
            ast.comprehension: self._generator,  # type: ignore[dict-item]
        }

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
        named = DISALLOWED_NODES.get(kind)
        if named is not None:
            raise self.fail(
                node, "disallowed-construct", f"{named} is not allowed in an expression"
            )
        if kind not in ALLOWED_NODES:
            raise self.fail(
                node, "disallowed-construct", f"{kind.__name__} is not allowed in an expression"
            )
        rule = self._rules.get(kind)
        if rule is not None:
            rule(node, depth)
        else:
            self.children(node, depth)

    def children(self, node: ast.AST, depth: int) -> None:
        for child in ast.iter_child_nodes(node):
            self.visit(child, depth + 1)

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
        self.children(node, depth)

    def _name(self, node: ast.Name, depth: int) -> None:
        name = node.id
        if isinstance(node.ctx, ast.Store):
            if name.startswith("_") and name != "_":
                raise self.fail(node, "private-name", f"the name '{name}' is private")
            self.children(node, depth)  # a comprehension target: bound by `_generator`
            return
        if name.startswith("_") and not (name == "_" and self.is_bound("_")):
            raise self.fail(
                node,
                "private-name",
                f"the name '{name}' is private (names starting with _ are not visible)",
            )
        if not self.is_bound(name):
            self.names.add(name)
        self.children(node, depth)

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

    def _comprehension_owner(self, node: ast.AST, depth: int) -> None:
        """A list, set, dict or generator comprehension: its generators bind names, then its
        element sees them."""
        self._bound.append(set())
        try:
            generators: list[ast.comprehension] = node.generators  # type: ignore[attr-defined]
            for generator in generators:
                self.visit(generator, depth + 1)
            for child in ast.iter_child_nodes(node):
                if not isinstance(child, ast.comprehension):
                    self.visit(child, depth + 1)
        finally:
            self._bound.pop()

    def _generator(self, node: ast.comprehension, depth: int) -> None:
        if node.is_async:
            raise self.fail(
                node.iter, "comprehension-async", "async comprehensions are not allowed"
            )
        self.visit(node.iter, depth + 1)  # sees the names bound before this generator, not its own
        self._bound[-1] |= self._targets(node.target)
        self.visit(node.target, depth + 1)
        for condition in node.ifs:
            self.visit(condition, depth + 1)

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
