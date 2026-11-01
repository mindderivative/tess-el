"""`cond ? a : b`, a second spelling of `a if cond else b` (decision D14).

The text is rewritten to `((a) if (cond) else (b))` before `ast.parse`, so what is parsed, checked
and run is the tree `if/else` makes: the whitelist, the evaluator and the trackers do not know there
is a second spelling. The rewrite is a list of *pieces*: ranges of the original text, copied, and
short inserted texts, each anchored at a place in the original.

The syntax tree then has the positions of the rewritten text. Nothing is mapped at compile time:
`original_node` maps a node back only when an error is made, by redoing the rewrite, so a compiled
expression keeps nothing for it. Text with no `?` outside a string or a comment is not touched.

Reading is done on *structural tokens* only: the brackets, `?`, `:`, `,`, and the words `for`, `in`,
`if`, `else`. Strings and comments are skipped. Text with an f-string is read by a scanner that goes
into the fields (`f"{c ? a : b}"`; the `:` of a format spec is not a pair of a `?`); all other
text is read by one regular expression, which is faster. Both give the same tokens.

How the pairs are found (docs/language.md section 15): `?:` is the lowest precedence and
right-associative, like `if/else`. Inside one bracket level the text is cut at commas, at a `:` that
no `?` is waiting for (a slice or dict colon), and at the words of a comprehension; each cut part is
one expression. In a part, the first `?` and the `:` that matches it (counting nested `?`) make the
condition (everything before the `?`), the value if true, and the value if false (everything after
the `:`, which may hold more `?:`).
"""

import bisect
import re
import types
from collections.abc import Iterator
from typing import Any, NamedTuple

from tel._spans import _characters, split_lines

__all__ = ["RewriteError", "join", "original_node", "pieces_of", "PositionMap"]


class RewriteError(Exception):
    """A `?` that cannot be paired. `index` is a character index into the original text."""

    def __init__(self, message: str, index: int) -> None:
        super().__init__(message)
        self.message, self.index = message, index


class Piece(NamedTuple):
    """`text is None`: the original text from `a` to `b`. Otherwise `text` is inserted and `a` is
    the place in the original that errors inside it are reported at."""

    text: str | None
    a: int
    b: int = 0


class _Tokens(NamedTuple):
    words: list[str]  # the structural tokens
    starts: list[int]
    ends: list[int]
    match: dict[int, int]  # an opening bracket's index to its closing bracket's
    prefix: list[int]  # prefix[k] is how many `?` there are in the tokens before k
    comments: list[
        tuple[int, int]
    ]  # where the comments are: a part's closing brackets go before one


# -- reading --------------------------------------------------------------------------------------

# One pass over text with no f-string. It yields strings and comments (to skip them), brackets, the
# separators, and the four words; everything else (names, numbers, operators) is not matched.
_STRUCTURE = re.compile(
    r"""(?P<s>[rRuUbB]{0,2}(?:'''(?:[^\\]|\\.)*?(?:'''|\Z)|\"\"\"(?:[^\\]|\\.)*?(?:\"\"\"|\Z)"""
    r"""|'(?:[^'\\\n]|\\.)*'?|"(?:[^"\\\n]|\\.)*"?))"""
    r"""|(?P<c>\#[^\n]*)"""
    r"""|(?P<o>[()\[\]{}?:,])"""
    r"""|(?P<w>(?<!\w)(?:for|in|if|else)(?!\w))""",
    re.DOTALL,
)
_HAS_FSTRING = re.compile(r"(?<!\w)(?:[fFtT][rR]?|[rR][fFtT])['\"]")
_STRING_START = re.compile(r"([rRuUbBfFtT]{0,2})('''|\"\"\"|'|\")")
_WORD = re.compile(r"\w+")
_WORDS = frozenset({"for", "in", "if", "else"})


def _link(
    words: list[str], starts: list[int], ends: list[int], comments: list[tuple[int, int]]
) -> _Tokens | None:
    """Pair the brackets and count the `?`; None when there is no `?` to rewrite."""
    match: dict[int, int] = {}
    prefix = [0]
    stack: list[int] = []
    count = 0
    for i, word in enumerate(words):
        if word == "?":
            count += 1
        elif word in ("(", "[", "{"):
            stack.append(i)
        elif word in (")", "]", "}") and stack:
            match[stack.pop()] = i
        prefix.append(count)
    return _Tokens(words, starts, ends, match, prefix, comments) if count else None


