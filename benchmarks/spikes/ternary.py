#!/usr/bin/env python3
"""Spike for D14: `cond ? a : b` as a read-time rewrite into `((a) if (cond) else (b))`.

Question (docs/decisions.md D14): is the C-style conditional cheap enough to add? The prototype
rewrites the text before `ast.parse`, so nothing new reaches the whitelist or the compiler, and then
moves the positions of the tree back to the original text so errors point where the author wrote.

What it measures and checks:

1. **Correctness of the rewrite.** 30,000 random pairs `(?: text, if/else text)`: the rewritten text
   must parse to the same tree as the reference spelling. Contexts: calls, lists, dicts, subscripts,
   slices, comprehensions (element, filter), f-string fields and format specs, nested ternaries in
   the middle and the else part, any spacing. Every `Name` in the remapped tree must point at its
   own spelling in the original text.
2. **Cost.** Compile time and memory of `tel.compile_expression`, with the rewrite patched into the
   parser, for text without `?` (the check every expression pays), text with a `?` only inside a
   string, and the real thing. Evaluation is the same tree, so it is the same speed by construction;
   one run confirms it.
3. **Error positions**, a table: where the caret lands for errors in each part.
4. **YAML**: what a plain scalar does with ` : `.

Not TEL code: the numbers and the table say whether the design is affordable.

    python benchmarks/spikes/ternary.py
"""

import ast
import bisect
import itertools
import random
import re
import statistics
import sys
import timeit
import types
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
import tel  # noqa: E402
import tel._parser as parser  # noqa: E402
import tel._spans as _spans  # noqa: E402
import tel.template as template_module  # noqa: E402
from tel._spans import _characters, split_lines  # noqa: E402

# -- the rewrite ----------------------------------------------------------------------------------

_NAME = re.compile(r"[^\W\d]\w*")
_STRING_PREFIXES = {"r", "u", "b", "f", "t", "br", "rb", "fr", "rf", "tr", "rt"}
_OPEN, _CLOSE = "([{", ")]}"
_NEWLINE = re.compile(r"\r\n|\r|\n")


class RewriteError(Exception):
    """The `?` could not be paired up; `index` is a character index into the original text."""

    def __init__(self, message: str, index: int) -> None:
        super().__init__(message)
        self.message, self.index = message, index


class Tok(NamedTuple):
    kind: str  # name, num, str, fstr, op
    a: int
    b: int
    q: int = 0  # `?` operators inside (1 for a `?`, the total for an f-string)
    items: tuple[Any, ...] = ()  # f-string: ("raw", a, b) and ("expr", TokList, a, b)


class TokList:
    """The tokens of one lexical level, brackets flat, with their partners."""

    def __init__(self) -> None:
        self.t: list[Tok] = []
        self.match: dict[int, int] = {}
        self.prefix: list[int] = [0]  # `?` operators in t[:k]
        self.q = 0

    def add(self, tok: Tok) -> None:
        self.t.append(tok)
        self.q += tok.q
        self.prefix.append(self.q)


Piece = tuple[Any, ...]  # ("c", a, b): original text; ("t", text, anchor): inserted text


