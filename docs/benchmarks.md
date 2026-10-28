# Benchmarks

The efficiency requirement is T14: *much more efficient than `expr.py`: parse once, cheap
re-evaluation, nothing re-run unless an input changed*. This page records the **baseline**, which is
Tesserae UI's `expr.py` measured by `benchmarks/run.py`. The target was adopted on 2026-10-26 (see [Target](#target-adopted-2026-10-26)).

## What was measured

| | |
|---|---|
| Date | 2026-10-26 |
| Python | CPython 3.14.8 |
| Machine | AMD Ryzen AI 9 HX 370 w/ Radeon 890M, Linux 7.3.0-5-cachyos (performance governor) |
| `expr.py` | Tesserae commit `9f64c42` (`expr.py` and `tests/test_expr.py` are identical to commit `d31a671`, where the cases were ported) |
| Harness | tess-el commit `3c0aead` |
| Command | `python benchmarks/run.py --json benchmarks/results/expr_py-2026-10-26-run1.json` |
| Rounds | 7 rounds of at least 0.2 s per measurement; the table shows the median |
| Load average at start | 1.57, 1.18, 0.76 (the run itself uses one core) |
| Raw results | `benchmarks/results/expr_py-2026-10-26-run1.json` (this table) and `run2.json` (a second run) |

`expr.py` is loaded by path with a stub for `tesserae.reactive` (`reference/expr_py.py`), so plain
values are measured: no `Signal` unwrapping is involved. The workloads are in
`benchmarks/workloads.py`: 14 expressions and one template, of the kind a shell or a UI writes.

**Repeatability.** Two runs back to back differ by up to 10% in time, 0.4% in bytes per compiled
expression, and up to 40% in peak bytes while evaluating the 100-item comprehension (the peak counts
transient garbage). Treat a time difference under 15% as noise, and the peak column as approximate.

## Results (`expr.py`)

| workload | compile µs | evaluate µs | bytes / compiled | peak bytes (eval) |
|---|---:|---:|---:|---:|
| name | 3.66 | 0.59 | 970 | 682 |
| add | 5.71 | 1.39 | 1,619 | 875 |
| compare | 8.94 | 1.85 | 2,790 | 1,393 |
| conditional | 8.44 | 2.02 | 2,812 | 1,208 |
| arithmetic | 12.17 | 4.01 | 3,581 | 1,654 |
| attribute | 4.33 | 1.06 | 1,290 | 817 |
| subscript | 10.85 | 3.55 | 3,250 | 1,112 |
| fstring | 9.85 | 2.21 | 2,973 | 1,144 |
| call | 7.16 | 2.55 | 2,073 | 1,398 |
| call-two | 13.12 | 5.10 | 4,243 | 1,843 |
| comprehension-10 | 9.13 | 16.71 | 3,315 | 3,015 |
| comprehension-100 | 9.16 | 150.56 | 3,314 | 4,717 |
| sum-100 | 10.33 | 123.19 | 3,426 | 4,614 |
| template | 14.01 | 2.22 | 3,301 | 993 |
| long | 26.04 | 8.49 | 8,685 | 2,765 |

One input changes (20 bindings; median µs for the whole update):

| strategy | bindings run | µs |
|---|---:|---:|
| re-run all | 20 | 59.47 |
| only those that read `battery` | 5 | 10.06 |
| only those that read `volume` | 3 | 7.51 |
| only those that read `width` | 2 | 6.29 |
| only those that read `count` | 2 | 4.38 |

Time to refuse (ms, best of 3):