def _tokens_fast(text: str) -> _Tokens | None:
    words: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    comments: list[tuple[int, int]] = []
    for m in _STRUCTURE.finditer(text):
        kind = m.lastgroup
        if kind == "s":
            continue
        a, b = m.span()
        if kind == "c":
            comments.append((a, b))
            continue
        if kind == "o" and text.startswith(":=", a):
            continue
        words.append(text[a:b])
        starts.append(a)
        ends.append(b)
    return _link(words, starts, ends, comments)


class _Scanner:
    """The structural tokens of text that has f-strings: a scanner that goes into their fields."""

    def __init__(self, text: str) -> None:
        self.s = text
        self.words: list[str] = []
        self.starts: list[int] = []
        self.ends: list[int] = []
        self.comments: list[tuple[int, int]] = []

    def emit(self, word: str, a: int, b: int) -> None:
        self.words.append(word)
        self.starts.append(a)
        self.ends.append(b)

    def tokens(self) -> _Tokens | None:
        self.expression(0, False)
        return _link(self.words, self.starts, self.ends, self.comments)

    def expression(self, i: int, field: bool) -> int:
        """Scan expression text from `i`. In a field, stop at the `}` that closes it, at a `!`
        that starts a conversion, and at a `:` that starts a format spec (one no `?` waits for)."""
        s, n = self.s, len(self.s)
        waiting = [0]  # `?` waiting for their `:`, one count per open bracket
        while i < n:
            c = s[i]
            if c in " \t\r\n\f":
                i += 1
            elif c == "#":
                end = s.find("\n", i)
                end = n if end < 0 else end
                self.comments.append((i, end))
                i = end
            elif c in "([{":
                self.emit(c, i, i + 1)
                waiting.append(0)
                i += 1
            elif c in ")]}":
                if field and len(waiting) == 1 and c == "}":
                    return i
                self.emit(c, i, i + 1)
                if len(waiting) > 1:
                    waiting.pop()
                i += 1
            elif c == "?":
                self.emit(c, i, i + 1)
                waiting[-1] += 1
                i += 1
            elif c == ",":
                self.emit(c, i, i + 1)
                i += 1
            elif c == ":":
                if waiting[-1]:
                    waiting[-1] -= 1
                elif field and len(waiting) == 1:
                    return i
                elif s.startswith(":=", i):
                    i += 2
                    continue
                self.emit(c, i, i + 1)
                i += 1
            elif c == "!" and field and len(waiting) == 1 and not s.startswith("!=", i):
                return i
            elif c.isdigit():
                i = _WORD.match(s, i).end()  # type: ignore[union-attr]
            elif c in "'\"" or c.isalpha() or c == "_":
                i = self.word_or_string(i)
            else:
                i += 1
        return i

    def word_or_string(self, i: int) -> int:
        s = self.s
        m = _STRING_START.match(s, i)
        if m is not None and not (i and (s[i - 1].isalnum() or s[i - 1] == "_")):
            return self.string(m.end(1), m.group(1).lower(), m.group(2))
        word = _WORD.match(s, i)
        assert word is not None
        if word.group() in _WORDS:
            self.emit(word.group(), i, word.end())
        return word.end()

    def string(self, quote: int, prefix: str, delimiter: str) -> int:
        s, n = self.s, len(self.s)
        i = quote + len(delimiter)
        if "f" in prefix or "t" in prefix:
            return self.fstring(i, delimiter)
        while i < n:
            if s[i] == "\\":
                i += 2
            elif s.startswith(delimiter, i):
                return i + len(delimiter)
            else:
                i += 1
        return n

    def fstring(self, i: int, delimiter: str, spec: bool = False) -> int:
        """The inside of an f-string, up to its closing quote (or, in a format spec, its `}`)."""
        s, n = self.s, len(self.s)
        while i < n:
            c = s[i]
            if spec and c == "}":
                return i
            if not spec and s.startswith(delimiter, i):
                return i + len(delimiter)
            if c == "\\":
                i += 2
            elif c == "{" and not spec and s.startswith("{{", i):
                i += 2
            elif c == "}" and not spec and s.startswith("}}", i):
                i += 2
            elif c == "{":
                self.emit(c, i, i + 1)
                i = self.expression(i + 1, True)
                if i < n and s[i] == "!":
                    self.emit("!", i, i + 1)
                    i += 1
                    while i < n and (s[i].isalnum() or s[i] == "_"):
                        i += 1
                if i < n and s[i] == ":":
                    self.emit(":", i, i + 1)
                    i = self.fstring(i + 1, delimiter, True)
                if i < n and s[i] == "}":
                    self.emit("}", i, i + 1)
                    i += 1
            else:
                i += 1
        return n


