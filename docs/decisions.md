# Design decisions

Decisions made by the maintainer, newest last. The reason is kept with each one.

## 2026-10-26

| # | Decision | Notes |
|---|---|---|
| D1 | **The efficiency target is adopted** as proposed in `docs/benchmarks.md`: 3x faster scalar evaluation, half the memory per compiled expression, compile no slower, evaluate only what reads a changed input, every limit fails in under 50 ms. | Measured against the `expr.py` baseline with `benchmarks/run.py`. Closes the T14 open item. |
| D2 | **Statements are part of TEL**, not only expressions: assignments and calls, as in Tesserae's handlers. | Their syntax, the set of statements, and how a scope says what is writable or callable are still to be designed (step 3 and 4). The sandbox rules apply to them as to expressions (step 7). |
| D3 | **The template delimiter is `{{ }}`**: text with expressions embedded in it; one whole part keeps the type of its value. | Open: the brief's own example, `{if condition, a, b}`, uses single braces. How a single-brace form and `{{ }}` fit together is not decided. |
| D4 | **Built-in functions are kept where they make sense and are efficient.** The Tesserae-flavoured ones (`format_number`, `pluralize`, `clamp`, the date helpers) are judged one by one in step 3: a built-in stays if it is generally useful, safe, and cheap to call. | Each kept built-in gets a test and an entry in the whitelist; each dropped one is listed with the reason. |
| D5 | **`event` stays**, but its design is open: it may be redesigned for stability, efficiency and performance. | Where an event value comes from, what it may hold, and how a handler reads it are designed in step 3 and 4. Until then the reference cases do not depend on it. |

## Still open

- The language syntax outside the above (brief section 9): conditions and repeaters (`if`, `else`,
  `elif`), how a repeater names its item and key, how a file declares its TEL version.
- Whether `import:` is TEL's or the Shell's.
- The package's own versioning and release process.