class Rewriter:
    def __init__(self, text: str) -> None:
        self.s = text

    # lexing: only what it takes to know where strings, brackets, commas and colons are

    def lex(self, i: int, field: bool = False) -> tuple[TokList, int]:
        s, n = self.s, len(self.s)
        tl = TokList()
        openers: list[int] = []
        pending = [0]  # `?` still waiting for their `:`, per bracket depth
        while i < n:
            c = s[i]
            if c in " \t\r\n\f":
                i += 1
                continue
            if c == "#":
                end = s.find("\n", i)
                i = n if end < 0 else end
                continue
            m = _NAME.match(s, i)
            if m:
                j = m.end()
                if m.group().lower() in _STRING_PREFIXES and j < n and s[j] in "'\"":
                    i = self._string(tl, i, j, m.group().lower())
                else:
                    tl.add(Tok("name", i, j))
                    i = j
                continue
            if c in "'\"":
                i = self._string(tl, i, i, "")
                continue
            if c.isdigit() or (c == "." and i + 1 < n and s[i + 1].isdigit()):
                j = i + 1
                while j < n and (s[j].isalnum() or s[j] in "._"):
                    j += 1
                tl.add(Tok("num", i, j))
                i = j
                continue
            if c in _OPEN:
                openers.append(len(tl.t))
                pending.append(0)
                tl.add(Tok("op", i, i + 1))
            elif c in _CLOSE:
                if field and not openers and c == "}":
                    return tl, i
                if openers:
                    tl.match[openers.pop()] = len(tl.t)
                    pending.pop()
                tl.add(Tok("op", i, i + 1))
            elif c == "?":
                pending[-1] += 1
                tl.add(Tok("op", i, i + 1, q=1))
            elif c == ":":
                if pending[-1] > 0:
                    pending[-1] -= 1
                elif field and not openers:
                    return tl, i
                elif not (s.startswith(":=", i)):
                    pass
                tl.add(Tok("op", i, i + 1))
            elif c == "!" and field and not openers and not s.startswith("!=", i):
                return tl, i
            else:
                tl.add(Tok("op", i, i + 1))
            i += 1
        return tl, i

    def _string(self, tl: TokList, start: int, quote: int, prefix: str) -> int:
        s, n = self.s, len(self.s)
        delim = s[quote] * 3 if s.startswith(s[quote] * 3, quote) else s[quote]
        k = quote + len(delim)
        if "f" in prefix or "t" in prefix:
            items: list[Any] = []
            state = {"raw": start, "q": 0}
            k = self._body(k, delim, items, state, False)
            tl.add(Tok("fstr", start, k, state["q"], tuple(items)))
            return k
        while k < n:
            if s[k] == "\\":
                k += 2
            elif s.startswith(delim, k):
                k += len(delim)
                break
            else:
                k += 1
        k = min(k, n)
        tl.add(Tok("str", start, k))
        return k

    def _body(self, k: int, delim: str, items: list[Any], st: dict[str, int], spec: bool) -> int:
        """The inside of an f-string up to its closing quote (or, in a format spec, its `}`)."""
        s, n = self.s, len(self.s)
        while k < n:
            ch = s[k]
            if spec and ch == "}":
                return k
            if not spec and s.startswith(delim, k):
                items.append(("raw", st["raw"], k + len(delim)))
                return k + len(delim)
            if ch == "\\":
                k += 2
            elif ch == "{" and not spec and s.startswith("{{", k):
                k += 2
            elif ch == "{":
                items.append(("raw", st["raw"], k + 1))
                tl, stop = self.lex(k + 1, field=True)
                items.append(("expr", tl, k + 1, stop))
                st["q"] += tl.q
                k = stop
                st["raw"] = stop
                if k < n and s[k] == "!":
                    k += 1
                    while k < n and (s[k].isalnum() or s[k] == "_"):
                        k += 1
                if k < n and s[k] == ":":
                    k = self._body(k + 1, delim, items, st, True)
                if k < n and s[k] == "}":
                    k += 1
            elif ch == "}" and not spec and s.startswith("}}", k):
                k += 2
            else:
                k += 1
        if not spec:
            items.append(("raw", st["raw"], n))
        return n

    # rewriting

    def rewrite(self) -> list[Piece] | None:
        tl, _ = self.lex(0)
        if tl.q == 0:
            return None
        return self.level(tl, 0, len(tl.t), 0, len(self.s))

    def _top(self, tl: TokList, lo: int, hi: int) -> Any:
        """The tokens of [lo, hi) that are not inside a bracket (their index and token)."""
        i = lo
        while i < hi:
            yield i, tl.t[i]
            i = tl.match[i] + 1 if i in tl.match else i + 1

    def level(self, tl: TokList, lo: int, hi: int, ca: int, cb: int) -> list[Piece]:
        """The content between two brackets (or the whole text), split at commas, colons that
        pair with no `?`, and the words of a comprehension; each part is rewritten on its own."""
        s = self.s
        segments: list[tuple[int, int]] = []
        start, pending, in_for, after_for = lo, 0, False, False
        for i, tk in self._top(tl, lo, hi):
            word = s[tk.a : tk.b] if tk.kind in ("op", "name") else ""
            cut = False
            if word == "?":
                pending += 1
            elif word == ":":
                if pending:
                    pending -= 1
                else:
                    cut = True
            elif word == ",":
                cut = True
            elif word == "for":
                in_for = after_for = cut = True
            elif word == "in" and after_for:
                after_for = False
                cut = True
            elif word == "if" and in_for:
                cut = True
            if cut:
                segments.append((start, i))
                start = i + 1
        segments.append((start, hi))
        pieces: list[Piece] = []
        cursor = ca
        for slo, shi in segments:
            if slo >= shi:
                continue
            pieces += self._copy(cursor, tl.t[slo].a)
            pieces += self.segment(tl, slo, shi)
            cursor = tl.t[shi - 1].b
        return pieces + self._copy(cursor, cb)

    @staticmethod
    def _copy(a: int, b: int) -> list[Piece]:
        return [("c", a, b)] if b > a else []

    def segment(self, tl: TokList, lo: int, hi: int) -> list[Piece]:
        s, t = self.s, tl.t
        q = next((i for i, tk in self._top(tl, lo, hi) if tk.kind == "op" and s[tk.a] == "?"), None)
        if q is None:
            return self.run(tl, lo, hi)
        for _, tk in self._top(tl, lo, hi):
            if tk.kind == "name" and s[tk.a : tk.b] in ("if", "else"):
                raise RewriteError(
                    "'?:' cannot be mixed with 'if ... else' without brackets", t[q].a
                )
        pending, colon = 1, None
        for i, tk in self._top(tl, q + 1, hi):
            if tk.kind == "op" and s[tk.a] == "?":
                pending += 1
            elif tk.kind == "op" and s[tk.a] == ":":
                pending -= 1
                if not pending:
                    colon = i
                    break
        if colon is None:
            raise RewriteError("this '?' has no ':' to go with it", t[q].a)
        if q == lo:
            raise RewriteError("there is no condition before this '?'", t[q].a)
        if colon == q + 1:
            raise RewriteError("there is nothing between this '?' and its ':'", t[q].a)
        if colon + 1 == hi:
            raise RewriteError("there is nothing after this ':'", t[colon].a)
        start, end = t[lo].a, t[hi - 1].b
        return [
            ("t", "(", start),
            ("t", "(", t[q + 1].a),
            *self.segment(tl, q + 1, colon),
            ("t", ") if (", t[q].a),
            *self.run(tl, lo, q),
            ("t", ") else (", t[colon].a),
            *self.segment(tl, colon + 1, hi),
            ("t", "))", end - 1),
        ]

    def run(self, tl: TokList, lo: int, hi: int) -> list[Piece]:
        """Tokens with no `?` of their own: copied, but not brackets and f-strings that have one."""
        t = tl.t
        pieces: list[Piece] = []
        cursor = t[lo].a
        i = lo
        while i < hi:
            tk = t[i]
            if i in tl.match:
                j = tl.match[i]
                if tl.prefix[j] - tl.prefix[i + 1]:
                    pieces += self._copy(cursor, tk.b)
                    pieces += self.level(tl, i + 1, j, tk.b, t[j].a)
                    cursor = t[j].a
                i = j + 1
                continue
            if tk.kind == "fstr" and tk.q:
                pieces += self._copy(cursor, tk.a)
                for item in tk.items:
                    if item[0] == "raw":
                        pieces += self._copy(item[1], item[2])
                    else:
                        sub = item[1]
                        pieces += self.level(sub, 0, len(sub.t), item[2], item[3])
                cursor = tk.b
            i += 1
        return pieces + self._copy(cursor, t[hi - 1].b)


