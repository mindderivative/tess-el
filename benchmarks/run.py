#!/usr/bin/env python3
"""Measure an expression implementation: parse time, evaluation time, memory, time to refuse.

    python benchmarks/run.py [--impl expr_py] [--min-time 0.2] [--repeat 7] [--json PATH]

Dev tool: nothing under `src/` imports it. The implementation is an adapter with `compile(kind,
source)` and `evaluate(compiled, values)`; `expr_py` (Tesserae UI's `expr.py`, read by path) is the
baseline for requirement T14, and TEL gets an adapter when it exists. Run it on an idle machine; the
numbers are only comparable with the same Python, machine and workloads (see docs/benchmarks.md).
"""

import argparse
import gc
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import timeit
import tracemalloc
from collections.abc import Callable
from datetime import date
from functools import partial
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmarks.workloads import BINDINGS, SCOPE, WORKLOADS, portable  # noqa: E402
from reference import cases, expr_py  # noqa: E402

PORTABLE_MODE = False  # set by --portable


class ExprPyAdapter:
    """Tesserae UI's `expr.py`, loaded by path (see reference/expr_py.py)."""

    name = "expr_py"
    kinds = frozenset({"expr", "template"})
    import_code = "from reference import expr_py; expr_py.load()"

    def __init__(self) -> None:
        self.mod = expr_py.load()

    def compile(self, kind: str, source: str) -> Any:
        if kind == "template":
            return self.mod.compile_template(source)
        return self.mod.compile_expr(source)

    def scope(self, values: dict[str, Any]) -> Any:
        return self.mod.MapScope(values)

    def evaluate(self, compiled: Any, scope: Any) -> Any:
        return compiled.evaluate(scope)

    def names(self, compiled: Any) -> set[str]:
        return set(compiled.names)

    def refuse(self, source: str, limits: dict[str, int]) -> str:
        """Compile and evaluate a source that must fail; return the error class name."""
        scope = self.mod.MapScope()
        try:
            self.mod.compile_expr(source, limits=self.mod.Limits(**limits)).evaluate(scope)
        except self.mod.ExprError:
            return "ExprError"
        return "NOT REFUSED"


class TelAdapter:
    """TEL itself (`src/tel`)."""

    name = "tel"
    kinds = frozenset({"expr"})  # templates are phase 6
    import_code = "import tel"

    def __init__(self) -> None:
        import tel

        self.tel = tel

    def compile(self, kind: str, source: str) -> Any:
        return self.tel.compile_expression(source, language=self.tel.LANGUAGE)

    def scope(self, values: dict[str, Any]) -> Any:
        return self.tel.MapScope(values)

    def evaluate(self, compiled: Any, scope: Any) -> Any:
        return compiled.evaluate(scope)

    def names(self, compiled: Any) -> set[str]:
        return set(compiled.names)

    def refuse(self, source: str, limits: dict[str, int]) -> str:
        """Compile and evaluate a source that must fail; return the error class name."""
        try:
            self.tel.compile_expression(
                source, language=self.tel.LANGUAGE, limits=self.tel.Limits(**limits)
            ).evaluate(self.tel.MapScope())
        except self.tel.TelError:
            return "TelError"
        return "NOT REFUSED"


ADAPTERS: dict[str, Callable[[], Any]] = {"expr_py": ExprPyAdapter, "tel": TelAdapter}


def per_call_ns(fn: Callable[[], object], min_time: float, repeat: int) -> dict[str, float]:
    """Nanoseconds per call: the minimum and median over `repeat` rounds of at least `min_time`."""
    timer = timeit.Timer(fn)
    timer.timeit(10)  # warm up
    number = 1
    while timer.timeit(number) < min_time:  # calls per round, found by doubling
        number *= 2
    rounds = [t / number * 1e9 for t in timer.repeat(repeat=repeat, number=number)]
    return {
        "min_ns": min(rounds),
        "median_ns": statistics.median(rounds),
        "number": number,
        "repeat": repeat,
    }


def bytes_per_compiled(impl: Any, kind: str, source: str, copies: int = 300) -> float:
    """Heap bytes kept alive per compiled expression (many copies, so the average is steady)."""
    impl.compile(kind, source)  # first-call caches are not the expression's
    gc.collect()
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    kept = [impl.compile(kind, source) for _ in range(copies)]
    after = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()
    del kept
    return (after - before) / copies


def peak_bytes_evaluating(impl: Any, compiled: Any, scope: Any) -> int:
    """Peak extra heap bytes during one evaluation."""
    impl.evaluate(compiled, scope)
    gc.collect()
    tracemalloc.start()
    base = tracemalloc.get_traced_memory()[0]
    tracemalloc.reset_peak()
    impl.evaluate(compiled, scope)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return peak - base


def measure_workloads(impl: Any, min_time: float, repeat: int) -> list[dict[str, Any]]:
    rows = []
    for name, kind, source, values in WORKLOADS:
        if kind not in impl.kinds:
            continue
        source = portable(source) if PORTABLE_MODE else source
        scope = impl.scope(values)
        compiled = impl.compile(kind, source)
        do_compile = partial(impl.compile, kind, source)
        do_evaluate = partial(impl.evaluate, compiled, scope)
        rows.append(
            {
                "name": name,
                "source": source,
                "compile": per_call_ns(do_compile, min_time, repeat),
                "evaluate": per_call_ns(do_evaluate, min_time, repeat),
                "bytes_per_compiled": bytes_per_compiled(impl, kind, source),
                "peak_bytes_evaluating": peak_bytes_evaluating(impl, compiled, scope),
            }
        )
    return rows


