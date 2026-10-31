# Design decisions

Decisions made by the maintainer, newest last. The reason is kept with each one.

## 2026-10-26

| # | Decision | Notes |
|---|---|---|
| D1 | **The efficiency target is adopted** as proposed in `docs/benchmarks.md`: 3x faster scalar evaluation, half the memory per compiled expression, compile no slower, evaluate only what reads a changed input, every limit fails in under 50 ms. | Measured against the `expr.py` baseline with `benchmarks/run.py`. Closes the T14 open item. |
| D2 | ~~**Statements are part of TEL**~~ *(superseded by D10)*, not only expressions: assignments and calls, as in Tesserae's handlers. | Their syntax, the set of statements, and how a scope says what is writable or callable are still to be designed (step 3 and 4). The sandbox rules apply to them as to expressions (step 7). |
| D3 | **The template delimiter is `{{ }}`**: text with expressions embedded in it; one whole part keeps the type of its value. | Open: the brief's own example, `{if condition, a, b}`, uses single braces. How a single-brace form and `{{ }}` fit together is not decided. |
| D4 | **Built-in functions are kept where they make sense and are efficient.** The Tesserae-flavoured ones (`format_number`, `pluralize`, `clamp`, the date helpers) are judged one by one in step 3: a built-in stays if it is generally useful, safe, and cheap to call. | Each kept built-in gets a test and an entry in the whitelist; each dropped one is listed with the reason. |
| D5 | ~~**`event` stays**~~ *(superseded by D10)*, but its design is open: it may be redesigned for stability, efficiency and performance. | Where an event value comes from, what it may hold, and how a handler reads it are designed in step 3 and 4. Until then the reference cases do not depend on it. |

## 2026-10-26 (later)

| # | Decision | Notes |
|---|---|---|
| D6 | **`elif` and `else` are supported** alongside `if`. | The brief reserved them in Tesserae's directives. Where they live (structure, step 5; statements, step 3) follows the syntax design. |
| D7 | **Generated names follow `<name>_0001` and increment** (`<name>_0002`, ...). | Stated by the maintainer for naming what a repeater makes. Confirmed reading: the counter names the entry; identity still comes from the key, so a counter is assigned when a key is first seen and never reused. Built in step 5. |
| D8 | **The language version starts at `0.1.0`.** A file declares only major and minor: `shell: 0.1` is enough. | TEL is an expression language, not a file format, so it has **no file key of its own**: the host format declares the version (the Shell's `shell:` key, or any other host's) and passes it to TEL's API. The patch number never changes the language. How the API takes the version (for example a `language="0.1"` argument) is designed in step 3. |
| D9 | **`import:` belongs to the Shell**, not to TEL. | Closes the open item in brief section 7. TEL does no file composition. |

## 2026-10-26 (statements and events)

| # | Decision | Notes |
|---|---|---|
| D10 | **TEL is an expression language and nothing else.** Statements, handlers and event handling are not in TEL; they belong to the consumer (the Shell). A consumer may use TEL to evaluate expressions, such as argument expressions, when an event fires. | **Supersedes D2 and D5.** `event`, if a host wants one, is an ordinary name in the scope it supplies. Raised by a message from the `shell` session; the maintainer confirmed it directly in this project. Phase 5 (#14) is dropped. |

## 2026-10-28

| # | Decision | Notes |
|---|---|---|
| D11 | **Memory criterion of D1 (at most half of `expr.py`'s) is accepted as measured in phase 4** (median 0.56, worst 0.76) and improved in step 8. | Option 1 of the phase 4 review. The other four criteria of D1 stand. |

## 2026-10-29

| # | Decision | Notes |
|---|---|---|
| D12 | **Step 4 design approved** (`docs/language.md` section 12): `evaluate_tracked(scope)` returns the value and the top-level names actually read, with plain `evaluate` unchanged (A, B); a missing name is still reported (C); host functions are pure, plain-in plain-out, registered at compile time (D); **host methods are supported too**, registered by the host per type, never found by asking the object (G), and allowed on plain types without replacing a built-in method (H); results must be plain (I); a bad registration is a `ValueError` or `TypeError` at compile (J); a failing tracked evaluation puts the names read on `TelError.reads` (K). | Extends the 2026-10-26 plan: host methods were added by the maintainer on 2026-10-29. |

## 2026-10-31

| # | Decision | Notes |
|---|---|---|
| D13 | **Path tracking is wanted:** a tracked evaluation reports the full path read (`RootShell.DP1.Top_Bar.Width`), not only the top-level name. **Changes decision B/D12** (top-level names only). **Build only on the maintainer's go-ahead.** | Asked for by the Shell (its T20): it supplies a tree of plain objects as the scope. **Design approved 2026-10-31** (`docs/language.md` 12.8, L to R as recommended): `reads` holds dotted paths in place of top-level names, `Tracked` stays `(value, reads)` with a `Tracked.names` property, a path stops at the first subscript or call, full chains only, the failing path is reported, `Expression.paths` and `Template.paths` give the paths in the text. Measured: recording a path costs about 5 ns. |
| D14 | **`cond ? a : b` as another spelling of `a if cond else b`: to be added if testing shows it is not too costly.** Not built, not yet decided as language. | The maintainer expects the cost to be small and wants it measured first: a read-time rewrite into the same tree (nothing new allowed), error columns mapped back to the original text, `:` in slices, dicts and format specs, nesting and precedence. A spike measures compile time, memory and the cost of error positions. Language version impact to be settled (0.1 or later). |

## Still open

- The language syntax outside the above (brief section 9): conditions and repeaters (the surface
  form, `else` and `elif` are decided), how a repeater names its item and key.
- The package's own versioning and release process.
