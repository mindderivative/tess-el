"""Text with expressions in it: `Hello {{ name }}, you have {{ count }} new messages`."""

import re
from typing import Any

from tel._arguments import as_text, check_limits, check_origin, no_lookup
from tel._compiler import Run, inert, type_name
from tel._parser import _position, reads_as_expression
from tel.errors import TelEvaluationError, TelLimitError, TelSyntaxError
from tel.expression import Expression, compile_expression
from tel.language import check_language
from tel.limits import DEFAULT_LIMITS, Limits, limit_code
from tel.origin import Origin
from tel.scope import Scope

_OPEN = "{{"
_CLOSE = "}}"
_HIDING = re.compile(r"['\"{]")  # what can hide a `}}` inside an expression


class Template:
    """A text with one or more `{{ expression }}` parts, compiled.

    Immutable and safe to share between threads. If the text is exactly one part, evaluating it
    gives that part's value with its type; otherwise it gives text.
    """

    __slots__ = ("_parts", "_single", "limits", "origin", "source")

    _parts: tuple[str | Expression, ...]
    _single: Expression | None
    source: str
    origin: Origin | None
    limits: Limits

    def __init__(
        self,
        parts: tuple[str | Expression, ...],
        source: str,
        origin: Origin | None,
        limits: Limits,
    ) -> None:
        set_ = object.__setattr__
        set_(self, "_parts", parts)
        only = parts[0] if len(parts) == 1 and isinstance(parts[0], Expression) else None
        set_(self, "_single", only)
        set_(self, "source", source)
        set_(self, "origin", origin)
        set_(self, "limits", limits)

    @property
    def names(self) -> frozenset[str]:
        """The names its parts read from a scope (syntactic)."""
        return frozenset().union(*(p.names for p in self._parts if isinstance(p, Expression)))

    def evaluate(self, scope: Scope) -> Any:
        """The value (one part) or the text (anything else). The parts share one step budget."""
        run = Run()
        run.scope = scope
        try:
            lookup = scope.lookup
        except AttributeError:
            raise no_lookup() from None
        if self._single is not None:
            try:
                return self._single._run(run)
            except RecursionError:
                raise self._single._too_deep() from None
        out: list[str] = []
        total = 0
        limit = self.limits.max_string
        current: str | Expression = ""
        try:
            for part in self._parts:
                current = part
                if isinstance(part, str):
                    text = part
                else:
                    if part._slots:
                        run.slots = [None] * part._slots
                    value = part._fn(lookup, run)
                    kind = type(value)
                    if kind is str:
                        text = value
                    elif value is None:
                        text = ""
                    elif kind is int or kind is float or kind is bool:
                        text = str(value)
                    else:
                        text = _as_text(part, value)
                total += len(text)
                if total > limit:
                    raise _over_limit(part, limit)
                out.append(text)
        except RecursionError:
            assert isinstance(current, Expression)
            raise current._too_deep() from None
        return "".join(out)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("a Template is immutable")

    def __copy__(self) -> Template:
        return self

    def __deepcopy__(self, memo: Any) -> Template:
        return self

    def __reduce__(self) -> Any:
        raise TypeError(
            "a Template cannot be pickled: send its text and compile it again from `.source`"
        )

    def __delattr__(self, name: str) -> None:
        raise AttributeError("a Template is immutable")

    def __repr__(self) -> str:
        return f"Template({self.source!r})"


def _as_text(part: Expression, value: Any) -> str:
    """A part's value as text: nothing for `None`, `str()` for a plain value."""
    if value is None:
        return ""
    if type(value) is str:
        return value
    if not inert(value):
        raise TelEvaluationError(
            f"a {type_name(value)} cannot be used in text",
            code="value-not-plain",
            source=part.text,
            line=1,
            column=1,
            end_column=None if "\n" in part.text else len(part.text) + 1,
            hint="read one of its attributes instead",
            origin=part.origin,
        )
    return str(value)


def _over_limit(part: str | Expression, limit: int) -> TelLimitError:
    where: dict[str, Any] = {}
    if isinstance(part, Expression):
        where = {"source": part.text, "line": 1, "column": 1, "origin": part.origin}
    return TelLimitError(
        f"the text would be over {limit} characters", code=limit_code("max_string"), **where
    )


def _error(text: str, origin: Origin | None, index: int, code: str, message: str) -> TelSyntaxError:
    """An error at the `{{` that opens a part."""
    line, column = _position(text, index)
    return TelSyntaxError(
        message,
        code=code,
        source=text,
        line=line,
        column=column,
        end_column=column + len(_OPEN),
        origin=origin,
    )


def _split(text: str, origin: Origin | None) -> list[tuple[str, int]]:
    """The text as `("literal", -1)` and `("expression text", index just after its "{{")` pieces.

    A part ends at the first `}}` after which the text reads as an expression, so a `}}` inside a
    string or a bracket belongs to the expression, whatever Python allows there."""
    pieces: list[tuple[str, int]] = []
    position = 0
    while True:
        start = text.find(_OPEN, position)
        if start < 0:
            if position < len(text):
                pieces.append((text[position:], -1))
            return pieces
        if start > position:
            pieces.append((text[position:start], -1))
        body = start + len(_OPEN)
        end = text.find(_CLOSE, body)
        if end < 0:
            raise _error(text, origin, start, "template-unclosed", "a {{ is never closed by }}")
        if not text[body:end].strip():
            raise _error(
                text, origin, start, "template-empty", "there is nothing between {{ and }}"
            )
        first = end
        # A `}}` can only be hidden in a string or behind a `{`; without either before the first
        # `}}`, that one ends the part and the trial parse is not needed.
        if _HIDING.search(text, body, end):
            while end >= 0 and not reads_as_expression(text[body:end]):
                end = text.find(_CLOSE, end + 1)  # overlapping: `}}}` has two candidate endings
        if end < 0:
            end = first  # none reads: the first one's own syntax error is the one to report
        pieces.append((text[body:end], body))
        position = end + len(_CLOSE)


def compile_template(
    text: str,
    *,
    language: str,
    origin: Origin | None = None,
    limits: Limits = DEFAULT_LIMITS,
) -> Template | None:
    """Compile text with `{{ }}` parts, or return `None` if it has none (it is just text).

    `language` and `origin` are as for `compile_expression`, and `origin` is where `text` starts in
    its file: each part's errors point at the part. `limits.max_source` applies to the whole text.
    """
    check_language(language)
    text, limits, origin = as_text(text), check_limits(limits), check_origin(origin)
    if len(text) > limits.max_source:
        raise TelLimitError(
            f"the text is {len(text)} characters; the limit is {limits.max_source}",
            code=limit_code("max_source"),
        )
    if _OPEN not in text:
        return None
    start = origin if origin is not None else Origin()  # positions are in the text at least
    parts: list[str | Expression] = []
    for piece, index in _split(text, origin):
        if index < 0:
            parts.append(piece)
        else:
            placed = start.advance(text[:index])
            parts.append(compile_expression(piece, language=language, origin=placed, limits=limits))
    return Template(tuple(parts), text, origin, limits)