class Rewritten:
    """The rewritten text and the way back to the original."""

    def __init__(self, original: str, pieces: list[Piece]) -> None:
        self.original = original
        out: list[str] = []
        self.starts: list[int] = []
        self.table: list[tuple[int, int]] = []  # (source index, length or -1 for inserted text)
        pos = 0
        for p in pieces:
            self.starts.append(pos)
            if p[0] == "c":
                out.append(original[p[1] : p[2]])
                self.table.append((p[1], p[2] - p[1]))
                pos += p[2] - p[1]
            else:
                out.append(p[1])
                self.table.append((p[2], -1))
                pos += len(p[1])
        self.text = "".join(out)
        self.new_lines = [m.end() for m in _NEWLINE.finditer(self.text)]
        self.old_lines = [m.end() for m in _NEWLINE.finditer(original)]
        self.new_split, self.old_split = split_lines(self.text), split_lines(original)
        self.ascii = original.isascii() and self.text.isascii()

    def to_old(self, index: int) -> int:
        k = bisect.bisect_right(self.starts, index) - 1
        src, n = self.table[k]
        return src if n < 0 else src + index - self.starts[k]

    def to_old_end(self, index: int) -> int:
        return self.to_old(index - 1) + 1 if index > 0 else self.to_old(index)

    def _index(self, line: int, col: int, split: list[str], starts: list[int]) -> int:
        before = starts[line - 2] if line > 1 else 0
        return before + (col if self.ascii else _characters(split[line - 1], col))

    def _line_col(self, index: int) -> tuple[int, int]:
        line = bisect.bisect_right(self.old_lines, index) + 1
        begin = self.old_lines[line - 2] if line > 1 else 0
        col = index - begin
        if not self.ascii:
            col = len(self.old_split[line - 1][:col].encode("utf-8"))
        return line, col

    def map_position(self, line: int, col: int, end: bool = False) -> tuple[int, int]:
        index = self._index(line, col, self.new_split, self.new_lines)
        return self._line_col(self.to_old_end(index) if end else self.to_old(index))

    def remap(self, tree: ast.AST) -> None:
        """Give every node the position its text has in the original."""
        for node in ast.walk(tree):
            if "lineno" not in node._attributes:
                continue
            node.lineno, node.col_offset = self.map_position(node.lineno, node.col_offset)  # type: ignore[attr-defined]
            end_line, end_col = self.map_position(
                node.end_lineno,  # type: ignore[attr-defined]
                node.end_col_offset,  # type: ignore[attr-defined]
                end=True,
            )
            node.end_lineno, node.end_col_offset = end_line, end_col  # type: ignore[attr-defined]


