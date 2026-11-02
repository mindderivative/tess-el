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
of 3x was not exceeded. The rewrite was first quadratic in nesting (800 nested parts took 69 ms, 3,000 about 0.5 s with the limits raised to a million); the `?`, `:` and `if`/`else` of each bracket are now indexed once, and 800 take 2.3 ms and 6,000 about 7 ms, with the same compile times as above for ordinary text.

## Conditions and repeaters (step 5, #30)

`python benchmarks/structure.py` (Python 3.14.8, x86_64, median of 7 rounds, an otherwise idle
machine, 2026-11-01). `expr.py` has no structure layer, so the comparisons are with a plain TEL
expression of the same text and with a list comprehension.

| | µs |
|---|---:|
| evaluate `battery < 20` (an expression) | 0.19 |
| `Condition.holds`, same text | 0.24 |
| `select` over 3 conditions, the second wins | 0.71 |
| `compile_expression`, same text | 6.6 |
| `compile_condition`, same text | 6.8 |
| `compile_repeater` (`w in workspaces`, key `w.id`) | 11.6 |

A condition adds the `truthy` test to an evaluation (0.05 µs). Bytes per compiled object: `Condition`
673, `Expression` 633, `Repeater` 1,469 (two expressions and the header).

| items | `[w.id for w in workspaces]` | `items()` | `reconcile`, same list | one new item | reversed |
|---:|---:|---:|---:|---:|---:|
| 10 | 1.1 | 9.5 | 18.9 | 20.5 | 18.6 |
| 100 | 6.8 | 81 | 158 | 161 | 156 |
| 1,000 | 63 | 826 | 1,606 | 1,621 | 1,604 |

A repeater costs about 0.8 µs an item to read and 1.6 µs to reconcile, about 12 and 25 times a
comprehension over the same list, and linear in the list. That is a few tens of microseconds for the
lists a shell has (workspaces, tray icons) and 1.6 ms for a thousand. The time is spread over the key
evaluation in a layered scope, the `Item` and `Entry` objects (two per item in `reconcile`), the key
checks and the number formatting; `cProfile` shows no single hot spot. Speeding this up is step 8's;
nothing in the design needs the extra object, so it is the first thing to look at there.

## The Python form (step 6, #35)

`python benchmarks/structure.py` (Python 3.14.8, x86_64, median of 7 rounds, idle machine, 2026-11-02).
There is no `expr.py` counterpart, so these are costs to know, not ratios.

| | µs |
|---|---:|
| `literal([1, 2.5, 'a'])` | 1.8 |
| `fill("battery < $limit", {...})` | 2.2 |
| `fill_template`, one part | 4.0 |
| `Expression.canonical` | 4.5 |
| `compile_repeater_parts` (same pieces as `compile_repeater`: 11.9) | 11.7 |

Building text in Python costs a few microseconds, less than compiling it (6.7 µs for the same
expression), and happens once per expression, when the tree is built. `canonical` is computed when a
parity test asks. The bytes per compiled expression are unchanged (633, 1,408 and 1,945 for three
samples, against the commit before the property).

## Looking inside containers (step 7, host objects)

Built-ins that compare, add, hash or write the elements of a container (`sum`, `sorted`, `max`, `min`,
`any`, `all`, `set`, `dict`, `str`), comparisons, `in`, text and `.index` / `.count` now check the
container for host objects first (`docs/security-review.md`, step 7). Python 3.14.8, x86_64, median of
7 rounds, evaluate only, before and after:

| Expression | before µs | after µs |
|---|---:|---:|
| `sum(xs)`, 1,000 ints | 2.73 | 9.50 |
| `sorted(xs)`, 1,000 ints | 6.00 | 10.01 |
| `xs == ys`, two lists of 1,000 ints | 2.82 | 15.51 |
| `999 in xs`, 1,000 ints | 2.91 | 9.43 |
| `str(small)`, 3 ints | 0.74 | 1.03 |
| `f'{small}'`, 3 ints | 0.52 | 0.74 |
| `max(small)` | 0.81 | 1.08 |
| `sorted(small)` | 0.84 | 1.14 |
| `[w.a for w in ws]`, 50 dicts | 3.57 | 3.54 |
| `sum([w.a for w in ws])` | 4.42 | 4.99 |

The check is one pass in C over a flat list of scalars (`set(map(type, ...))`), about 7 ns an element
and 0.25 µs of fixed cost; it is only paid by the operations above and only when the operand is a list,
tuple, set or dict. Expressions that do not use them (attribute reads, arithmetic, loops, comprehensions)
are unchanged. The cost is a candidate for step 8 (a host that knows its lists are plain could say so
once; not built).

## Step 8: the target again (#8, 2026-11-02)