# -- rewriting ------------------------------------------------------------------------------------


def _copy(a: int, b: int) -> list[Piece]:
    return [Piece(None, a, b)] if b > a else []


class _Rewrite:
    def __init__(self, text: str, tokens: _Tokens) -> None:
        self.s = text
        self.t = tokens

    def top(self, lo: int, hi: int) -> Iterator[tuple[int, str]]:
        """The tokens of [lo, hi) that are not inside a bracket: their index and word."""
        words, match = self.t.words, self.t.match
        i = lo
        while i < hi:
            yield i, words[i]
            i = match[i] + 1 if i in match else i + 1

    def level(self, lo: int, hi: int, ca: int, cb: int) -> list[Piece]:
        """The tokens of [lo, hi) between the characters `ca` and `cb` (the inside of a bracket, or
        the whole text), cut into parts; each part with a `?` in it is rewritten."""
        t = self.t
        parts: list[tuple[int, int, int, int]] = []  # tokens, then characters
        start, char, waiting, in_for, after_for = lo, ca, 0, False, False
        for i, word in self.top(lo, hi):
            cut = False
            if word == "?":
                waiting += 1
            elif word == ":":
                if waiting:
                    waiting -= 1
                else:
                    cut = True
            elif word == "," or word == "!":
                cut = True  # `!` starts the conversion of an f-string field: `{c ? a : b!r}`
            elif word == "for":
                in_for = after_for = cut = True
            elif word == "in" and after_for:
                after_for = False
                cut = True
            elif word == "if" and in_for:
                cut = True
            if cut:
                parts.append((start, i, char, t.starts[i]))
                start, char = i + 1, t.ends[i]
        parts.append((start, hi, char, cb))
        pieces: list[Piece] = []
        cursor = ca
        for plo, phi, pa, pb in parts:
            if t.prefix[phi] - t.prefix[plo]:
                pb = self.before_comments(pa, pb)
                pieces += _copy(cursor, pa)
                pieces += self.part(plo, phi, pa, pb)
                cursor = pb
        return pieces + _copy(cursor, cb)

    def before_comments(self, ca: int, cb: int) -> int:
        """`cb`, or where the comments that end the text between `ca` and `cb` start: what the
        rewrite adds after a part must not end up inside a comment."""
        s = self.s
        for a, b in reversed(self.t.comments):
            if b <= cb and a >= ca and not s[b:cb].strip():
                cb = a
        return cb

    def part(self, lo: int, hi: int, ca: int, cb: int) -> list[Piece]:
        """One expression, between the characters `ca` and `cb`."""
        s, t = self.s, self.t
        question = next((i for i, word in self.top(lo, hi) if word == "?"), None)
        if question is None:
            return self.copy_around(lo, hi, ca, cb)
        for _, word in self.top(lo, hi):
            if word == "if" or word == "else":
                raise RewriteError(
                    "'?:' cannot be mixed with 'if ... else' without brackets", t.starts[question]
                )
        waiting, colon = 1, None
        for i, word in self.top(question + 1, hi):
            if word == "?":
                waiting += 1
            elif word == ":":
                waiting -= 1
                if not waiting:
                    colon = i
                    break
        mark, end = t.starts[question], t.ends[question]
        if colon is None:
            raise RewriteError("this '?' has no ':' to go with it", mark)
        if not s[ca:mark].strip():
            raise RewriteError("there is no condition before this '?'", mark)
        if not s[end : t.starts[colon]].strip():
            raise RewriteError("there is nothing between this '?' and its ':'", mark)
        if not s[t.ends[colon] : cb].strip():
            raise RewriteError("there is nothing after this ':'", t.starts[colon])
        return [
            Piece("(", ca),
            Piece("(", end),
            *self.part(question + 1, colon, end, t.starts[colon]),
            Piece(") if (", mark),
            *self.copy_around(lo, question, ca, mark),
            Piece(") else (", t.starts[colon]),
            *self.part(colon + 1, hi, t.ends[colon], cb),
            Piece("))", len(s[:cb].rstrip()) - 1),
        ]

    def copy_around(self, lo: int, hi: int, ca: int, cb: int) -> list[Piece]:
        """Text with no `?` of its own: copied, but for the brackets that have one inside."""
        t = self.t
        pieces: list[Piece] = []
        cursor = ca
        i = lo
        while i < hi:
            if i in t.match:
                j = t.match[i]
                if t.prefix[j] - t.prefix[i + 1]:
                    pieces += _copy(cursor, t.ends[i])
                    pieces += self.level(i + 1, j, t.ends[i], t.starts[j])
                    cursor = t.starts[j]
                i = j + 1
            else:
                i += 1
        return pieces + _copy(cursor, cb)