| source | ms | outcome |
|---|---:|---|
| `[x for x in range(100000)]` | 36.39 | ExprError |
| `list(range(100000)) + list(range(100000)) + list(range(10000` | 2.60 | ExprError |
| `[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1` | 0.82 | ExprError |
| `sum([[1]] * 500000, [])` | 0.21 | ExprError |
| `[x for x in range(10) for y in range(10) for z in range(10)]` | 0.17 | ExprError |
| `[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[]]]]]]]]]]]]]]]` | 0.08 | ExprError |
| `9 ** 64 * 9 ** 64 * 9 ** 64 * 9 ** 64 * 9 ** 64 * 9 ** 64 * ` | 0.07 | ExprError |
| `'-'.join(['x' * 500000, 'y' * 600000])` | 0.06 | ExprError |
| `f'{"a" * 600000}{"b" * 600000}'` | 0.03 | ExprError |
| `'a' * 600000 + 'b' * 600000` | 0.03 | ExprError |
| `[i for i in range(10**6)]` | 0.02 | ExprError |
| `sum(range(10**7))` | 0.02 | ExprError |
| `list(range(10**7))` | 0.02 | ExprError |
| `range(10**9)` | 0.02 | ExprError |
| `'x'.zfill(10**9)` | 0.02 | ExprError |
| `[0] * 10**9` | 0.02 | ExprError |
| `range(10**12)` | 0.02 | ExprError |
| `'x'.zfill(10**7)` | 0.02 | ExprError |
| `'x'.ljust(10**9)` | 0.02 | ExprError |
| `'x'.center(10**9)` | 0.01 | ExprError |
| `'a' * 10**9` | 0.01 | ExprError |
| `[0] * 2_000_000` | 0.01 | ExprError |
| `10 ** 10 ** 10` | 0.01 | ExprError |
| `range(100001)` | 0.01 | ExprError |
| `10 ** 64 ** 2` | 0.01 | ExprError |
| `3 * 'ab' * 400000` | 0.01 | ExprError |
| `'x'.center(2000000)` | 0.01 | ExprError |
| `9 ** 9 ** 9` | 0.01 | ExprError |
| `'a' * 1000001` | 0.01 | ExprError |
| `2 ** 65` | 0.01 | ExprError |
| `'x' * 2000` | 0.00 | ExprError |

Module import (stubbed `tesserae.reactive`): median 16.0 ms, min 15.0 ms.

## What the numbers say

- **Cost of parsing.** Compiling takes 4 to 26 µs, 5 to 8 times one evaluation of a scalar
  expression. Compile once, evaluate many (T4) matters, but a compiled expression keeps
  1 to 9 KB alive (about 1 KB for a bare name, 3 KB for a typical condition), probably its syntax
  tree. A shell with a few hundred bindings holds about a megabyte.
- **Cost of evaluating.** A scalar expression takes 0.6 to 8 µs. A comprehension over 100 items
  takes about 150 µs, 1.5 µs per item, so the evaluator's per-node cost is the thing to cut.
- **"Nothing re-run unless an input changed" (T14).** `expr.py` never skips an evaluation. It offers
  `Expr.names`, the *syntactic* free names, and the caller filters. Re-running all 20 bindings costs
  about 59 µs; running only those that read the changed input costs 4 to 10 µs. TEL has to do that
  filtering itself, and by the names an evaluation actually *read* (T5), not the names in the text.
- **Time to refuse.** Every limit and every resource-exhaustion escape fails with `ExprError`. The
  slowest is `[x for x in range(100000)]` at about 36 ms, because the step budget (200,000) lets it run
  that long first; everything else fails in under 3 ms. Nothing hangs.
- **Import.** Loading the module takes about 16 to 18 ms (stub included), mostly `ast`, `decimal`,
  `difflib` and `re`.

## Target (adopted 2026-10-26)

Accepted by the maintainer as proposed. TEL is measured with the same harness and the same workloads
(an adapter in `benchmarks/run.py`), on the same machine and Python. "Faster" and "half" are against
the baseline above, and a difference under 15% is noise.

1. Evaluating a scalar expression is at least 3 times faster than `expr.py`.
2. A compiled expression keeps at most half the memory.
3. Compiling is no slower than `expr.py` (it happens once).
4. When one input changes, only expressions that read it are evaluated, and the update costs in
   proportion to those, not to all bindings.
5. Every limit still fails in under 50 ms.

## TEL against the target (step 3, phase 4, 2026-10-27)

First numbers for TEL's evaluator, against `expr.py`, by the same harness on the same machine and
Python (3.14.8), one run after the other. `--portable` replaces the two helpers TEL dropped
(`format_number`, `pluralize`) by what replaces them in the sources of **both** implementations, so the
`call` and `call-two` rows differ from the baseline table above. Commit `59ffa07`;
`expr.py` at Tesserae `7b518a1` (unchanged since `d31a671`). Raw results:
`benchmarks/results/expr_py-2026-10-27-portable.json` and `tel-2026-10-27-portable.json`.
The template workload is not measured for TEL until phase 6.

