"""Conditions: an expression read as yes or no, and the first of a chain that holds (decision D15).

The Shell owns the `if:`, `elif:` and `else:` keys; TEL gives it the answer and the reads. The
`else` is what `select` returns when no condition holds."""

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from tel._values import truthy
from tel.errors import TelError
from tel.expression import Expression, Tracked, attach, compile_expression
from tel.limits import DEFAULT_LIMITS, Limits
from tel.origin import Origin
from tel.scope import Scope


class Condition:
    """An expression that is read as yes or no: truthy gives `True`, anything else `False`.

    Immutable and safe to share between threads, like the `Expression` it holds.
    """

    __slots__ = ("expression",)

    expression: Expression

    def __init__(self, expression: Expression) -> None:
        object.__setattr__(self, "expression", expression)

    @property
    def source(self) -> str:
        """The text as given."""
        return self.expression.source

    @property
    def text(self) -> str:
        """The text that was read: no surrounding whitespace."""
        return self.expression.text

    @property
    def names(self) -> frozenset[str]:
        """The names the condition reads from a scope (see `Expression.names`)."""
        return self.expression.names

    @property
    def paths(self) -> frozenset[str]:
        """Every path the condition could read (see `Expression.paths`)."""
        return self.expression.paths

    def holds(self, scope: Scope) -> bool:
        """Whether the condition is true in `scope`, by the evaluator's own rule (`not x`): a plain
        value is true or false as in Python, and a host object is true without being asked."""
        return truthy(self.expression.evaluate(scope))

    def holds_tracked(self, scope: Scope) -> Tracked:
        """`holds`, with the paths the evaluation read: a `Tracked` whose value is the bool. An
        error carries the paths read so far as `error.reads`."""
        value, reads = self.expression.evaluate_tracked(scope)
        return tuple.__new__(Tracked, (truthy(value), reads))

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("a Condition is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("a Condition is immutable")

    def __copy__(self) -> Condition:
        return self

    def __deepcopy__(self, memo: Any) -> Condition:
        return self

    def __reduce__(self) -> Any:
        raise TypeError(
            "a Condition cannot be pickled: send its text and compile it again from `.source`"
        )

    def __repr__(self) -> str:
        return f"Condition({self.text!r})"


def compile_condition(
    source: str,
    *,
    language: str,
    origin: Origin | None = None,
    limits: Limits = DEFAULT_LIMITS,
    functions: Mapping[str, Callable[..., Any]] | None = None,
    methods: Mapping[type, Mapping[str, Callable[..., Any]]] | None = None,
) -> Condition:
    """Read, check and compile one condition: `compile_expression` with the same arguments and
    errors, whose value is read as yes or no (`docs/language.md`, section 16)."""
    return Condition(
        compile_expression(
            source,
            language=language,
            origin=origin,
            limits=limits,
            functions=functions,
            methods=methods,
        )
    )


def _conditions(conditions: Iterable[Condition]) -> Iterable[Condition]:
    """`conditions`, read one at a time as far as the winner, each checked when it is reached."""
    if isinstance(conditions, Condition):
        raise TypeError(
            f"conditions must be a sequence of Condition, not {type(conditions).__name__}"
        )
    for condition in conditions:
        if not isinstance(condition, Condition):
            raise TypeError(f"conditions must be Condition objects, not {type(condition).__name__}")
        yield condition


def select(conditions: Iterable[Condition], scope: Scope) -> int | None:
    """The index of the first condition that holds in `scope`, or `None` if none does (the `else`).

    Conditions after the winner are not evaluated, and not even looked up in `scope`."""
    for index, condition in enumerate(_conditions(conditions)):
        if condition.holds(scope):
            return index
    return None


def select_tracked(conditions: Iterable[Condition], scope: Scope) -> Tracked:
    """`select`, with the paths read: those of every condition tested, up to and including the
    winner (or all of them when none holds), because an earlier condition that flips changes the
    winner. A `TelError` carries the paths read so far, from every condition tested."""
    reads: set[str] = set()
    for index, condition in enumerate(_conditions(conditions)):
        try:
            holds, more = condition.holds_tracked(scope)
        except TelError as error:
            raise attach(error, reads | (error.reads or frozenset())) from None
        reads |= more
        if holds:
            return tuple.__new__(Tracked, (index, frozenset(reads)))
    return tuple.__new__(Tracked, (None, frozenset(reads)))
