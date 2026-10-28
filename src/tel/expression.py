"""A compiled expression: compile once, evaluate against any scope, any number of times."""

from typing import Any

from tel._compiler import Fn, Run, compile_tree
from tel._parser import parse
from tel.errors import TelLimitError
from tel.language import check_language
from tel.limits import DEFAULT_LIMITS, Limits, limit_code
from tel.origin import Origin
from tel.scope import Scope


class Expression:
    """An expression that has been read, checked and compiled.

    Immutable, and safe to share between threads: `evaluate` keeps its state on the stack, not on
    the object. It keeps no syntax tree, only the closures and the text for error messages.
    """

    __slots__ = ("_fn", "_slots", "limits", "names", "nodes", "origin", "source", "text")

    def __init__(self, fn: Fn, slots: int, parsed_source: str, parsed: Any, limits: Limits) -> None:
        self._fn = fn
        self._slots = slots
        self.source: str = parsed_source  # the text as given
        self.text: str = parsed.text  # the text that was read: no surrounding whitespace
        self.origin: Origin | None = parsed.origin  # where `text` starts in its file
        self.names: frozenset[str] = parsed.names  # the names it reads from a scope (syntactic)
        self.nodes: int = parsed.nodes  # nodes in the syntax tree
        self.limits = limits

    def evaluate(self, scope: Scope) -> Any:
        """The value of the expression in `scope`. Raises `TelEvaluationError` or `TelLimitError`
        for a problem with the expression; an exception from `scope.lookup` propagates."""
        run = Run()
        run.scope = scope
        if self._slots:
            run.slots = [None] * self._slots
        try:
            return self._fn(scope.lookup, run)
        except RecursionError:
            raise TelLimitError(
                f"the expression is nested more than {self.limits.max_depth} deep",
                code=limit_code("max_depth"),
                source=self.text,
                line=1,
                column=1,
                origin=self.origin,
            ) from None

    def __repr__(self) -> str:
        return f"Expression({self.text!r})"


def compile_expression(
    source: str,
    *,
    language: str,
    origin: Origin | None = None,
    limits: Limits = DEFAULT_LIMITS,
) -> Expression:
    """Read, check and compile one expression.

    `language` is the language version the host declares, as text (`"0.1"`); an unsupported or
    non-text version raises `TelVersionError`. `origin` says where the text starts in its file so
    errors point into the file. Raises `TelSyntaxError` or `TelLimitError` for a bad expression.
    """
    check_language(language)
    parsed = parse(source, origin=origin, limits=limits)
    try:
        fn, slots = compile_tree(parsed, limits)
    except RecursionError:
        raise TelLimitError(
            f"the expression is nested more than {limits.max_depth} deep",
            code=limit_code("max_depth"),
            source=parsed.text,
            line=1,
            column=1,
            origin=parsed.origin,
        ) from None
    return Expression(fn, slots, source, parsed, limits)
