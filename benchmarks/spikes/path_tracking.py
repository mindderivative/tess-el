#!/usr/bin/env python3
"""Spike for D13: what does it cost to record the path of an attribute chain?

Today `RootShell.DP1.Top_Bar.Width` compiles to four nested closures (name, then one per attribute).
Path tracking needs the chain as a unit, so this compares, on the same object tree:

* current: TEL as it is (plain `evaluate`, and `evaluate_tracked`, which records the root name only)
* fused:   one closure per chain that walks the attributes, with `R.paths` unset (plain evaluation)
* tracked: the same closure with `R.paths` set, recording the whole path

The fused closures use TEL's own `read_attribute`: the same work as the real ones, happy path.
Not TEL code: the numbers say whether the design in docs/language.md 12.8 is affordable.

    python benchmarks/spikes/path_tracking.py
"""

import statistics
import sys
import timeit
from functools import partial
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import tel  # noqa: E402
from tel._compiler import Site, read_attribute  # noqa: E402
from tel.limits import DEFAULT_LIMITS  # noqa: E402


class Node:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


class Run:
    paths: set[str] | None = None


def per_ns(fn: Any) -> int:
    timer = timeit.Timer(fn)
    timer.timeit(200)
    number = 1
    while timer.timeit(number) < 0.2:
        number *= 2
    return round(statistics.median(t / number * 1e9 for t in timer.repeat(repeat=9, number=number)))


def fused(root: str, attrs: tuple[str, ...], S: Site) -> Any:
    path = ".".join((root, *attrs))

    def chain(L, R, root=root, attrs=attrs, path=path, S=S):  # type: ignore[no-untyped-def]
        if R.paths is None:
            value = L(root)
        else:
            value = R.raw(root)
            R.paths.add(path)
        for name in attrs:
            if type(value) is dict:
                try:
                    value = value[name]
                    continue
                except KeyError:
                    pass
            value = read_attribute(S, 0, value, name)
        return value

    return chain


def main() -> None:
    tree = Node(DP1=Node(Top_Bar=Node(Width=300, Height=30, Inner=Node(Deep=Node(Leaf=7)))))
    scope = tel.MapScope({"RootShell": tree, "ws": Node(name="n")})
    S = Site("x", None, DEFAULT_LIMITS)
    print(
        f"{'expression':<42} {'plain now':>10} {'tracked now':>12} {'fused':>7} {'fused+path':>11}"
    )
    for text, root, attrs in (
        ("ws.name", "ws", ("name",)),
        ("RootShell.DP1.Top_Bar.Width", "RootShell", ("DP1", "Top_Bar", "Width")),
        (
            "RootShell.DP1.Top_Bar.Inner.Deep.Leaf",
            "RootShell",
            ("DP1", "Top_Bar", "Inner", "Deep", "Leaf"),
        ),
    ):
        expr = tel.compile_expression(text, language="0.1")
        chain = fused(root, attrs, S)
        plain_run, tracked_run = Run(), Run()
        tracked_run.paths = set()
        tracked_run.raw = scope.lookup  # type: ignore[attr-defined]
        assert chain(scope.lookup, plain_run) == expr.evaluate(scope)
        t = (
            per_ns(partial(expr.evaluate, scope)),
            per_ns(partial(expr.evaluate_tracked, scope)),
            per_ns(partial(chain, scope.lookup, plain_run)),
            per_ns(partial(chain, scope.lookup, tracked_run)),
        )
        print(f"{text:<42} {t[0]:>8} ns {t[1]:>9} ns {t[2]:>4} ns {t[3]:>8} ns")
    print(
        "\n`fused` and `fused+path` leave out a whole evaluation (the Run object and the result):"
    )
    print("compare them with each other, and with `plain now` minus about 100 ns.")


if __name__ == "__main__":
    main()
