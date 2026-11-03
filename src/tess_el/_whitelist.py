"""What an expression may contain. Anything not listed here is refused.

Every entry is a decision (`docs/language.md`, sections 4 to 6); `tests/test_parser.py` pins each
list, so adding to one fails a test until the change is reviewed.
"""

import ast

#: The syntax-tree node types an expression may contain.
ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression, ast.Constant, ast.Name, ast.Load, ast.Store, ast.Attribute, ast.Subscript,
    ast.Slice, ast.UnaryOp, ast.Not, ast.USub, ast.UAdd, ast.BinOp, ast.Add, ast.Sub, ast.Mult,
    ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.BoolOp, ast.And, ast.Or, ast.Compare, ast.Eq,
    ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot, ast.IfExp,
    ast.JoinedStr, ast.FormattedValue, ast.List, ast.Tuple, ast.Set, ast.Dict, ast.ListComp,
    ast.DictComp, ast.SetComp, ast.GeneratorExp, ast.comprehension, ast.Call, ast.keyword,
    ast.Starred,
)  # fmt: skip

#: Node types that are refused by name, with the words used in the message.
DISALLOWED_NODES: dict[type[ast.AST], str] = {
    ast.Lambda: "a lambda",
    ast.NamedExpr: "an assignment expression (:=)",
    ast.Await: "await",
    ast.Yield: "yield",
    ast.YieldFrom: "yield",
    ast.TemplateStr: "a t-string (t'...')",
    ast.Interpolation: "a t-string (t'...')",
    ast.BitAnd: "the operator &",
    ast.BitOr: "the operator |",
    ast.BitXor: "the operator ^",
    ast.LShift: "the operator <<",
    ast.RShift: "the operator >>",
    ast.MatMult: "the operator @",
    ast.Invert: "the operator ~",
}

#: The functions an expression may call by name.
BUILTIN_NAMES: frozenset[str] = frozenset(
    """len min max abs round sum str int float bool sorted reversed range enumerate zip any all list
    dict tuple set isinstance clamp""".split()
)

#: The only types `isinstance` may be asked about.
ISINSTANCE_TYPES: frozenset[str] = frozenset("str int float bool list dict".split())

#: The methods an expression may call, by the type of the value they are called on.
STR_METHODS: frozenset[str] = frozenset(
    """lower upper title capitalize strip lstrip rstrip split splitlines join startswith endswith
    replace find count zfill isdigit isalpha center ljust rjust removeprefix removesuffix""".split()
)
SEQUENCE_METHODS: frozenset[str] = frozenset({"index", "count"})  # list and tuple
DICT_METHODS: frozenset[str] = frozenset({"get", "keys", "values", "items"})  # dict and mappings

#: Every method name some value may be called with; whether *this* value has it is checked when
#: the expression is evaluated.
METHOD_NAMES: frozenset[str] = STR_METHODS | SEQUENCE_METHODS | DICT_METHODS

#: Methods refused with a reason of their own: a format string can read attributes.
FORMAT_METHODS: frozenset[str] = frozenset({"format", "format_map"})
