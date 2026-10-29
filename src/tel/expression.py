"""A compiled expression: compile once, evaluate against any scope, any number of times."""

from typing import Any, NamedTuple

from tel._arguments import as_text, check_limits, check_origin, no_lookup
from tel._compiler import Fn, Run, compile_tree
from tel._parser import Parsed, parse
from tel.errors import TelError, TelLimitError
from tel.language import check_language
from tel.limits import DEFAULT_LIMITS, Limits, limit_code
from tel.origin import Origin
from tel.scope import Scope


class Expression:
    """An expression that has been read, checked and compiled.

    Immutable, and safe to share between threads: `evaluate` keeps its state on the stack, not on
    the object. It keeps no syntax tree, only the closures and the text for error messages.
    """

    __slots__ = ("_fn", "_names", "_slots", "limits", "nodes", "origin", "source", "text")

    def __init__(self, fn: Fn, slots: int, parsed: Parsed, limits: Limits) -> None:
        # attributes are set once, here; `__setattr__` then refuses any change
        set_ = object.__setattr__
        set_(self, "_fn", fn)
        set_(self, "_slots", slots)
        set_(self, "source", parsed.source)  # the text as given
        set_(self, "text", parsed.text)  # the text that was read: no surrounding whitespace
        set_(self, "origin", parsed.origin)  # where `text` starts in its file
        set_(self, "_names", tuple(sorted(parsed.names)))
        set_(self, "nodes", parsed.nodes)  # nodes in the syntax tree, not counting operators
        set_(self, "limits", limits)

    _fn: Fn
    _slots: int
    source: str
    text: str
    origin: Origin | None
    _names: tuple[str, ...]
    nodes: int
    limits: Limits

    @property
    def names(self) -> frozenset[str]:
        """The names the expression reads from a scope (syntactic; built-in functions it calls
        are not scope names)."""
        return frozenset(self._names)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("an Expression is immutable")

    def __copy__(self) -> Expression:
        return self

    def __deepcopy__(self, memo: Any) -> Expression:
        return self

    def __reduce__(self) -> Any:
        raise TypeError(
            "an Expression cannot be pickled: send its text and compile it again from `.source`"
        )

    def __delattr__(self, name: str) -> None:
        raise AttributeError("an Expression is immutable")

    def evaluate(self, scope: Scope) -> Any:
        """The value of the expression in `scope`. Raises `TelEvaluationError` or `TelLimitError`
        for a problem with the expression; an exception from `scope.lookup` propagates."""
        run = Run()
        run.scope = scope
        try:
            return self._run(run)
        except RecursionError:
            raise self._too_deep() from None

    def evaluate_tracked(self, scope: Scope) -> Tracked:
        """Evaluate, and also say which names the evaluation actually asked `scope` for.

        `reads` can be fewer than `names`: `a if flag else b` reads `flag` and one of the others.
        A `TelError` raised on the way carries the names read so far as `error.reads`.
        """
        reads: set[str] = set()
        run = Run()
        run.scope = scope
        try:
            lookup = scope.lookup
        except AttributeError:
            raise no_lookup() from None

        def record(name: str) -> Any:
            reads.add(name)
            return lookup(name)

        try:
            value = self._run(run, record)
        except RecursionError:
            raise attach(self._too_deep(), reads) from None
        except TelError as error:
            raise attach(error, reads) from None
        return tuple.__new__(Tracked, (value, frozenset(reads)))

    def _run(self, run: Run, lookup: Any = None) -> Any:
        """Evaluate inside `run` (a template shares one step budget between its parts)."""
        run.slots = [None] * self._slots if self._slots else None
        if lookup is None:
            try:
                lookup = run.scope.lookup
            except AttributeError:
                raise no_lookup() from None
        return self._fn(lookup, run)

    def _too_deep(self) -> TelLimitError:
        return TelLimitError(
            f"the expression is nested more than {self.limits.max_depth} deep",
            code=limit_code("max_depth"),
            source=self.text,
            line=1,
            column=1,
            origin=self.origin,
        )

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
    source, limits, origin = as_text(source), check_limits(limits), check_origin(origin)
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
    return Expression(fn, slots, parsed, limits)


class Tracked(NamedTuple):
    """The result of `evaluate_tracked`: the value, and the names the evaluation read."""

    value: Any
    reads: frozenset[str]


def recorder(reads: set[str], scope: Any) -> Any:
    """A `lookup` that writes each name asked for into `reads` before it asks `scope`."""
    try:
        lookup = scope.lookup
    except AttributeError:
        raise no_lookup() from None

    def record(name: str) -> Any:
        reads.add(name)
        return lookup(name)

    return record


def attach(error: TelError, reads: set[str]) -> TelError:
    """`error` with the names read so far. Errors are made once, at the site, so this sets the one
    attribute and the constructor argument that pickling uses."""
    frozen = frozenset(reads)
    error.reads = frozen
    error._kwargs["reads"] = frozen
    return error