The same harness, workloads, machine and Python as the step 3 table (3.14.8, `--portable`, median of 7
rounds). Both implementations were run **on the same day**, one after the other: TEL at `HEAD` of
2026-11-02 (`benchmarks/results/tel-2026-11-02-portable.json`) and `expr.py` at Tesserae `7b518a1`
(`benchmarks/results/expr_py-2026-11-02-portable.json`; its adapter no longer claims a tracked
evaluation it does not have, which made the 2026-10-27 re-run crash). A first run of TEL that day had
`name` at 0.28 µs against 0.13: it was a noisy run (the same commit measured again gives 0.13, and
worktrees at the step 3, step 4 and `HEAD` commits give 117, 152 and 126 ns for `count`, so step 4
added about 35 ns and this step took 25 back). What was changed: `Expression.evaluate` makes the run
and calls the closure itself; the `names` of an expression are derived from its paths, so a second
tuple is not kept (64 bytes); a plain value in an f-string field is formatted without the generic
checks; two pieces of text are joined with one size check; the repeater makes its entries in one pass.

| workload | eval `expr.py` µs | eval TEL µs | faster | compile ratio | bytes ratio |
|---|---:|---:|---:|---:|---:|
| name | 0.59 | 0.13 | **4.4x** | 1.09 | 0.52 |
| add | 1.39 | 0.21 | **6.6x** | 1.02 | 0.35 |
| compare | 1.84 | 0.26 | **7.0x** | 1.09 | 0.50 |
| conditional | 2.01 | 0.25 | **8.1x** | 1.09 | 0.48 |
| arithmetic | 3.97 | 0.67 | **6.0x** | 1.00 | 0.75 |
| attribute | 1.05 | 0.17 | **6.3x** | 1.22 | 0.48 |
| subscript | 3.52 | 0.86 | **4.1x** | 0.98 | 0.73 |
| fstring | 2.22 | 0.56 | **3.9x** | 1.02 | 0.60 |
| call | 1.67 | 0.59 | **2.8x** | 1.22 | 0.52 |
| call-two | 4.93 | 1.42 | **3.5x** | 1.06 | 0.56 |
| comprehension-10 | 16.86 | 2.03 | **8.3x** | 1.33 | 0.57 |
| comprehension-100 | 156.28 | 14.52 | **10.8x** | 1.35 | 0.57 |
| sum-100 | 120.80 | 9.37 | **12.9x** | 1.25 | 0.49 |
| template | 2.28 | 0.81 | **2.8x** | 1.25 | 0.70 |
| long | 8.25 | 1.59 | **5.2x** | 1.08 | 0.55 |

Verdict, criterion by criterion (decision D1):

1. **Scalar evaluation at least 3x faster: met on 13 of 15; the other two are 2.8x.** Median 6.0x.
   The two below 3x are `call` (an f-string with a format spec, where Python's own `format` is most of
   the time) and the template (three parts); both are inside the 15% noise floor of 3x. Step 3 had
   `call` and `call-two` at 2.7x and 2.6x; they are 2.8x and 3.5x.
2. **At most half the memory: not met.** Median 0.55; 5 of 15 workloads at or under 0.5, the worst
   0.75 (`arithmetic`, `subscript`). A compiled expression is still its closures, about 300 bytes each.
   Getting every workload under half needs fewer closures (for example one closure for a chain of
   arithmetic on names): a change to the compiler's shapes, not attempted.
3. **Compiling no slower: median 1.09x, worst 1.35x** (the comprehensions). Not changed in this step;
   reading and checking the text is most of the time and is faster than `expr.py`'s whole compile.
4. **Only what reads a changed input is evaluated: met** (step 4, `One input changes` above).
5. **Every limit fails in under 50 ms: met** (the escape and limit tests pin a 0.5 s ceiling; the real
   figures are milliseconds).

Not a target but a cost to know: looking inside lists for host objects (step 7) adds 0.25 µs and 7 ns an
element to `sum`, `sorted`, a comparison and the like, so `sum-100` went from 8.5 to 9.4 µs.

**Repeaters** (`python benchmarks/structure.py`), per list of items, before and after this step:

| items | `items()` | `reconcile`, same list | one new item | reversed |
|---:|---:|---:|---:|---:|
| 100 | 81 → 51 µs | 158 → 106 | 161 → 106 | 156 → 102 |
| 1,000 | 826 → 516 µs | 1,606 → 1,079 | 1,621 → 1,082 | 1,604 → 1,024 |

A repeater is now about 0.5 µs an item to read and 1.1 µs to reconcile (8 and 17 times a comprehension
over the same list), and linear. Its time is spread over the key evaluation in a layered scope, the
objects it returns and the key checks; the object that is made per item (`Entry`) is the next place to
look, as a tuple subclass would halve its construction; not built.

**Left for later, with the reason.** Memory (criterion 2) and the compile time of comprehensions need
closure-count work in `_compiler.py`; a separate step with its own review is the safer way, since every
closure shape is a security rule with removal tests. The container check could be skipped for a host
that declares its lists plain; no such API is designed.

## Running it

```sh
~/Projects/pyDev/pyEnvs/tess-el/bin/python benchmarks/run.py --json benchmarks/results/NAME.json
```

It takes about 90 seconds. Run it on an idle machine, with nothing else building. Add an adapter to
`ADAPTERS` in `benchmarks/run.py` to measure TEL; keep the workload names, and translate sources if
the syntax differs.