| workload | eval `expr.py` µs | eval TEL µs | faster | compile `expr.py` µs | compile TEL µs | ratio | bytes `expr.py` | bytes TEL | ratio |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| name | 0.58 | 0.13 | **4.5x** | 3.7 | 3.8 | 1.04x | 968 | 496 | 0.51 |
| add | 1.39 | 0.21 | **6.7x** | 5.6 | 5.5 | 0.99x | 1,615 | 565 | 0.35 |
| compare | 1.90 | 0.27 | **7.0x** | 9.3 | 9.4 | 1.01x | 2,767 | 1,372 | 0.50 |
| conditional | 2.08 | 0.25 | **8.5x** | 8.4 | 9.0 | 1.07x | 2,812 | 1,342 | 0.48 |
| arithmetic | 4.00 | 0.67 | **5.9x** | 12.1 | 11.9 | 0.98x | 3,583 | 2,707 | 0.76 |
| attribute | 1.06 | 0.17 | **6.2x** | 4.3 | 4.8 | 1.10x | 1,279 | 780 | 0.61 |
| subscript | 3.62 | 0.83 | **4.4x** | 11.0 | 10.6 | 0.96x | 3,255 | 2,375 | 0.73 |
| fstring | 2.25 | 0.65 | **3.5x** | 9.9 | 9.9 | 0.99x | 2,976 | 1,766 | 0.59 |
| call | 1.73 | 0.65 | **2.7x** | 8.0 | 9.5 | 1.19x | 2,273 | 1,168 | 0.51 |
| call-two | 5.01 | 1.84 | **2.7x** | 15.0 | 15.8 | 1.05x | 4,935 | 2,796 | 0.57 |
| comprehension-10 | 18.02 | 1.99 | **9.0x** | 9.2 | 11.7 | 1.26x | 3,316 | 1,879 | 0.57 |
| comprehension-100 | 158.38 | 14.57 | **10.9x** | 9.2 | 11.8 | 1.29x | 3,315 | 1,879 | 0.57 |
| sum-100 | 132.38 | 8.53 | **15.5x** | 10.3 | 12.3 | 1.20x | 3,430 | 1,664 | 0.49 |
| long | 8.58 | 1.62 | **5.3x** | 25.9 | 27.0 | 1.04x | 8,681 | 4,808 | 0.55 |

One input changes (20 bindings, whole update, µs): re-running all costs 57.4 for `expr.py` and 10.9 for TEL.

| strategy | bindings run | `expr.py` µs | TEL µs |
|---|---:|---:|---:|
| only those that read `battery` | 5 | 10.1 | 2.2 |
| only those that read `volume` | 3 | 7.5 | 2.0 |
| only those that read `width` | 2 | 5.9 | 1.5 |
| only those that read `count` | 2 | 4.0 | 1.0 |

Slowest refusal of a limit: 36.7 ms for `expr.py`, 3.0 ms for TEL.
Module import: 16.0 ms for `expr.py` (with its stub), 14.6 ms for TEL.

### Verdict on each criterion (decision D1)

1. **Scalar evaluation at least 3x faster: met on 12 of 14 workloads.** Median 6.1x, minimum
   2.7x. The two below 3x are `call` (an f-string with a format spec, where Python's own `format`
   is most of the time) and `call-two` (a conditional, a method call and two concatenations), both 2.7x.
   The 100-item comprehension is 10.9x.
2. **At most half the memory: not met.** Median 0.56, worst 0.76; five of 14 workloads are
   at or under 0.51. A compiled expression is closures, about 300 bytes each (a 168-byte function object,
   its default-arguments tuple of about 100, and a 40-byte position), plus about 200 bytes that every
   expression has (the object, the text, the limits and error-site record). Getting under half
   everywhere needs fewer closures, not tuning.
3. **Compiling no slower: median 1.05x, worst 1.29x.** Within the 15% noise floor for 10 of 14; the
   comprehensions are 1.20 to 1.29x and `call` is 1.19x. Reading and checking the text is 70 to 85% of
   the time and on its own is faster than `expr.py`'s whole compile; the closures are the rest.
4. **Only what reads a changed input is evaluated: not yet.** TEL has the same *syntactic* names as
   `expr.py` (`Expression.names`). The names an evaluation actually *read* (T5) are step 4. Re-running
   all 20 bindings is already 5.3x cheaper.
5. **Every limit fails in under 50 ms: met**, worst 3.0 ms.

What it took, for the record: the first closure compiler was *slower to compile and bigger* than
`expr.py` (an `add` was 2.6 KB against 1.6 KB). On Python 3.14 an annotated nested function also
allocates an `__annotate__` function (630 bytes and 147 ns against 385 and 89 without), a variable a
closure captures costs a 40-byte cell where a default argument costs 8, and packing positions was
more than half of the compile time. What is left for step 8 is in the table: memory, and the compile
time of comprehensions.

## Running it

```sh
~/Projects/pyDev/pyEnvs/tess-el/bin/python benchmarks/run.py --json benchmarks/results/NAME.json
```

It takes about 90 seconds. Run it on an idle machine, with nothing else building. Add an adapter to
`ADAPTERS` in `benchmarks/run.py` to measure TEL; keep the workload names, and translate sources if
the syntax differs.
