"""Repeaters: `w in workspaces` and a key, read into the keyed items of a list (decisions D15, D16).

The Shell owns the `for:` and `key:` keys and builds the nodes; TEL reads the header, evaluates the
list and the key of every item, and checks the keys. A repeater's children are ordinary
expressions, evaluated in the scope an item gives them (`Item.scope`)."""

import keyword
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from tel._arguments import as_text, check_limits, check_origin, no_lookup
from tel._compiler import Run, items_of, type_name
from tel._parser import _position
from tel.errors import TelError, TelEvaluationError, TelLimitError, TelSyntaxError
from tel.expression import Expression, compile_expression
from tel.language import check_language
from tel.limits import DEFAULT_LIMITS, Limits, limit_code
from tel.origin import Origin
from tel.scope import Scope

#: A key is one of these, or a tuple of them (`Key`).
Key = int | str | tuple[int | str, ...]

# `a`, `a, b, c` (names only), then the word `in`, then whatever is left: the list.
_NAME = r"[^\W\d]\w*"
_HEADER = re.compile(
    rf"(?P<lead>\s*)(?P<target>{_NAME}(?:\s*,\s*{_NAME})*)\s+in(?!\w)(?P<rest>.*)\Z", re.DOTALL
)
_IN = re.compile(r"(?<!\w)in(?!\w)")


def _syntax(
    header: str, origin: Origin | None, start: int, end: int, message: str, code: str
) -> TelSyntaxError:
    """A syntax error over the characters `start` to `end` of the header."""
    line, column = _position(header, start)
    end_line, end_column = _position(header, end)
    return TelSyntaxError(
        message,
        code=code,
        source=header,
        line=line,
        column=column,
        end_column=end_column if end_line == line and end_column > column else None,
        origin=origin,
    )


def _read_header(header: str, origin: Origin | None) -> tuple[tuple[str, ...], str, Origin | None]:
    """The loop variables and the text of the list, with where that text starts in the file."""
    first = len(header) - len(header.lstrip())
    if not header.strip():
        raise _syntax(header, origin, 0, 0, "the header is empty", "repeater-header")
    found = _HEADER.match(header)
    if found is None:
        keyword_at = _IN.search(header)
        if keyword_at is None:
            raise _syntax(
                header,
                origin,
                first,
                len(header.rstrip()),
                "there is no `in`: write the header as `item in items`",
                "repeater-header",
            )
        before = header[: keyword_at.start()].rstrip()
        if not before.strip():
            raise _syntax(
                header,
                origin,
                first,
                keyword_at.end(),
                "there is no loop variable before `in`",
                "repeater-header",
            )
        raise _syntax(
            header,
            origin,
            first,
            len(before),
            "the loop variable must be a name, or names separated by commas",
            "repeater-header",
        )
    rest_at = found.start("rest")
    if not found.group("rest").strip():
        raise _syntax(
            header,
            origin,
            rest_at - 2,
            rest_at,
            "there is nothing after `in`: write the header as `item in items`",
            "repeater-header",
        )
    targets: list[str] = []
    for match in re.finditer(_NAME, found.group("target")):
        name, at = match.group(), found.start("target") + match.start()
        if keyword.iskeyword(name):
            raise _syntax(
                header, origin, at, at + len(name), f"'{name}' cannot be a name", "repeater-header"
            )
        if name.startswith("_") and name != "_":
            raise _syntax(
                header, origin, at, at + len(name), f"the name '{name}' is private", "private-name"
            )
        if name in targets and name != "_":
            raise _syntax(
                header,
                origin,
                at,
                at + len(name),
                f"the name '{name}' is used twice",
                "repeater-header",
            )
        targets.append(name)
    return tuple(targets), found.group("rest"), origin.advance(header[:rest_at]) if origin else None


def _check_name(name: Any) -> str:
    text = as_text(name, "the name")
    if not text.isidentifier() or keyword.iskeyword(text) or text.startswith("_"):
        raise ValueError(
            f"the name must be a public identifier (letters, digits and _, not starting with a "
            f"digit or _): {text!r}"
        )
    return text


def _fail(
    expression: Expression, cls: type[TelError], code: str, message: str, hint: str | None = None
) -> TelError:
    """An error at the start of `expression`, the whole of it when it is on one line."""
    text = expression.text
    return cls(
        message,
        code=code,
        source=text,
        line=1,
        column=1,
        end_column=None if "\n" in text else len(text) + 1,
        hint=hint,
        origin=expression.origin,
    )


