"""The errors TEL raises. Each carries what a host needs to report it: a stable `code`, the source
text, and where the problem is (in the host's file when an `Origin` is known).

TEL logs nothing and does not depend on any logging library: the host turns an error into its own
message.
"""

from typing import Any

from tel._spans import split_lines
from tel.origin import Origin


class TelError(ValueError):
    """Base class of every error TEL raises.

    * `message`: text for people; not a stable API.
    * `code`: a short stable identifier such as `private-name`; match on this, not on the message.
    * `source`: the expression text.
    * `line`, `column`, `end_column`: 1-based, in the host file when an `Origin` was given, else in
      the text. `end_column` is just past the last character of the span, or `None`. All three
      are `None` for an error that has no position (raised before any text is read).
    * `file`: the origin's file label, if any.
    * `hint`: a suggestion such as "did you mean 'count'", or `None`.
    * `text_line`, `text_column`: the position inside `source`, whatever the origin.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str,
        source: str = "",
        line: int | None = None,
        column: int | None = None,
        end_column: int | None = None,
        hint: str | None = None,
        origin: Origin | None = None,
    ) -> None:
        if (line is None) != (column is None):
            raise ValueError("line and column are given together or not at all")
        for name, value in (("line", line), ("column", column), ("end_column", end_column)):
            if value is not None and value < 1:
                raise ValueError(f"{name} is 1-based and must be at least 1, not {value}")
        self._kwargs: dict[str, Any] = dict(
            code=code,
            source=source,
            line=line,
            column=column,
            end_column=end_column,
            hint=hint,
            origin=origin,
        )
        self.message = message
        self.code = code
        self.source = source
        self.hint = hint
        self.file = origin.file if origin else None
        self.text_line, self.text_column, self.text_end_column = line, column, end_column
        self.line, self.column, self.end_column = line, column, end_column
        if origin is not None and line is not None and column is not None:
            self.line = origin.line + line - 1
            shift = origin.column - 1 if line == 1 else 0
            self.column = column + shift
            if end_column is not None:
                self.end_column = end_column + shift
        super().__init__(self._summary())

    def _summary(self) -> str:
        where = ""
        if self.line is not None:
            where = f"{self.line}:{self.column}: "
            if self.file is not None:
                where = f"{self.file}:{where}"
        return f"{where}{self.message}" + (f" ({self.hint})" if self.hint else "")

    def render(self) -> str:
        """The message, the offending line of the expression and a caret under the span."""
        if self.text_line is None or self.text_column is None:
            return str(self)
        lines = split_lines(self.source)
        text = lines[min(self.text_line, len(lines)) - 1]
        pad = "".join("\t" if ch == "\t" else " " for ch in text[: self.text_column - 1])
        width = 1
        if self.text_end_column is not None:
            width = max(1, self.text_end_column - self.text_column)
        return f"{self}\n    {text}\n    {pad}{'^' * width}"

    def __reduce__(self) -> tuple[Any, ...]:
        return _rebuild, (type(self), self.message, self._kwargs)


def _rebuild(cls: type[TelError], message: str, kwargs: dict[str, Any]) -> TelError:
    return cls(message, **kwargs)


class TelSyntaxError(TelError):
    """Compile time: the text is not valid, or uses something the language does not allow."""


class TelEvaluationError(TelError):
    """Evaluation time: an undefined name, a bad operand, a missing attribute or key."""


class TelLimitError(TelError):
    """A limit was exceeded, at compile time or at evaluation time (`code` is `limit-...`)."""


class TelVersionError(TelError):
    """The language version the host asked for is not one this release supports."""