# The fast path: a text with no f-string is read with one regex pass that yields only what the
# rewrite needs (strings and comments, to skip them; brackets, `?`, `:`, `,` and four keywords).
_SPARSE = re.compile(
    r"""(?P<s>[rRuUbB]{0,2}(?:'''(?:[^\\]|\\.)*?(?:'''|\Z)|\"\"\"(?:[^\\]|\\.)*?(?:\"\"\"|\Z)"""
    r"""|'(?:[^'\\\n]|\\.)*'?|"(?:[^"\\\n]|\\.)*"?))"""
    r"""|(?P<c>\#[^\n]*)"""
    r"""|(?P<o>[()\[\]{}?:,])"""
    r"""|(?P<w>(?<!\w)(?:for|in|if|else)(?!\w))""",
    re.DOTALL,
)
_FSTRING = re.compile(r"(?<!\w)(?:[fFtT][rR]?|[rR][fFtT])[\'\"]")


class Sparse:
    """The same rewrite as `Rewriter`, over the structural tokens only."""

    def __init__(self, text: str) -> None:
        self.s = text
        self.ks: list[str] = []
        self.aa: list[int] = []
        self.bb: list[int] = []
        self.match: dict[int, int] = {}
        self.prefix = [0]  # `?` in tokens[:k]
        stack: list[int] = []
        q = 0
        for m in _SPARSE.finditer(text):
            kind = m.lastgroup
            if kind == "s" or kind == "c":
                continue
            a, b = m.span()
            k = text[a:b]
            if k == ":" and text.startswith(":=", a):
                continue
            if k in "([{":
                stack.append(len(self.ks))
            elif k in ")]}" and stack:
                self.match[stack.pop()] = len(self.ks)
            elif k == "?":
                q += 1
            self.ks.append(k)
            self.aa.append(a)
            self.bb.append(b)
            self.prefix.append(q)
        self.q = q

    def pieces(self) -> list[Piece] | None:
        if not self.q:
            return None
        return self.level(0, len(self.ks), 0, len(self.s))

    def _top(self, lo: int, hi: int) -> Any:
        i, ks, match = lo, self.ks, self.match
        while i < hi:
            yield i, ks[i]
            i = match[i] + 1 if i in match else i + 1

    def level(self, lo: int, hi: int, ca: int, cb: int) -> list[Piece]:
        segments: list[tuple[int, int, int, int]] = []  # token range and char range
        start, char, pending, in_for, after_for = lo, ca, 0, False, False
        for i, word in self._top(lo, hi):
            cut = False
            if word == "?":
                pending += 1
            elif word == ":":
                if pending:
                    pending -= 1
                else:
                    cut = True
            elif word == ",":
                cut = True
            elif word == "for":
                in_for = after_for = cut = True
            elif word == "in" and after_for:
                after_for = False
                cut = True
            elif word == "if" and in_for:
                cut = True
            if cut:
                segments.append((start, i, char, self.aa[i]))
                start, char = i + 1, self.bb[i]
        segments.append((start, hi, char, cb))
        pieces: list[Piece] = []
        cursor = ca
        for tlo, thi, cs, ce in segments:
            if self.prefix[thi] - self.prefix[tlo]:
                pieces += _copy(cursor, cs)
                pieces += self.segment(tlo, thi, cs, ce)
                cursor = ce
        return pieces + _copy(cursor, cb)

    def segment(self, lo: int, hi: int, cs: int, ce: int) -> list[Piece]:
        aa, bb, s = self.aa, self.bb, self.s
        q = next((i for i, w in self._top(lo, hi) if w == "?"), None)
        if q is None:
            return self.run(lo, hi, cs, ce)
        for _, w in self._top(lo, hi):
            if w == "if" or w == "else":
                raise RewriteError(
                    "'?:' cannot be mixed with 'if ... else' without brackets", aa[q]
                )
        pending, colon = 1, None
        for i, w in self._top(q + 1, hi):
            if w == "?":
                pending += 1
            elif w == ":":
                pending -= 1
                if not pending:
                    colon = i
                    break
        if colon is None:
            raise RewriteError("this '?' has no ':' to go with it", aa[q])
        if not s[cs : aa[q]].strip():
            raise RewriteError("there is no condition before this '?'", aa[q])
        if not s[bb[q] : aa[colon]].strip():
            raise RewriteError("there is nothing between this '?' and its ':'", aa[q])
        if not s[bb[colon] : ce].strip():
            raise RewriteError("there is nothing after this ':'", aa[colon])
        last = len(s[:ce].rstrip()) - 1
        return [
            ("t", "(", cs),
            ("t", "(", bb[q]),
            *self.segment(q + 1, colon, bb[q], aa[colon]),
            ("t", ") if (", aa[q]),
            *self.run(lo, q, cs, aa[q]),
            ("t", ") else (", aa[colon]),
            *self.segment(colon + 1, hi, bb[colon], ce),
            ("t", "))", last),
        ]

    def run(self, lo: int, hi: int, cs: int, ce: int) -> list[Piece]:
        pieces: list[Piece] = []
        cursor = cs
        i = lo
        match, prefix = self.match, self.prefix
        while i < hi:
            if i in match:
                j = match[i]
                if prefix[j] - prefix[i + 1]:
                    pieces += _copy(cursor, self.bb[i])
                    pieces += self.level(i + 1, j, self.bb[i], self.aa[j])
                    cursor = self.aa[j]
                i = j + 1
            else:
                i += 1
        return pieces + _copy(cursor, ce)