def pieces_of(text: str) -> list[Piece] | None:
    """The rewrite of `text` as pieces, or None when it has no `?` operator. Raises `RewriteError`
    for a `?` that cannot be paired."""
    if "?" not in text:
        return None
    tokens = _Scanner(text).tokens() if _HAS_FSTRING.search(text) else _tokens_fast(text)
    if tokens is None:
        return None
    return _Rewrite(text, tokens).level(0, len(tokens.words), 0, len(text))


def join(text: str, pieces: list[Piece]) -> str:
    """The rewritten text."""
    return "".join(text[p.a : p.b] if p.text is None else p.text for p in pieces)


# -- the way back ---------------------------------------------------------------------------------

_NEWLINE = re.compile(r"\r\n|\r|\n")


class PositionMap:
    """Positions in the rewritten text, mapped to positions in the original text."""

    def __init__(self, original: str, pieces: list[Piece]) -> None:
        self.original = original
        self.starts: list[int] = []  # where each piece starts in the rewritten text
        self.sources: list[int] = []  # and where in the original it comes from
        self.copied: list[bool] = []
        out = 0
        for p in pieces:
            self.starts.append(out)
            self.sources.append(p.a)
            self.copied.append(p.text is None)
            out += p.b - p.a if p.text is None else len(p.text)
        self.text = join(original, pieces)
        self.new_lines = split_lines(self.text)
        self.old_lines = split_lines(original)
        self.new_breaks = [m.end() for m in _NEWLINE.finditer(self.text)]
        self.old_breaks = [m.end() for m in _NEWLINE.finditer(original)]

    def to_original(self, index: int, end: bool = False) -> int:
        """The index in the original of a character of the rewritten text; for the end of a node
        (just past its last character) the index just past the original of its last character."""
        if end and index > 0:
            return self.to_original(index - 1) + 1
        k = bisect.bisect_right(self.starts, index) - 1
        return self.sources[k] + index - self.starts[k] if self.copied[k] else self.sources[k]

    def position(self, line: int, offset: int, end: bool = False) -> tuple[int, int]:
        """(line, UTF-8 byte offset) in the original for a (line, byte offset) in the rewritten
        text, the way `ast` counts them."""
        before = self.new_breaks[line - 2] if line > 1 else 0
        index = before + _characters(self.new_lines[line - 1], offset)
        mapped = self.to_original(index, end)
        old_line = bisect.bisect_right(self.old_breaks, mapped) + 1
        begin = self.old_breaks[old_line - 2] if old_line > 1 else 0
        return old_line, len(self.old_lines[old_line - 1][: mapped - begin].encode("utf-8"))


def move_syntax_error(exc: SyntaxError, original: str, pieces: list[Piece]) -> None:
    """Point a `SyntaxError` from the rewritten text at the original text."""
    places = PositionMap(original, pieces)
    line, offset = places.position(max(exc.lineno or 1, 1), max((exc.offset or 1) - 1, 0))
    exc.lineno = line
    exc.offset = _characters(places.old_lines[line - 1], offset) + 1
    exc.end_lineno = exc.end_offset = None


def original_node(source: str, node: Any) -> Any:
    """`node`, a node of the tree parsed from `source`, with the positions its text has in
    `source`. The same node when `source` was not rewritten."""
    if "?" not in source or getattr(node, "lineno", None) is None:
        return node
    try:
        pieces = pieces_of(source)
    except RewriteError:
        return node
    if pieces is None:
        return node
    places = PositionMap(source, pieces)
    line, offset = places.position(node.lineno, node.col_offset)
    end_line, end_offset = places.position(node.end_lineno, node.end_col_offset, end=True)
    return types.SimpleNamespace(
        lineno=line, col_offset=offset, end_lineno=end_line, end_col_offset=end_offset
    )
