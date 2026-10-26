---
name: perf-baseline
description: 'Use for TEL performance work (requirement T14): recording the expr.py baseline, running the benchmarks, comparing a change against the baseline, or checking that nothing is re-run unless an input changed.'
---

# Performance baseline

T14: much more efficient than `expr.py`; the target and benchmark are set in this project. Until step 2 of the plan records a baseline there is no target, so **do not claim a speed-up without a number from both sides**.

## Measure

- `benchmarks/run.py` is the harness (stdlib `timeit` and `tracemalloc`, no dependency): `python benchmarks/run.py --json benchmarks/results/NAME.json`, about 90 s. Each implementation is an adapter in `ADAPTERS`; the workloads are in `benchmarks/workloads.py`. Use `pyperf` only if a result needs to be steadier than the harness gives (two runs differ by up to 10% in time).
- The same expression set runs against `expr.py` (`reference/expr_py.py` loads it by path with a stub `tesserae.reactive`; nothing under `src/` imports it) and TEL: parse time, first evaluation, repeated evaluation with an unchanged input, repeated evaluation after one input changed, memory per compiled expression.
- Compile once, evaluate many (T4): the repeated-evaluation numbers matter most. Name-tracking (T5) must make an unchanged input cost nothing.

## Record

The baseline is recorded in `docs/benchmarks.md` (2026-10-26, Tesserae `9f64c42`). Results go in the same page with the date, Python version, machine, commit and the exact command. The numbers are the baseline; the target is the user's decision.

## Rules

- Run on an otherwise idle machine, warm up, and say how many rounds.
- A change that speeds one case and slows another is reported with both.
- Do not tune before the baseline is recorded and the behaviour tests pass (step 3 before step 8).
- Nothing in the benchmark may be needed to import `tel`: it is a dev tool.