def _copy(a: int, b: int) -> list[Piece]:
    return [("c", a, b)] if b > a else []


def pieces_of(text: str) -> list[Piece] | None:
    """The rewrite as pieces of the original and inserted text; None when there is nothing to do."""
    if "?" not in text:
        return None
    if _FSTRING.search(text):
        return Rewriter(text).rewrite()
    return Sparse(text).pieces()


def join(text: str, pieces: list[Piece]) -> str:
    return "".join(text[p[1] : p[2]] if p[0] == "c" else p[1] for p in pieces)


def rewrite(text: str) -> Rewritten | None:
    """None when no `?` is outside strings and comments; RewriteError when one is unpaired."""
    pieces = pieces_of(text)
    return None if pieces is None else Rewritten(text, pieces)


# -- patching the real parser ---------------------------------------------------------------------

_original_read = parser._read
_original_reads_as_expression = parser.reads_as_expression
_original_template_reads = template_module.reads_as_expression
_original_node_span = _spans.node_span


def _read_with_rewrite(text: str, origin: Any, limits: Any) -> ast.AST:
    """The parser's `_read`, for text that may hold `?:`. Nothing is mapped back here: the tree has
    the positions of the rewritten text and `node_span` maps them when an error is made."""
    try:
        pieces = pieces_of(text)
    except RewriteError as exc:
        line, column = parser._position(text, exc.index)
        raise tel.TelSyntaxError(
            exc.message,
            code="syntax-error",
            source=text,
            line=line,
            column=column,
            end_column=column + 1,
            origin=origin,
        ) from None
    if pieces is None:
        return _original_read(text, origin, limits)
    try:
        return parser._parse_quietly(join(text, pieces))
    except SyntaxError as exc:
        rw = Rewritten(text, pieces)
        line, col = rw.map_position(max(exc.lineno or 1, 1), max((exc.offset or 1) - 1, 0))
        exc.lineno, exc.offset = line, _characters(rw.old_split[line - 1], col) + 1
        exc.end_lineno = exc.end_offset = None
        raise parser._syntax_error(text, origin, limits, exc) from None
    except RecursionError, MemoryError:
        raise parser._too_deep(text, origin, limits) from None


def _node_span_with_rewrite(source: str, node: ast.AST) -> tuple[int, int, int | None]:
    """`node_span` for a node of a rewritten text: the rewrite is redone now that it is needed."""
    try:
        rw = rewrite(source)
    except RewriteError:
        rw = None
    if rw is None or getattr(node, "lineno", None) is None:
        return _original_node_span(source, node)
    line, col = rw.map_position(node.lineno, node.col_offset)  # type: ignore[attr-defined]
    end_line, end_col = rw.map_position(
        node.end_lineno,  # type: ignore[attr-defined]
        node.end_col_offset,  # type: ignore[attr-defined]
        end=True,
    )
    moved = types.SimpleNamespace(
        lineno=line, col_offset=col, end_lineno=end_line, end_col_offset=end_col
    )
    return _original_node_span(source, moved)  # type: ignore[arg-type]


def _reads_as_expression_with_rewrite(text: str) -> bool:
    try:
        pieces = pieces_of(text.strip())
    except RewriteError:
        return False
    return _original_reads_as_expression(text if pieces is None else join(text.strip(), pieces))


