"""Private helpers that turn syntax-tree positions into the positions TEL reports."""

import ast
import difflib
import re
import types
from collections.abc import Iterable

_NEWLINE = re.compile(r"\r\n|\r|\n")  # what `ast` counts as a line break


def split_lines(source: str) -> list[str]:
    """The lines of `source`, split exactly where `ast` counts line numbers."""
    return _NEWLINE.split(source)


def _characters(line: str, byte_offset: int) -> int:
    """The number of characters before a UTF-8 byte offset (`ast` reports bytes, not characters)."""
    return len(line.encode("utf-8")[:byte_offset].decode("utf-8", errors="replace"))


def node_span(source: str, node: ast.AST) -> tuple[int, int, int | None]:
    """`(line, column, end_column)` of a node in `source`: 1-based, in characters, the end just past
    the last character, or `None` when the node spans more than one line."""
    lineno = getattr(node, "lineno", None)
    if lineno is None:
        return 1, 1, None
    lines = split_lines(source)

    def column(line_number: int, byte_offset: int) -> int:
        line = lines[line_number - 1] if 0 < line_number <= len(lines) else ""
        return _characters(line, byte_offset) + 1

    start = column(lineno, node.col_offset)  # type: ignore[attr-defined]
    end_lineno = getattr(node, "end_lineno", lineno)
    end_offset = getattr(node, "end_col_offset", None)
    if end_lineno != lineno or end_offset is None:
        return lineno, start, None
    return lineno, start, column(end_lineno, end_offset)


def did_you_mean(name: str, known: Iterable[str]) -> str | None:
    """A hint naming the nearest of `known` to `name`, or `None` when nothing is near."""
    close = difflib.get_close_matches(name, [str(k) for k in known], n=3)
    return "did you mean " + " or ".join(f"'{c}'" for c in close) if close else None


_FIELD = 24  # bits per coordinate in a packed position
_MASK = (1 << _FIELD) - 1


def pack_position(node: ast.AST) -> int:
    """A node's position as one int, so a compiled expression keeps no syntax tree: line, column,
    end line and end column, `_FIELD` bits each (larger values are clamped)."""
    lineno: int = getattr(node, "lineno", 1)
    end_lineno: int = getattr(node, "end_lineno", None) or lineno
    parts = (
        lineno,
        getattr(node, "col_offset", 0),
        end_lineno,
        getattr(node, "end_col_offset", None) or 0,
    )
    packed = 0
    for part in parts:
        packed = (packed << _FIELD) | min(max(part, 0), _MASK)
    return packed


def packed_span(source: str, packed: int) -> tuple[int, int, int | None]:
    """`node_span` for a position made by `pack_position`."""
    end_col = packed & _MASK
    end_line = (packed >> _FIELD) & _MASK
    col = (packed >> (2 * _FIELD)) & _MASK
    line = (packed >> (3 * _FIELD)) & _MASK
    node = types.SimpleNamespace(
        lineno=line, col_offset=col, end_lineno=end_line, end_col_offset=end_col or None
    )
    return node_span(source, node)  # type: ignore[arg-type]
