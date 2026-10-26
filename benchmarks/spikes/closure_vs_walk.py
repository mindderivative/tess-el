#!/usr/bin/env python3
"""Spike for Step 3 phase 1: evaluate a checked `ast` by walking it, or by compiling it to closures?

Not TEL code: a deliberately small subset (constants, names, arithmetic, comparisons, `and`/`or`/
`not`, `if` expressions, attributes, subscripts, f-strings, calls to a few built-ins) so the two
strategies can be timed on the same expressions as `expr.py`.

* walk: a dispatch table keyed by node type, one step counted per node (what `expr.py` does).
* closures: each node becomes a Python function once; evaluating is calling the root. No per-node
  counting: a straight-line expression is bounded by the node limit, so only loops need a budget.

    python benchmarks/spikes/closure_vs_walk.py
"""

import ast
import operator
import sys
import timeit
from functools import partial
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmarks.workloads import SCOPE  # noqa: E402
from reference import expr_py  # noqa: E402

BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
CMPOPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
BUILTINS = {"len": len, "min": min, "max": max, "abs": abs, "round": round, "str": str, "int": int}


class MapScope:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values

    def lookup(self, name: str) -> Any:
        return self.values[name]


def attr(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value[name]
    return getattr(value, name)


# -- strategy 1: walk the tree, counting a step per node ---------------------------------


class Walker:
    def __init__(self, tree: ast.expr) -> None:
        self.tree = tree
        self.steps = 0
        self.table = {
            ast.Constant: self.constant,
            ast.Name: self.name,
            ast.BinOp: self.binop,
            ast.Compare: self.compare,
            ast.BoolOp: self.boolop,
            ast.UnaryOp: self.unary,
            ast.IfExp: self.ifexp,
            ast.Attribute: self.attribute,
            ast.Subscript: self.subscript,
            ast.Call: self.call,
            ast.JoinedStr: self.joined,
            ast.FormattedValue: self.formatted,
        }

    def evaluate(self, scope: MapScope) -> Any:
        self.steps = 0
        return self.visit(self.tree, scope)

    def visit(self, node: Any, scope: MapScope) -> Any:
        self.steps += 1
        if self.steps > 200_000:
            raise RuntimeError("too expensive")
        return self.table[type(node)](node, scope)

    def constant(self, node: Any, scope: Any) -> Any:
        return node.value

    def name(self, node: Any, scope: Any) -> Any:
        return scope.lookup(node.id)

    def binop(self, node: Any, scope: Any) -> Any:
        return BINOPS[type(node.op)](self.visit(node.left, scope), self.visit(node.right, scope))

    def compare(self, node: Any, scope: Any) -> Any:
        left = self.visit(node.left, scope)
        for op, comp in zip(node.ops, node.comparators, strict=True):
            right = self.visit(comp, scope)
            if not CMPOPS[type(op)](left, right):
                return False
            left = right
        return True

    def boolop(self, node: Any, scope: Any) -> Any:
        is_and = isinstance(node.op, ast.And)
        result: Any = None
        for v in node.values:
            result = self.visit(v, scope)
            if bool(result) != is_and:
                return result
        return result

    def unary(self, node: Any, scope: Any) -> Any:
        v = self.visit(node.operand, scope)
        return (
            (not v)
            if isinstance(node.op, ast.Not)
            else (-v if isinstance(node.op, ast.USub) else +v)
        )

    def ifexp(self, node: Any, scope: Any) -> Any:
        return self.visit(node.body if self.visit(node.test, scope) else node.orelse, scope)

    def attribute(self, node: Any, scope: Any) -> Any:
        return attr(self.visit(node.value, scope), node.attr)

    def subscript(self, node: Any, scope: Any) -> Any:
        return self.visit(node.value, scope)[self.visit(node.slice, scope)]

    def call(self, node: Any, scope: Any) -> Any:
        return BUILTINS[node.func.id](*[self.visit(a, scope) for a in node.args])

    def joined(self, node: Any, scope: Any) -> Any:
        return "".join(self.visit(v, scope) for v in node.values)

    def formatted(self, node: Any, scope: Any) -> Any:
        return format(self.visit(node.value, scope), "")


# -- strategy 2: compile each node to a closure once -------------------------------------


def compile_node(node: Any) -> Any:
    t = type(node)
    if t is ast.Constant:
        value = node.value
        return lambda scope: value
    if t is ast.Name:
        name = node.id
        return lambda scope: scope.lookup(name)
    if t is ast.BinOp:
        fn, left, right = BINOPS[type(node.op)], compile_node(node.left), compile_node(node.right)
        return lambda scope: fn(left(scope), right(scope))
    if t is ast.Compare:
        left = compile_node(node.left)
        if len(node.ops) == 1:
            fn, right = CMPOPS[type(node.ops[0])], compile_node(node.comparators[0])
            return lambda scope: fn(left(scope), right(scope))
        parts = [
            (CMPOPS[type(o)], compile_node(c))
            for o, c in zip(node.ops, node.comparators, strict=True)
        ]

        def chain(scope: Any) -> Any:
            lv = left(scope)
            for fn, comp in parts:
                rv = comp(scope)
                if not fn(lv, rv):
                    return False
                lv = rv
            return True

        return chain
    if t is ast.BoolOp:
        values = [compile_node(v) for v in node.values]
        is_and = isinstance(node.op, ast.And)

        def boolop(scope: Any) -> Any:
            result: Any = None
            for v in values:
                result = v(scope)
                if bool(result) != is_and:
                    return result
            return result

        return boolop
    if t is ast.UnaryOp:
        operand = compile_node(node.operand)
        if isinstance(node.op, ast.Not):
            return lambda scope: not operand(scope)
        if isinstance(node.op, ast.USub):
            return lambda scope: -operand(scope)
        return lambda scope: +operand(scope)
    if t is ast.IfExp:
        test, body, orelse = (
            compile_node(node.test),
            compile_node(node.body),
            compile_node(node.orelse),
        )
        return lambda scope: body(scope) if test(scope) else orelse(scope)
    if t is ast.Attribute:
        value, name = compile_node(node.value), node.attr
        return lambda scope: attr(value(scope), name)
    if t is ast.Subscript:
        value, index = compile_node(node.value), compile_node(node.slice)
        return lambda scope: value(scope)[index(scope)]
    if t is ast.Call:
        fn, args = BUILTINS[node.func.id], [compile_node(a) for a in node.args]
        return lambda scope: fn(*[a(scope) for a in args])
    if t is ast.JoinedStr:
        values = [compile_node(v) for v in node.values]
        return lambda scope: "".join([v(scope) for v in values])
    if t is ast.FormattedValue:
        value = compile_node(node.value)
        return lambda scope: format(value(scope), "")
    raise TypeError(t)


SOURCES = [
    ("name", "count"),
    ("add", "count + 1"),
    ("compare", "battery < 20 and not charging"),
    ("conditional", "'low' if battery < 20 else 'ok'"),
    ("arithmetic", "(width - 2 * pad) / 3 + offset"),
    ("attribute", "ws.name"),
    ("subscript", "items[0] + items[-1]"),
    ("fstring", "f'{battery}% ({state})'"),
]


def per_call_us(fn: Any) -> float:
    timer = timeit.Timer(fn)
    timer.timeit(100)
    number = 1
    while timer.timeit(number) < 0.2:
        number *= 2
    return sorted(t / number * 1e6 for t in timer.repeat(repeat=7, number=number))[3]


def main() -> None:
    mod = expr_py.load()
    scope = MapScope(SCOPE)
    old_scope = mod.MapScope(SCOPE)
    print(
        f"{'workload':<12} {'expr.py':>9} {'walk':>9} {'closures':>9}   (µs per evaluation, median)"
    )
    for name, source in SOURCES:
        tree = ast.parse(source, mode="eval").body
        walker, closure = Walker(tree), compile_node(tree)
        old = mod.compile_expr(source)
        assert walker.evaluate(scope) == closure(scope) == old.evaluate(old_scope), source
        a = per_call_us(partial(old.evaluate, old_scope))
        b = per_call_us(partial(walker.evaluate, scope))
        c = per_call_us(partial(closure, scope))
        print(
            f"{name:<12} {a:9.2f} {b:9.2f} {c:9.2f}   closures {a / c:4.1f}x faster than "
            f"expr.py, {b / c:4.1f}x than walk"
        )


if __name__ == "__main__":
    main()