def patch() -> None:
    parser._read = _read_with_rewrite  # type: ignore[assignment]
    parser.node_span = _node_span_with_rewrite  # type: ignore[assignment]
    _spans.node_span = _node_span_with_rewrite  # type: ignore[assignment]
    template_module.reads_as_expression = _reads_as_expression_with_rewrite


def unpatch() -> None:
    parser._read = _original_read  # type: ignore[assignment]
    parser.node_span = _original_node_span  # type: ignore[assignment]
    _spans.node_span = _original_node_span  # type: ignore[assignment]
    template_module.reads_as_expression = _original_template_reads


# -- 1. correctness -------------------------------------------------------------------------------

ATOMS = ["a", "b", "c", "n", "1", "2.5", "'?'", "':'", "'a?b:c'", "x.y", "f(1, 2)", "d['k']"]
CONDS = ["a", "not a", "a < b", "a or b", "a and not b", "n + 1", "x in xs", "a is not None"]


def spaces(rng: random.Random) -> tuple[str, str]:
    return rng.choice([(" ", " "), ("", ""), (" ", ""), ("", " "), ("  ", "\t")])


def gen(rng: random.Random, depth: int) -> tuple[str, str]:
    """A pair: the expression with `?:`, and the same with `if ... else` (the reference)."""
    kind = rng.random()
    if depth <= 0 or kind < 0.25:
        atom = rng.choice(ATOMS)
        return atom, atom
    if kind < 0.55:
        c = rng.choice(CONDS)
        if rng.random() < 0.3:
            ct, cp = gen(rng, depth - 1)
            c, cond_p = f"({ct})", f"({cp})"
        else:
            cond_p = c
        mt, mp = gen(rng, depth - 1)
        et, ep = gen(rng, depth - 1)
        s1, s2 = spaces(rng)
        s3, s4 = spaces(rng)
        return f"{c}{s1}?{s2}{mt}{s3}:{s4}{et}", f"(({mp}) if ({cond_p}) else ({ep}))"
    parts = [gen(rng, depth - 1) for _ in range(2)]
    (t1, p1), (t2, p2) = parts
    form = rng.choice(["call", "list", "dict", "index", "slice", "comp", "filter", "fstr", "spec"])
    if form == "call":
        return f"f({t1}, {t2})", f"f({p1}, {p2})"
    if form == "list":
        return f"[{t1}, {t2}]", f"[{p1}, {p2}]"
    if form == "dict":
        return f"{{'k': {t1}, 'j': {t2}}}", f"{{'k': {p1}, 'j': {p2}}}"
    if form == "index":
        return f"x[{t1}]", f"x[{p1}]"
    if form == "slice":
        return f"x[{t1} : {t2}]", f"x[{p1} : {p2}]"
    if form == "comp":
        return f"[{t1} for v in xs]", f"[{p1} for v in xs]"
    if form == "filter":
        return f"[v for v in xs if {t1}]", f"[v for v in xs if {p1}]"
    if form == "fstr":
        return f'f"{{ {t1} }} {{ {t2} }}"', f'f"{{ {p1} }} {{ {p2} }}"'
    return f'f"{{ {t1} :>{{ {t2} }}}}"', f'f"{{ {p1} :>{{ {p2} }}}}"'


NO_TERNARY = [
    "'?'",
    "'what? yes: no'",
    'f"{x:?>5}"',
    'f"{x!r:?^9}"',
    'f"{x:{w}?}"',
    "a[1:2]",
    "{'a': 1, 'b': [1, 2][0:1]}",
    "[x for x in xs if x]",
    "a  # is it? maybe: no",
    "'a' if b else 'c?'",
    "x if y else '?:'",
]


def names_point_home(tree: ast.AST, original: str) -> list[str]:
    bad = []
    lines = split_lines(original)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            end_line = node.end_lineno or node.lineno
            got = lines[node.lineno - 1][node.col_offset : node.end_col_offset]
            if node.lineno != end_line or got != node.id:
                bad.append(f"{node.id} -> {got!r}")
    return bad


def check_correctness(count: int = 30000, seed: int = 14) -> dict[str, Any]:
    rng = random.Random(seed)
    stats = {
        "cases": 0,
        "with_ternary": 0,
        "tree_mismatch": [],
        "position_mismatch": [],
        "errors": [],
        "fast_cases": 0,
        "fast_vs_slow": [],
    }
    for _ in range(count):
        text, reference = gen(rng, rng.randint(1, 4))
        rw = rewrite(text)
        stats["cases"] += 1
        if rw is None:
            if text != reference:
                stats["errors"].append(("no rewrite", text))
            continue
        stats["with_ternary"] += 1
        if not _FSTRING.search(text):
            stats["fast_cases"] += 1
            slow = Rewriter(text).rewrite()
            same = slow is not None and ast.dump(
                ast.parse(join(text, slow), mode="eval")
            ) == ast.dump(ast.parse(rw.text, mode="eval"))
            if not same:
                stats["fast_vs_slow"].append((text, rw.text, slow and join(text, slow)))
        try:
            tree = ast.parse(rw.text, mode="eval")
            want = ast.parse(reference, mode="eval")
        except SyntaxError as exc:
            stats["errors"].append((str(exc), text, rw.text))
            continue
        if ast.dump(tree) != ast.dump(want):
            stats["tree_mismatch"].append((text, rw.text, reference))
            continue
        rw.remap(tree)
        bad = names_point_home(tree, text)
        if bad:
            stats["position_mismatch"].append((text, bad[:3]))
    stats["no_ternary_unchanged"] = all(rewrite(t) is None for t in NO_TERNARY)
    return stats


