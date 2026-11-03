"""A compiled expression: compile once, evaluate against any scope, any number of times."""

from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

from tess_el._arguments import as_text, check_limits, check_origin, no_lookup
from tess_el._compiler import Fn, Run, compile_tree
from tess_el._host import EMPTY, Registry
from tess_el._parser import Parsed, canonical_text, parse
from tess_el.errors import TelError, TelLimitError
from tess_el.language import check_language
from tess_el.limits import DEFAULT_LIMITS, Limits, limit_code
from tess_el.origin import Origin
from tess_el.scope import Scope


class Expression:
    """An expression that has been read, checked and compiled.

    Immutable, and safe to share between threads: `evaluate` keeps its state on the stack, not on
    the object. It keeps no syntax tree, only the closures and the text for error messages.
    """

    __slots__ = (
        "_fn",
        "_paths",
        "_slots",
        "limits",
        "nodes",
        "origin",
        "source",
        "text",
    )

    def __init__(
        self, fn: Fn, slots: int, paths: frozenset[str], parsed: Parsed, limits: Limits
    ) -> None:
        # attributes are set once, here; `__setattr__` then refuses any change
        set_ = object.__setattr__
        set_(self, "_fn", fn)
        set_(self, "_slots", slots)
        set_(self, "source", parsed.source)  # the text as given
        set_(self, "text", parsed.text)  # the text that was read: no surrounding whitespace
        set_(self, "origin", parsed.origin)  # where `text` starts in its file
        set_(self, "_paths", tuple(paths))
        set_(self, "nodes", parsed.nodes)  # nodes in the syntax tree, not counting operators
        set_(self, "limits", limits)

    _fn: Fn
    _slots: int
    source: str
    text: str
    origin: Origin | None
    _paths: tuple[str, ...]
    nodes: int
    limits: Limits

    @property
    def names(self) -> frozenset[str]:
        """The names the expression reads from a scope (syntactic; built-in functions it calls
        are not scope names)."""
        return frozenset(path.partition(".")[0] for path in self._paths)

    @property
    def canonical(self) -> str:
        """The expression written back from its syntax tree: spacing, quotes, redundant brackets
        and the `?:` spelling do not matter, so two spellings of one expression have one canonical
        text (`a<20` and `a < 20`; `c ? a : b` and `a if c else b`). Computed when asked, from the
        text alone; nothing is kept. It is for comparing within one run: `ast.unparse` output is
        stable within one Python version only, so never store it."""
        try:
            return canonical_text(self.text)
        except RecursionError:
            raise self._too_deep() from None

    @property
    def paths(self) -> frozenset[str]:
        """Every path the expression could read: `a.b.c` for an attribute chain on a name, `a` for a
        bare name. It covers every branch, so a tracked evaluation's `reads` is a subset of it."""
        return frozenset(self._paths)

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
        try:
            lookup = scope.lookup
        except AttributeError:
            raise no_lookup() from None
        run = Run()
        run.scope = scope
        if self._slots:
            run.slots = [None] * self._slots
        try:
            return self._fn(lookup, run)
        except RecursionError:
            raise self._too_deep() from None

    def evaluate_tracked(self, scope: Scope) -> Tracked:
        """Evaluate, and also say which paths the evaluation actually read from `scope`.

        A path is a name (`flag`) or an attribute chain on a name (`RootShell.DP1.Width`); `reads`
        can be fewer than `paths`: `a if flag else b` reads `flag` and one of the others. A
        `TelError` raised on the way carries the paths read so far as `error.reads`.
        """
        reads: set[str] = set()
        run = Run()
        run.scope = scope
        run.paths = reads
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


def make_registry(
    functions: Mapping[str, Callable[..., Any]] | None,
    methods: Mapping[type, Mapping[str, Callable[..., Any]]] | None,
) -> Registry:
    """The host's functions and methods, validated and copied (the shared empty one if none)."""
    return EMPTY if functions is None and methods is None else Registry(functions, methods)


def compile_expression(
    source: str,
    *,
    language: str,
    origin: Origin | None = None,
    limits: Limits = DEFAULT_LIMITS,
    functions: Mapping[str, Callable[..., Any]] | None = None,
    methods: Mapping[type, Mapping[str, Callable[..., Any]]] | None = None,
) -> Expression:
    """Read, check and compile one expression.

    `language` is the language version the host declares, as text (`"0.1"`); an unsupported or
    non-text version raises `TelVersionError`. `origin` says where the text starts in its file so
    errors point into the file. Raises `TelSyntaxError` or `TelLimitError` for a bad expression.

    `functions` maps a name to a function the expression may call, and `methods` maps a class to
    the methods it may call on a value of that class (`docs/language.md`, section 12). Both are
    checked and copied here; a mistake in them is a `ValueError` or `TypeError`, not a `TelError`.
    """
    check_language(language)
    return compile_checked(
        source, origin=origin, limits=limits, registry=make_registry(functions, methods)
    )


def compile_checked(
    source: str, *, origin: Origin | None, limits: Limits, registry: Registry
) -> Expression:
    """`compile_expression` after the language and the registry have been checked."""
    source, limits, origin = as_text(source), check_limits(limits), check_origin(origin)
    parsed = parse(
        source,
        origin=origin,
        limits=limits,
        functions=registry.call_names,
        method_names=registry.method_names,
    )
    try:
        fn, slots, paths = compile_tree(parsed, limits, registry)
    except RecursionError:
        raise TelLimitError(
            f"the expression is nested more than {limits.max_depth} deep",
            code=limit_code("max_depth"),
            source=parsed.text,
            line=1,
            column=1,
            origin=parsed.origin,
        ) from None
    return Expression(fn, slots, paths, parsed, limits)


class Tracked(NamedTuple):
    """The result of `evaluate_tracked`: the value, and the paths the evaluation read."""

    value: Any
    reads: frozenset[str]  # `a` for a name, `a.b.c` for an attribute chain on a name

    @property
    def names(self) -> frozenset[str]:
        """The top-level names behind `reads` (`a` for `a.b.c`)."""
        return frozenset(path.partition(".")[0] for path in self.reads)


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