def _run(expression: Expression, run: Run, lookup: Any) -> Any:
    """Evaluate `expression` in the shared `run`: the list and every key spend one step budget."""
    try:
        return expression._run(run, lookup)
    except RecursionError:
        raise expression._too_deep() from None


def _too_expensive(expression: Expression) -> TelError:
    return _fail(
        expression,
        TelLimitError,
        limit_code("max_steps"),
        f"the repeater is too expensive to evaluate (over {expression.limits.max_steps} steps)",
    )


def _need_lookup(scope: Any) -> None:
    if not callable(getattr(scope, "lookup", None)):
        raise no_lookup()


class _Layered:
    """A scope that binds the loop variables over the host's scope. Nothing is copied."""

    __slots__ = ("bindings", "parent")

    def __init__(self, bindings: dict[str, Any], parent: Scope) -> None:
        self.bindings = bindings
        self.parent = parent

    def lookup(self, name: str) -> Any:
        try:
            return self.bindings[name]
        except KeyError:
            return self.parent.lookup(name)

    def names(self) -> Iterable[str]:
        found = list(self.bindings)
        try:
            found += [n for n in self.parent.names() if n not in self.bindings]
        except Exception:  # `names` is optional and only builds a hint
            pass
        return found


class Item:
    """One item of a repeater's list: its position, its key, its value and its scope.

    Immutable. `scope(parent)` is the scope for the item's children: the loop variables over
    `parent`, which is the host's scope (it need not be the one the list was read from)."""

    __slots__ = ("_bindings", "index", "key", "value")

    def __init__(self, index: int, key: Key, value: Any, bindings: dict[str, Any]) -> None:
        set_ = object.__setattr__
        set_(self, "index", index)  # the item's place in the list, from 0
        set_(self, "key", key)  # an int, a str or a tuple of those
        set_(self, "value", value)  # the item itself, as the list has it
        set_(self, "_bindings", bindings)

    index: int
    key: Key
    value: Any
    _bindings: dict[str, Any]

    def scope(self, parent: Scope) -> Scope:
        """A scope that has the loop variables of this item and asks `parent` for any other name."""
        _need_lookup(parent)
        return _Layered(self._bindings, parent)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("an Item is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("an Item is immutable")

    def __copy__(self) -> Item:
        return self

    def __deepcopy__(self, memo: Any) -> Item:
        return self

    def __reduce__(self) -> Any:
        raise TypeError("an Item cannot be pickled: it belongs to one evaluation")

    def __repr__(self) -> str:
        return f"Item(index={self.index}, key={self.key!r})"


class Repeater:
    """A header (`w in workspaces`) and a key expression, compiled.

    Immutable and safe to share between threads. `name` is the base of the names the entries get
    (`Workspace_0001`, from decision D7)."""

    __slots__ = ("_key", "_list", "header", "name", "targets")

    def __init__(
        self, header: str, targets: tuple[str, ...], items: Expression, key: Expression, name: str
    ) -> None:
        set_ = object.__setattr__
        set_(self, "header", header)  # the header as given
        set_(self, "targets", targets)  # the loop variables, in order
        set_(self, "name", name)
        set_(self, "_list", items)
        set_(self, "_key", key)

    header: str
    targets: tuple[str, ...]
    name: str
    _list: Expression
    _key: Expression

    def items(self, scope: Scope) -> tuple[Item, ...]:
        """The items of the list in `scope`, in order, each with its key.

        A value that cannot be looped over is `not-iterable`, and so is a set (its order is not
        stable). A list longer than `max_sequence` is a `TelLimitError` before any key is made. A
        key that is not an int, a str or a tuple of those is `bad-key-type`, and two items with one
        key are `duplicate-key`. Errors from the list or a key are the usual ones, positioned in the
        header or the key."""
        _need_lookup(scope)
        run = Run()
        run.scope = scope
        values = self._values(_run(self._list, run, scope.lookup), run)
        key = self._key
        items: list[Item] = []
        seen: dict[Key, int] = {}
        for index, value in enumerate(values):
            bindings = self._bind(index, value)
            layered = _Layered(bindings, scope)
            run.scope = layered
            made = self._checked(index, _run(key, run, layered.lookup))
            if made in seen:
                raise _fail(
                    key,
                    TelEvaluationError,
                    "duplicate-key",
                    f"items {seen[made]} and {index} have the same key",
                    "a key must be different for every item",
                )
            seen[made] = index
            items.append(Item(index, made, value, bindings))
        return tuple(items)

    def _values(self, source: Any, run: Run) -> list[Any]:
        e = self._list
        if isinstance(source, set | frozenset):
            raise _fail(
                e,
                TelEvaluationError,
                "not-iterable",
                f"a {type_name(source)} has no stable order, so it cannot be repeated",
                "use a list, tuple, dict, text or range",
            )
        if not isinstance(source, str | list | tuple | range | Mapping):
            raise _fail(
                e,
                TelEvaluationError,
                "not-iterable",
                f"cannot repeat over a {type_name(source)}",
                "use a list, tuple, dict, text or range",
            )
        limit = e.limits.max_sequence
        if len(source) > limit:
            raise _fail(
                e,
                TelLimitError,
                limit_code("max_sequence"),
                f"the list has {len(source)} items; the limit is {limit}",
            )
        # the whole loop is paid for before it starts, as in a comprehension
        run.steps += len(source)
        if run.steps > e.limits.max_steps:
            raise _too_expensive(e)
        return list(items_of(source))

    def _bind(self, index: int, value: Any) -> dict[str, Any]:
        targets = self.targets
        if len(targets) == 1:
            return {targets[0]: value}
        if not isinstance(value, list | tuple) or len(value) != len(targets):
            shape = (
                f"{len(value)} values"
                if isinstance(value, list | tuple)
                else f"a {type_name(value)}"
            )
            raise _fail(
                self._list,
                TelEvaluationError,
                "bad-unpack",
                f"item {index} has {shape}; the header names {len(targets)}",
                "each item must be a list or tuple with one value per name",
            )
        return dict(zip(targets, items_of(value), strict=True))

    def _checked(self, index: int, key: Any) -> Key:
        """`key` as plain int, str or tuple of those, or `bad-key-type`."""
        if type(key) is tuple:
            if all(_plain_part(part) for part in key):
                return tuple(_plain(part) for part in key)
        elif _plain_part(key):
            return _plain(key)
        raise _fail(
            self._key,
            TelEvaluationError,
            "bad-key-type",
            f"the key of item {index} is a {type_name(key)}; "
            "a key is an int, a str or a tuple of those",
            "a float, bool or None would let two different items share a key",
        )

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("a Repeater is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("a Repeater is immutable")

    def __copy__(self) -> Repeater:
        return self

    def __deepcopy__(self, memo: Any) -> Repeater:
        return self

    def __reduce__(self) -> Any:
        raise TypeError(
            "a Repeater cannot be pickled: send its header and key and compile it again"
        )

    def __repr__(self) -> str:
        return f"Repeater({self.header!r}, key={self._key.text!r})"


def _plain_part(value: Any) -> bool:
    """An int (not a bool) or a str, or a subclass of either."""
    return isinstance(value, int | str) and not isinstance(value, bool)


def _plain(value: Any) -> int | str:
    """`value` as an exact int or str, without running a subclass's own methods."""
    return str.__str__(value) if isinstance(value, str) else int.__int__(value)


def compile_repeater(
    header: str,
    *,
    key: str,
    name: str,
    language: str,
    origin: Origin | None = None,
    key_origin: Origin | None = None,
    limits: Limits = DEFAULT_LIMITS,
    functions: Mapping[str, Callable[..., Any]] | None = None,
    methods: Mapping[type, Mapping[str, Callable[..., Any]]] | None = None,
) -> Repeater:
    """Read the header (`item in items`, or `i, item in enumerate(items)`) and compile it with the
    key expression (`docs/language.md`, section 16).

    `origin` says where the header text starts in its file and `key_origin` where the key text
    starts, so an error in either points into the file. `name` is the base of the entries' names:
    a public identifier. The other arguments are those of `compile_expression`. Raises
    `TelSyntaxError` for a bad header or expression, `ValueError` for a bad `name`."""
    check_language(language)
    header = as_text(header, "the header")
    key = as_text(key, "the key")
    limits, origin, key_origin = (
        check_limits(limits),
        check_origin(origin),
        check_origin(key_origin),
    )
    name = _check_name(name)
    targets, rest, rest_origin = _read_header(header, origin)
    common: dict[str, Any] = dict(
        language=language, limits=limits, functions=functions, methods=methods
    )
    items = compile_expression(rest, origin=rest_origin, **common)
    made = compile_expression(key, origin=key_origin, **common)
    return Repeater(header, targets, items, made, name)
