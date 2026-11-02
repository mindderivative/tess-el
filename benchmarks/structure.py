#!/usr/bin/env python3
"""Measure conditions and repeaters (step 5): compile, one decision, one reconcile, memory.

    python benchmarks/structure.py [--min-time 0.15] [--repeat 7]

Dev tool: nothing under `src/` imports it. There is no `expr.py` counterpart to compare with (the
Shell has no structure layer in `expr.py`), so the figures are TEL against a plain expression of the
same text, and against itself at several list sizes. Run it on an idle machine.
"""

import argparse
import gc
import platform
import statistics
import sys
import timeit
import tracemalloc
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import tel  # noqa: E402

LANG = "0.1"


def per_call_us(fn: Callable[[], object], min_time: float, repeat: int) -> float:
    number = 1
    while timeit.timeit(fn, number=number) < min_time:
        number *= 2
    return statistics.median(timeit.repeat(fn, number=number, repeat=repeat)) / number * 1e6


def bytes_per(make: Callable[[], object], copies: int = 3000) -> float:
    make()
    gc.collect()
    tracemalloc.start()
    keep = [make() for _ in range(copies)]
    size = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()
    del keep
    return size / copies


def workspaces(count: int) -> list[dict[str, object]]:
    return [{"id": i, "name": f"w{i}", "windows": i % 7} for i in range(count)]


def size_row(
    repeater: tel.Repeater, comprehension: tel.Expression, size: int, mt: float, rp: int
) -> str:
    data = workspaces(size)
    here = tel.MapScope({"workspaces": data})
    grown = tel.MapScope({"workspaces": [*data, {"id": size, "name": "n", "windows": 0}]})
    flipped = tel.MapScope({"workspaces": data[::-1]})
    state = repeater.reconcile(here, tel.RepeaterState()).state
    cells = (
        per_call_us(lambda: comprehension.evaluate(here), mt, rp),
        per_call_us(lambda: repeater.items(here), mt, rp),
        per_call_us(lambda: repeater.reconcile(here, state), mt, rp),
        per_call_us(lambda: repeater.reconcile(grown, state), mt, rp),
        per_call_us(lambda: repeater.reconcile(flipped, state), mt, rp),
    )
    return f"{size:>6} " + " ".join(f"{cell:>14.1f}" for cell in cells)


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-time", type=float, default=0.15)
    parser.add_argument("--repeat", type=int, default=7)
    args = parser.parse_args(argv)
    mt, rp = args.min_time, args.repeat
    print(f"Python {platform.python_version()} on {platform.machine()}; median of {rp} rounds\n")

    scope = tel.MapScope({"battery": 42, "n": 3})
    text = "battery < 20"
    expression = tel.compile_expression(text, language=LANG)
    condition = tel.compile_condition(text, language=LANG)
    chain = [tel.compile_condition(t, language=LANG) for t in (text, "battery < 60", "n")]

    def compile_repeater() -> tel.Repeater:
        return tel.compile_repeater("w in workspaces", key="w.id", name="W", language=LANG)

    rows = [
        ("evaluate `battery < 20` (an expression)", lambda: expression.evaluate(scope)),
        ("Condition.holds, same text", lambda: condition.holds(scope)),
        ("select over 3 conditions, 2nd wins", lambda: tel.select(chain, scope)),
        ("compile_expression, same text", lambda: tel.compile_expression(text, language=LANG)),
        ("compile_condition, same text", lambda: tel.compile_condition(text, language=LANG)),
        ("compile_repeater `w in workspaces`, key `w.id`", compile_repeater),
        (
            "compile_repeater_parts, same pieces",
            lambda: tel.compile_repeater_parts(
                "w", "workspaces", key="w.id", name="W", language=LANG
            ),
        ),
        ("literal([1, 2.5, 'a'])", lambda: tel.literal([1, 2.5, "a"])),
        ("fill `battery < $limit`", lambda: tel.fill("battery < $limit", {"limit": 20})),
        (
            "fill_template, one part",
            lambda: tel.fill_template("Hi {{ $who }}, {{ n }} new", {"who": "Ada"}),
        ),
        ("Expression.canonical", lambda: expression.canonical),
    ]
    for label, call in rows:
        print(f"{label:<52} {per_call_us(call, mt, rp):>10.2f} us")
    print()
    for label, make in (
        ("Condition", lambda: tel.compile_condition(text, language=LANG)),
        ("Expression", lambda: tel.compile_expression(text, language=LANG)),
        ("Repeater", compile_repeater),
    ):
        print(f"bytes per compiled {label:<12} {bytes_per(make):>8.0f}")
    print()

    repeater = compile_repeater()
    comprehension = tel.compile_expression("[w.id for w in workspaces]", language=LANG)
    heads = ("items", "comprehension", "items()", "reconcile same", "+1 new", "reversed")
    print(f"{heads[0]:>6} " + " ".join(f"{h:>14}" for h in heads[1:]) + "   (microseconds)")
    for size in (10, 100, 1000):
        print(size_row(repeater, comprehension, size, mt, rp))


if __name__ == "__main__":
    main(sys.argv[1:])