# -- 2. cost --------------------------------------------------------------------------------------


def per_us(fn: Any, rounds: int = 9, min_time: float = 0.15) -> float:
    timer = timeit.Timer(fn)
    timer.timeit(20)
    number = 1
    while timer.timeit(number) < min_time:
        number *= 2
    return statistics.median(t / number * 1e6 for t in timer.repeat(rounds, number))


COSTS = [
    # name, source with ?:, the same with if/else, the same with no conditional
    ("simple", "battery < 20 ? 'low' : 'ok'", "'low' if battery < 20 else 'ok'"),
    ("nested", "a < 1 ? 'x' : a < 2 ? 'y' : 'z'", "'x' if a < 1 else 'y' if a < 2 else 'z'"),
    (
        "in call",
        "max(a, b ? c : d) + len(t ? s : 'none')",
        "max(a, (c if b else d)) + len((s if t else 'none'))",
    ),
    (
        "comprehension",
        "[w.name for w in workspaces if w.active ? w.windows > 1 : w.windows > 5]",
        "[w.name for w in workspaces if (w.windows > 1 if w.active else w.windows > 5)]",
    ),
    (
        "f-string",
        "f\"{ok ? 'yes' : 'no'}: {battery}%\"",
        "f\"{('yes' if ok else 'no')}: {battery}%\"",
    ),
]
NO_QUESTION = [
    ("plain", "battery + 1"),
    ("long", "'critical' if battery < 10 else 'low' if battery < 20 else f'{battery}%'"),
    ("? in a string", "'is it ok?' + title"),
    ("? in an f-string spec", "f'{battery:?>5}'"),
]


def compile_us(source: str) -> float:
    return per_us(lambda: tel.compile_expression(source, language="0.1"))


def bytes_each(source: str, copies: int = 3000) -> float:
    import gc
    import tracemalloc

    tel.compile_expression(source, language="0.1")  # warm the free lists
    gc.collect()
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    keep = [tel.compile_expression(source, language="0.1") for _ in range(copies)]
    after = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()
    del keep
    return (after - before) / copies


def measure_cost() -> list[list[str]]:
    rows = [
        [
            "source",
            "compile before",
            "compile, `?` check only",
            "compile, rewritten",
            "ratio",
            "bytes before",
            "bytes after",
        ]
    ]
    scope = tel.MapScope(
        {
            "battery": 12, "a": 1, "b": 0, "c": 3, "d": 4, "t": "x", "s": "y", "ok": True,
            "title": "T", "workspaces": [{"name": "w", "active": True, "windows": 3}],
        }
    )  # fmt: skip
    for name, source in NO_QUESTION:
        unpatch()
        before = compile_us(source)
        b_before = bytes_each(source)
        patch()
        after = compile_us(source)
        b_after = bytes_each(source)
        rows.append(
            [
                f"{name}: `{source}`",
                f"{before:.2f} µs",
                f"{after:.2f} µs",
                "",
                f"{after / before:.3f}x",
                f"{b_before:,.0f}",
                f"{b_after:,.0f}",
            ]
        )
    for name, ternary, reference in COSTS:
        unpatch()
        before = compile_us(reference)
        b_before = bytes_each(reference)
        compiled_reference = tel.compile_expression(reference, language="0.1")
        eval_before = per_us(lambda e=compiled_reference: e.evaluate(scope))
        patch()
        check = compile_us(reference)
        rewritten = compile_us(ternary)
        b_after = bytes_each(ternary)
        compiled_ternary = tel.compile_expression(ternary, language="0.1")
        eval_after = per_us(lambda e=compiled_ternary: e.evaluate(scope))
        rows.append(
            [
                f"{name}: `{ternary}`",
                f"{before:.2f} µs",
                f"{check:.2f} µs",
                f"{rewritten:.2f} µs",
                f"{rewritten / before:.2f}x",
                f"{b_before:,.0f}",
                f"{b_after:,.0f}",
            ]
        )
        rows.append(
            [
                f"  evaluate, same value: {eval_before:.3f} µs vs {eval_after:.3f} µs",
                "",
                "",
                "",
                "",
                "",
                "",
            ]
        )
    unpatch()
    return rows


