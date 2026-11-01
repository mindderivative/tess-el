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
The template workload is in the last section of this page (phase 6).

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
4. **Only what reads a changed input is evaluated: not yet at this point (step 3); met in step 4**
   (see "One input changes, with tracked reads" below). TEL had the same *syntactic* names as
   `expr.py` (`Expression.names`). Re-running all 20 bindings was already 5.3x cheaper.
5. **Every limit fails in under 50 ms: met**, worst 3.0 ms.

What it took, for the record: the first closure compiler was *slower to compile and bigger* than
`expr.py` (an `add` was 2.6 KB against 1.6 KB). On Python 3.14 an annotated nested function also
allocates an `__annotate__` function (630 bytes and 147 ns against 385 and 89 without), a variable a
closure captures costs a 40-byte cell where a default argument costs 8, and packing positions was
more than half of the compile time. What is left for step 8 is in the table: memory, and the compile
time of comprehensions.

## Templates (step 3, phase 6, 2026-10-28)

The one template workload, `Battery {{ battery }}% ({{ state }}), {{ count }} items`, three parts,
same harness and machine, `--portable`:

| | `expr.py` | TEL | ratio |
|---|---:|---:|---:|
| evaluate µs | 2.23 | 0.82 | **2.7x faster** |
| compile µs | 14.1 | 16.8 | 1.19x |
| bytes per compiled | 3,301 | 2,280 | 0.69 |

A template is below the 3x evaluation target (decision D1): every part is its own compiled expression
and the text is joined from pieces. It started at 2.3x and 1.49x compile; the first version parsed each
part twice, once to find where it ends and once to compile it. Further work is step 8.

## One input changes, with tracked reads (step 4, phase 5, 2026-10-31)

Criterion 4 of decision D1: *only expressions that read a changed input are evaluated, and the update
costs in proportion to those.* Measured with `evaluate_tracked` (T5) and path tracking (D13), TEL only,
`--portable`, same machine and Python (3.14.8) as above. Raw result:
`benchmarks/results/tel-2026-10-31-tracked.json`.

How it is measured: each binding is evaluated once with `evaluate_tracked`, and its `reads` recorded.
When an input changes, the host picks the bindings whose recorded reads touch it and runs them again with
`evaluate_tracked` (a host refreshes what each one read). Picking is the host's index and is not timed;
the time is the evaluations. Three ways of picking: by the **syntactic names** (`Expression.names`, what
`expr.py` offered), by the **top-level names read** (`Tracked.names`, step 4 before D13), and by the
**paths read** (`Tracked.reads`). A change at a path touches a read when one is a prefix of the other.

**Flat scope** (the 20 bindings above, over top-level names; whole update in µs):

| change | bindings run | syntactic names | names read | paths read |
|---|---:|---:|---:|---:|
| `battery` | 5 of 20 | 4.30 | 4.31 | 4.31 |
| `volume` | 3 | 3.01 | 2.97 | 3.00 |
| `width` | 2 | 2.05 | 2.04 | 2.05 |
| `count` | 2 | 1.48 | 1.49 | 1.49 |
| re-run all, plain `evaluate` | 20 | 11.22 | | |
| re-run all, `evaluate_tracked` | 20 | 21.02 | | |

