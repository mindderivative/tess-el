"""TEL's Python form: text with `$name` placeholders, each replaced by a checked literal.

`fill` and `fill_template` return text that any entry point reads (`compile_expression`,
`compile_condition`, `compile_repeater`, `compile_template`), so the one parser and the one
whitelist still decide what the text may do. A value can only be data: it is written as a Python
literal, a string is quoted by `repr`, and a value is never scanned for placeholders again
(`docs/language.md`, section 17, decisions 6A to 6H)."""

import math
import re
from collections.abc import Mapping
from typing import Any

from tel._arguments import as_text, check_limits
from tel._parser import reads_as_expression
from tel.errors import TelLimitError
from tel.limits import DEFAULT_LIMITS, Limits, limit_code
from tel.template import _split

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# What a placeholder cannot be inside: strings (any prefix, so f-strings and their fields too) and
# comments. Then `$name`, or a `$` with no name after it.
_SCAN = re.compile(
    r"""(?P<keep>(?:'''(?:[^\\]|\\.)*?(?:'''|\Z)|\"\"\"(?:[^\\]|\\.)*?(?:\"\"\"|\Z)"""
    r"""|'(?:[^'\\\n]|\\.)*'?|"(?:[^"\\\n]|\\.)*"?)|\#[^\n]*)"""
    r"""|\$(?P<name>[A-Za-z_][A-Za-z0-9_]*)?""",
    re.DOTALL,
)

_WHAT = "None, bool, int, float, str, and list, tuple and dict of those"


def _too_long(limits: Limits) -> TelLimitError:
    return TelLimitError(
        f"the text would be over {limits.max_source} characters",
        code=limit_code("max_source"),
    )


def _too_deep(limits: Limits) -> TelLimitError:
    return TelLimitError(
        f"the value is nested more than {limits.max_depth} deep", code=limit_code("max_depth")
    )


def _show(key: Any) -> str:
    """A key or an index for a path in a message, without running a subclass's own methods."""
    if isinstance(key, str):
        return str.__repr__(key)
    if isinstance(key, int):
        return int.__repr__(key)
    return f"<{type(key).__name__}>"


class _Writer:
    """Writes one value as a literal, counting what it has written against `max_source`."""

    __slots__ = ("limits", "path", "size")

    def __init__(self, limits: Limits, root: str) -> None:
        self.limits = limits
        self.path = [root]
        self.size = 0

    def write(self, value: object, out: list[str], depth: int, top: bool) -> None:
        limits = self.limits
        if value is None:
            text = "None"
        elif value is True:
            text = "True"
        elif value is False:
            text = "False"
        elif isinstance(value, int):
            if int.bit_length(value) > limits.max_int_bits:
                raise TelLimitError(
                    f"{self.where()}: the number is over {limits.max_int_bits} bits",
                    code=limit_code("max_int_bits"),
                )
            text = _bracket(int.__repr__(value), top)
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError(f"{self.where()}: nan and inf have no literal")
            text = _bracket(float.__repr__(value), top)
        elif isinstance(value, str):
            if str.__len__(value) > limits.max_source:  # before `repr` builds a second copy of it
                raise _too_long(limits)
            text = str.__repr__(value)
        elif isinstance(value, list | tuple):
            self.sequence(value, out, depth)
            return
        elif isinstance(value, dict):
            self.mapping(value, out, depth)
            return
        else:
            raise TypeError(
                f"{self.where()}: a {type(value).__name__} cannot be written as a literal ({_WHAT})"
            )
        self.add(len(text))
        out.append(text)

    def add(self, n: int) -> None:
        self.size += n
        if self.size > self.limits.max_source:
            raise _too_long(self.limits)

    def where(self) -> str:
        return "".join(self.path)

    def enter(self, depth: int) -> None:
        if depth + 1 > self.limits.max_depth:
            raise _too_deep(self.limits)

    def sequence(self, value: list[Any] | tuple[Any, ...], out: list[str], depth: int) -> None:
        self.enter(depth)
        is_list = isinstance(value, list)
        items = list.__iter__(value) if is_list else tuple.__iter__(value)  # type: ignore[arg-type]
        out.append("[" if is_list else "(")
        count = 0
        for count, item in enumerate(items, 1):
            if count > 1:
                out.append(", ")
                self.add(2)
            self.path.append(f"[{count - 1}]")
            self.write(item, out, depth + 1, False)
            self.path.pop()
        out.append("]" if is_list else (",)" if count == 1 else ")"))
        self.add(2)

    def mapping(self, value: dict[Any, Any], out: list[str], depth: int) -> None:
        self.enter(depth)
        out.append("{")
        first = True
        for key, item in dict.items(value):
            if isinstance(key, bool) or not isinstance(key, str | int):
                raise TypeError(
                    f"{self.where()}: a dict key must be a str or an int, "
                    f"not a {type(key).__name__}"
                )
            if not first:
                out.append(", ")
                self.add(2)
            first = False
            self.path.append(f"[{_show(key)}]")
            self.write(key, out, depth + 1, False)
            out.append(": ")
            self.add(2)
            self.write(item, out, depth + 1, False)
            self.path.pop()
        out.append("}")
        self.add(2)