def measure_update(impl: Any, min_time: float, repeat: int) -> dict[str, Any]:
    """One input changes: re-run every binding, or only the ones that read it (by `names`)."""
    compiled = [impl.compile("expr", portable(s) if PORTABLE_MODE else s) for s in BINDINGS]
    scope = impl.scope(SCOPE)
    names = [impl.names(c) for c in compiled]
    out: dict[str, Any] = {"bindings": len(BINDINGS), "per_input": {}}

    def rerun_all() -> None:
        for c in compiled:
            impl.evaluate(c, scope)

    out["rerun_all"] = per_call_ns(rerun_all, min_time, repeat)
    for changed in ("battery", "volume", "width", "count"):
        hit = [c for c, n in zip(compiled, names, strict=True) if changed in n]

        def rerun_affected(hit: list[Any] = hit, changed: str = changed) -> None:
            for c, n in zip(compiled, names, strict=True):
                if changed in n:
                    impl.evaluate(c, scope)

        out["per_input"][changed] = {
            "affected": len(hit),
            "time": per_call_ns(rerun_affected, min_time, repeat),
        }
    return out


def measure_refusals(impl: Any) -> list[dict[str, Any]]:
    """Time to fail for each limit case and each resource-exhaustion escape: must be prompt."""
    cases_to_run = [(s, lim) for s, _, lim in cases.LIMIT_CASES]
    cases_to_run += [(s, {}) for s in cases.ESCAPES if "10**" in s or "10 **" in s or "9 **" in s]
    rows = []
    for source, limits in cases_to_run:
        best = float("inf")
        outcome = ""
        for _ in range(3):
            start = time.perf_counter()
            outcome = impl.refuse(source, limits)
            best = min(best, time.perf_counter() - start)
        rows.append({"source": source[:60], "ms": best * 1e3, "outcome": outcome})
    return rows


def measure_import(impl: Any, repeat: int = 7) -> dict[str, float]:
    code = (
        "import sys, time; root = sys.argv[1]; sys.path[:0] = [root, root + '/src'];"
        f"t = time.perf_counter(); {impl.import_code}; print(time.perf_counter() - t)"
    )
    times = [
        float(
            subprocess.run(
                [sys.executable, "-c", code, str(ROOT)], capture_output=True, text=True, check=True
            ).stdout
        )
        for _ in range(repeat)
    ]
    return {"median_ms": statistics.median(times) * 1e3, "min_ms": min(times) * 1e3}


def git(*args: str, cwd: Path = ROOT) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return done.stdout.strip()


def cpu_model() -> str:
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return platform.processor()


def metadata(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "date": date.today().isoformat(),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "machine": f"{cpu_model()}, {platform.system()} {platform.release()}",
        "tess_el_commit": git("rev-parse", "--short", "HEAD")
        + ("+dirty" if git("status", "--short", "--", ".", ":!benchmarks/results") else ""),
        "tesserae_commit": expr_py.clone_commit(),
        "command": "python benchmarks/run.py " + " ".join(sys.argv[1:]),
        "portable": PORTABLE_MODE,
        "min_time_s": args.min_time,
        "repeat": args.repeat,
        "load_average": list(os.getloadavg()),
    }


def us(ns: float) -> str:
    return f"{ns / 1e3:,.2f}" if ns < 1e6 else f"{ns / 1e3:,.0f}"


def report(result: dict[str, Any]) -> str:
    lines = [f"## {result['impl']}", ""]
    lines += [
        "| workload | compile µs | evaluate µs | bytes / compiled | peak bytes (eval) |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in result["workloads"]:
        lines.append(
            f"| {r['name']} | {us(r['compile']['median_ns'])} | {us(r['evaluate']['median_ns'])} "
            f"| {r['bytes_per_compiled']:,.0f} | {r['peak_bytes_evaluating']:,} |"
        )
    u = result["update"]
    lines += [
        "",
        f"One input changes ({u['bindings']} bindings; median µs for the whole update):",
        "",
    ]
    lines += ["| strategy | bindings run | µs |", "|---|---:|---:|"]
    lines.append(f"| re-run all | {u['bindings']} | {us(u['rerun_all']['median_ns'])} |")
    for name, v in u["per_input"].items():
        lines.append(
            f"| only those that read `{name}` | {v['affected']} | {us(v['time']['median_ns'])} |"
        )
    lines += [
        "",
        "Time to refuse (ms, best of 3):",
        "",
        "| source | ms | outcome |",
        "|---|---:|---|",
    ]
    for r in sorted(result["refusals"], key=lambda r: -r["ms"]):
        lines.append(f"| `{r['source']}` | {r['ms']:.2f} | {r['outcome']} |")
    imp = result["import"]
    lines += [
        "",
        f"Module import: median {imp['median_ms']:.1f} ms, min {imp['min_ms']:.1f} ms.",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--impl", default="expr_py", choices=sorted(ADAPTERS))
    parser.add_argument("--min-time", type=float, default=0.2, help="seconds per timing round")
    parser.add_argument("--repeat", type=int, default=7, help="timing rounds per measurement")
    parser.add_argument("--json", type=Path, help="write the raw result here")
    parser.add_argument(
        "--portable",
        action="store_true",
        help="replace the helpers TEL dropped (format_number, pluralize) in the sources",
    )
    args = parser.parse_args()
    if not expr_py.available():
        sys.exit(f"{expr_py.PATH} not found; set TESSERAE_SRC")
    global PORTABLE_MODE
    PORTABLE_MODE = args.portable
    impl = ADAPTERS[args.impl]()
    result = {
        "meta": metadata(args),
        "impl": impl.name,
        "workloads": measure_workloads(impl, args.min_time, args.repeat),
        "update": measure_update(impl, args.min_time, args.repeat),
        "refusals": measure_refusals(impl),
        "import": measure_import(impl),
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2) + "\n")
    print(report(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