**Tree scope** (the Shell's shape: `RootShell.DP1.Top_Bar.Width`, 12 bindings over plain objects):

| change | syntactic names | names read | paths read |
|---|---:|---:|---:|
| `RootShell.DP1.Top_Bar.Width` | 12 bindings, 29.14 | 12, 29.15 | **3, 7.51** |
| `RootShell.DP1.Left.Height` | 12, 29.15 | 12, 29.10 | **1, 3.04** |
| `RootShell.DP2.Scale` | 12, 29.32 | 12, 29.35 | **1, 2.99** |
| `RootShell.Theme.Gap` | 12, 29.21 | 12, 29.13 | **3, 7.75** |
| re-run all, plain `evaluate` | 12, 22.19 | | |
| re-run all, `evaluate_tracked` | 12, 28.94 | | |

What it says:

- **Criterion 4 is met.** Over top-level names the cost follows the bindings run: 5 of 20 cost 4.3 µs
  against 11.2 to re-run all (2.6x less), 2 of 20 cost 1.5 (7.6x less). Over the Shell's tree it only
  follows them with paths: 1 of 12 bindings costs 3.0 µs against 22.2 (7.3x less), 3 of 12 cost 7.5.
- **Names are not enough for a tree.** Every binding in the tree reads under `RootShell`, so by name each
  change runs all 12 and a tracked update (29 µs) costs more than re-running everything plain (22 µs).
  This is what D13 is for.
- **Reads equal the syntactic names here.** No binding skips a name for these values (the conditional
  `'low' if battery < 20 else 'ok'` reads `battery` either way). The gain from reading less shows when a
  branch is not taken (`a if flag else b` reads two of three); the tests pin that
  (`tests/test_tracking.py`), the benchmark does not exercise it.
- **Tracking costs about 1.9x on top of evaluating** (21.0 against 11.2 µs for 20 flat bindings, 28.9
  against 22.2 for 12 on the tree). A host that records reads once and re-runs plain pays nothing, but
  then its dependencies go stale when a branch flips; refreshing them is this cost. The update figures
  above are all tracked, so they include it.
- **Cost per binding:** about 0.7 to 0.9 µs flat, about 2.4 µs on the tree (three-to-four-step
  attribute chains on plain objects, about 280 ns a step; the cache that would cut it is step 8).


## cond ? a : b (step 4, #24)

Compile of the built code, median of 7 rounds, µs per expression (Python 3.14, idle machine):

| Text | `if/else` | `?:` | ratio |
|---|---:|---:|---:|
| `battery < 20 ? 'low' : 'ok'` | 9.3 | 21.4 | 2.31x |
| `a < 1 ? 'x' : a < 2 ? 'y' : 'z'` | 14.0 | 33.4 | 2.38x |
| comprehension with a `?:` filter | 24.6 | 52.4 | 2.13x |
| `f"{ok ? 'yes' : 'no'}: {battery}%"` | 13.3 | 34.7 | 2.61x |

Text with no `?:`, against the code before D14 (commit d9f98fb, same machine and harness):

| Text | before D14 | now | ratio |
|---|---:|---:|---:|
| `battery + 1` (no `?`) | 5.78 | 5.90 | 1.02x |
| `'is it ok?' + title` (`?` in a string) | 6.03 | 7.70 | 1.28x |
| `f'{battery:?>5}'` (`?` in a format spec) | 8.20 | 11.08 | 1.35x |

A text with no `?` is unchanged; a `?` that is not an operator makes the text be read once (nothing is rewritten) and costs 25 to 35%.

Evaluation is the same (0.243 µs both) and so are the bytes per compiled expression (1,408 against
1,412, over 3,000 copies). Criterion 3 (compile no slower than `expr.py`): an expression that uses `?:`
compiles about 2.3x slower than its `if/else` spelling, and against `expr.py`'s 8.4 µs for the simplest
conditional it is 2.5x; the median over the workloads does not change, since none has a `?`. The ceiling
of 3x was not exceeded. Compile time grows faster than linearly in the rewrite for very long chains
(about 0.5 s for 3,000 nested parts with the limits raised to a million); at the default limits it is about 10 ms.

## Running it

```sh
~/Projects/pyDev/pyEnvs/tess-el/bin/python benchmarks/run.py --json benchmarks/results/NAME.json
```

It takes about 90 seconds. Run it on an idle machine, with nothing else building. Add an adapter to
`ADAPTERS` in `benchmarks/run.py` to measure TEL; keep the workload names, and translate sources if
the syntax differs.