def _bracket(text: str, top: bool) -> str:
    """A negative number on its own is put in brackets, so `$x ** 2` with -5 is `(-5) ** 2`."""
    return f"({text})" if top and text.startswith("-") else text


def _render(value: object, limits: Limits, root: str) -> str:
    writer = _Writer(limits, root)
    out: list[str] = []
    try:
        writer.write(value, out, 0, True)
    except RecursionError:
        raise _too_deep(limits) from None
    return "".join(out)


def literal(value: object, *, limits: Limits = DEFAULT_LIMITS) -> str:
    """`value` as text that TEL reads back to an equal value: `None`, `bool`, `int`, `float`
    (finite), `str`, and `list`, `tuple` and `dict` (with `str` or `int` keys) of those.

    A negative number is in brackets (`(-5)`), so the text is safe in any expression. A subclass is
    written as the plain type it extends without running its own methods. Another type is a
    `TypeError`, nan and inf a `ValueError`, and a value over `limits.max_source` characters,
    `limits.max_depth` deep or `limits.max_int_bits` bits a `TelLimitError`."""
    return _render(value, check_limits(limits), "value")


def _mask(text: str) -> str:
    """`text` with each placeholder outside a string or comment turned into `_` and spaces, so
    Python can still read it as an expression (only whether it reads matters)."""

    def hide(found: re.Match[str]) -> str:
        if found.group("keep") is not None:
            return found.group()
        return "_"

    return _SCAN.sub(hide, text)


def _need_values(values: object) -> dict[str, Any]:
    if not isinstance(values, Mapping):
        raise TypeError(f"values must be a mapping of names to values, not {type(values).__name__}")
    found: dict[str, Any] = {}
    for name, value in dict(values).items():
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ValueError(
                f"a placeholder name must be a str of letters, digits and _ (not starting with "
                f"a digit): {_show(name)}"
            )
        found[name] = value
    return found


class _Filler:
    """Fills the placeholders of one or more pieces of text from the same values."""

    __slots__ = ("limits", "missing", "total", "used", "values")

    def __init__(self, values: dict[str, Any], limits: Limits) -> None:
        self.values = values
        self.limits = limits
        self.used: set[str] = set()
        self.missing: list[str] = []
        self.total = 0

    def add(self, n: int) -> None:
        self.total += n
        if self.total > self.limits.max_source:
            raise _too_long(self.limits)

    def text(self, text: str) -> str:
        """`text` as it is, counted against the size limit."""
        self.add(len(text))
        return text

    def fill(self, text: str) -> str:
        out: list[str] = []
        pos = 0
        for found in _SCAN.finditer(text):
            if found.group("keep") is not None:
                continue
            name = found.group("name")
            if name is None:
                raise ValueError(
                    f"a '$' at character {found.start()} is not followed by a name: a "
                    "placeholder is $name; a '$' in a string or a comment is left alone"
                )
            out.append(self.text(text[pos : found.start()]))
            out.append(self.text(self.value(name)))
            pos = found.end()
        out.append(self.text(text[pos:]))
        return "".join(out)

    def value(self, name: str) -> str:
        self.used.add(name)
        if name not in self.values:
            if name not in self.missing:
                self.missing.append(name)
            return ""
        return _render(self.values[name], self.limits, f"values[{name!r}]")

    def done(self) -> None:
        if self.missing:
            raise ValueError("no value for " + ", ".join(f"${name}" for name in self.missing))
        unused = sorted(set(self.values) - self.used)
        if unused:
            raise ValueError(
                "no placeholder for "
                + ", ".join(f"{name!r}" for name in unused)
                + " (a misspelt name would silently go unused)"
            )


def fill(text: str, values: Mapping[str, Any], *, limits: Limits = DEFAULT_LIMITS) -> str:
    """`text` with each `$name` replaced by the literal for `values[name]`.

    A placeholder is read outside string literals (f-strings and their fields too) and comments; a
    `$` inside one is ordinary text. Every placeholder needs a value and every value a placeholder
    (else `ValueError`, naming it); a `$` with no name is a `ValueError`; a value that is not
    literal data is a `TypeError` (see `literal`). The result is checked as it grows against
    `limits.max_source`, and a value against `limits.max_depth`, so a huge value is never built into
    text first. A value is written once and never scanned for placeholders. Errors from compiling
    the result point into the filled text, not into `text`."""
    text = as_text(text, "the text")
    limits = check_limits(limits)
    filler = _Filler(_need_values(values), limits)
    result = filler.fill(text)
    filler.done()
    return result


def fill_template(text: str, values: Mapping[str, Any], *, limits: Limits = DEFAULT_LIMITS) -> str:
    """`text` as a template, with each `$name` inside a `{{ }}` part replaced as in `fill`. The text
    between parts is never touched, so a `$` there stays. To put a value in as text, put it in a
    part (`{{ $greeting }}`): it becomes a quoted string, so a value holding `{{` is only text."""
    text = as_text(text, "the text")
    limits = check_limits(limits)
    filler = _Filler(_need_values(values), limits)
    out: list[str] = []
    for piece, index in _split(text, None, lambda part: reads_as_expression(_mask(part))):
        if index < 0:
            out.append(filler.text(piece))
        else:
            out.append(filler.text("{{"))
            out.append(filler.fill(piece))
            out.append(filler.text("}}"))
    filler.done()
    return "".join(out)
