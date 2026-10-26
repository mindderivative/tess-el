"""Where an expression's text starts in its file."""

from dataclasses import dataclass

from tel._spans import split_lines


@dataclass(frozen=True, slots=True)
class Origin:
    """Where the text of an expression starts in the file it came from.

    `line` and `column` are 1-based, as an editor shows them, and name the first character of the
    text, so a column inside a YAML scalar maps to the file. `file` is only a label for messages.
    """

    file: str | None = None
    line: int = 1
    column: int = 1

    def __post_init__(self) -> None:
        if self.file is not None and not isinstance(self.file, str):
            raise TypeError(f"file must be text or None, not {type(self.file).__name__}")
        for name in ("line", "column"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an int, not {type(value).__name__}")
            if value < 1:
                raise ValueError(f"{name} is 1-based and must be at least 1, not {value}")

    def advance(self, text: str) -> Origin:
        """The origin of what follows `text`: used to skip leading whitespace, or the literal text
        in front of a `{{ }}` part, so positions stay right."""
        lines = split_lines(text)
        if len(lines) == 1:
            return Origin(self.file, self.line, self.column + len(text))
        return Origin(self.file, self.line + len(lines) - 1, len(lines[-1]) + 1)