# -- 3. error positions ---------------------------------------------------------------------------

ERRORS = [
    # (source, scope values) : an evaluation error in each part
    ("ok ? missing : 1", {"ok": True}),
    ("ok ? 1 : missing", {"ok": False}),
    ("missing ? 1 : 2", {}),
    ("ok ? a.nope : 1", {"ok": True, "a": {"k": 1}}),
    ("ok ? 1 : 1 / 0", {"ok": False}),
    ("n > 1 ? 'big' : n == 0 ? 1 / n : 'small'", {"n": 0}),
    ("[x ? 1 / v : 0 for v in vs]", {"x": True, "vs": [1, 0]}),
    ("f\"{ok ? 'a' : missing}\"", {"ok": False}),
    ("ok ? 'é' : missing", {"ok": False}),
    ("ok ?\n  missing\n  : 1", {"ok": True}),
    ("max(1, ok ? missing : 2)", {"ok": True}),
]
COMPILE_ERRORS = [
    "ok ? __class__ : 1",
    "ok ? 1 : a.__dict__",
    "ok ? open('x') : 1",
    "ok ? 1",
    "ok ? : 1",
    "? 1 : 2",
    "ok ? 1 :",
    "(ok ? 1 : 2",
    "ok ? 1 : 2 : 3",
    "ok ? 1 : 2)",
    "ok ? 1 if x else 2 : 3",
    "ok ? 1 : 2 if x else 3",
    "a ?? b",
    "ok ? (x := 1) : 2",
    "f(ok ? 1, 2 : 3)",
    "x[ok ? 1 : 2 : 3]",
    "ok ? lambda: 1 : 2",
]


def measure_errors() -> list[str]:
    patch()
    out = ["evaluation errors:"]
    for source, values in ERRORS:
        try:
            tel.compile_expression(source, language="0.1").evaluate(tel.MapScope(values))
            out.append(f"  {source!r}: NO ERROR")
        except tel.TelError as exc:
            out.append(
                f"  {source!r}\n     > {exc.code} at {exc.line}:{exc.column}-{exc.end_column} {exc}"
            )
    out.append("compile errors:")
    for source in COMPILE_ERRORS:
        try:
            tel.compile_expression(source, language="0.1")
            out.append(f"  {source!r}: ACCEPTED")
        except tel.TelError as exc:
            out.append(
                f"  {source!r}\n     > {exc.code} at {exc.line}:{exc.column}-{exc.end_column} {exc}"
            )
    unpatch()
    return out


# -- 4. YAML --------------------------------------------------------------------------------------


def measure_yaml() -> list[str]:
    try:
        import yaml
    except ImportError:
        return ["PyYAML not available"]
    docs = [
        "x: a ? b : c",
        "x: a ? b :c",
        "x: a ?b: c",
        "x: a?b:c",
        "x: 'a ? b : c'",
        'x: "a ? b : c"',
        "- a ? b : c",
        "x: {{ a ? b : c }}",
        "x: Battery {{ a ? b : c }}%",
        "x: '{{ a ? b : c }}'",
        "x: a < 2 ? 'x' : 'y'",
        "x: [a ? b : c]",
        "x: {k: a ? b : c}",
        "x: a if b else c",
        "x: d['k']",
    ]
    out = []
    for doc in docs:
        try:
            out.append(f"  {doc!r:42} -> {yaml.safe_load(doc)!r}")
        except yaml.YAMLError as exc:
            out.append(f"  {doc!r:42} -> YAML ERROR: {str(exc).splitlines()[0]}")
    return out


def main() -> None:
    print("== 1. correctness")
    stats = check_correctness()
    print(f"cases {stats['cases']}, with a ternary {stats['with_ternary']}")
    for kind in ("tree_mismatch", "position_mismatch", "errors", "fast_vs_slow"):
        print(f"{kind}: {len(stats[kind])}")
    print(f"fast path: {stats['fast_cases']} of the cases")
    for kind in ("tree_mismatch", "position_mismatch", "errors", "fast_vs_slow"):
        for item in itertools.islice(stats[kind], 3):
            print("  ", kind, item)
    print("no-ternary texts untouched:", stats["no_ternary_unchanged"])
    print("\n== 2. cost")
    for row in measure_cost():
        print(" | ".join(row))
    print("\n== 3. error positions")
    print("\n".join(measure_errors()))
    print("\n== 4. YAML")
    print("\n".join(measure_yaml()))


if __name__ == "__main__":
    main()
