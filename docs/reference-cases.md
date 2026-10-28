# The `expr.py` behaviour reference

Step 2 ports Tesserae UI's `tests/test_expr.py` as a behaviour reference for TEL. The tests are
`expr.py`'s, written for its API and its Python-like syntax; TEL's syntax is not decided
(brief section 9). So what is ported is **data**: tables of expressions with the outcome each must
have, in `reference/cases.py`. They run against `expr.py` now (`tests/test_reference_expr_py.py`,
skipped when the Tesserae clone is absent), and against TEL from step 3. If TEL's syntax differs, a
case is translated, never silently dropped.

Source: Tesserae `tests/test_expr.py` at commit `d31a671` (49 test functions, 652 test cases, all
passing on Python 3.14.8 on 2026-10-26).

## Ported: 374 of the 652 cases

| Table | Rows | From | What it holds |
|---|---:|---|---|
| `ALLOWED` | 100 | 100 cases | Every construct the grammar allows, with its value. |
| `DISALLOWED` | 55 | 53 cases | What is refused, with the message text. Two rows have no message; the original skips them too. |
| `ESCAPES` | 198 | 198 cases | Sandbox escapes that must fail and must never touch a `Trap` in the scope: attribute traversal, private names, unicode folding to a dunder, `eval` and friends, format-string traversal, lambda and generator tricks, statements, missing operators, resource exhaustion. |
| `LIMIT_CASES` | 20 | 20 cases | One case per limit, each with the named error. |
| `POSITIONS` | 4 | 3 tests | File, line and column of an error inside a YAML scalar (T6), including a leading-space offset and a multi-line expression. |

`reference/support.py` holds the `Plain` and `Trap` objects the cases put in the scope. The 375
tests in `tests/test_reference_expr_py.py` are these rows (the two message-less rows are not
asserted).

## Not ported yet: 278 cases, and where they go

| Left out | Cases | Why | Goes to |
|---|---:|---|---|
| The escape corpus run again as a handler | 198 | Statements are not in TEL (D10, `docs/decisions.md`). | Never. |
| Statements: assignment, augmented assignment, calls, `event`, `is_action_name`, the handler budget, the handler fuzzer | 32 | Not in TEL (D10). | Never. |
| `Signal` and `Computed` read as values, recording a dependency | 5 | Tesserae's reactive types; TEL has none (T1, T5). | Replaced by the scope protocol, step 4. |
| `is_reactive` and the syntactic `names` | 2 | `expr.py` reports the names *in the text*; T5 asks for the names an evaluation *read*. | Step 4. |
| Templates: `{{ }}`, a closing `}}` inside a string, the unclosed error, reactive templates | 4 | The delimiter is `{{ }}` (D3); how it fits the single-brace form is open. | Step 3 or 5. |
| Attribute rules: object attributes read-only, `__expose__`, mappings by attribute, a dataclass, modules, classes and functions have no attributes | 11 | What a scope may hold is the protocol's decision. | Steps 3 and 4. |
| Names and built-ins: "did you mean", the scope wins over built-ins, a loop variable cannot be called, the documented built-in list, `event` is not a name | 5 | The list includes Tesserae-flavoured helpers (`format_number`, `pluralize`, date helpers) and `event` is a Tesserae name; D4 (`docs/decisions.md`): built-ins are judged one by one. `event` is not special (D10): it is an ordinary scope name, so that case is dropped. | Step 3. |
| Sandbox claims, one test each: a container that is not a built-in is never iterated or searched (8), `isinstance` takes only basic types (5), the power cap, `%` formatting is refused on text, bad keys and indexes are expression errors, deep nesting does not overflow the stack, a slow expression fails and does not hang, a big legitimate expression fits the budget | 19 | They are the removal checks for specific rules. | Step 7, each with its removal check. |
| The fuzzers over expressions (4,000 random) and one-token mutations (1,600) | 2 | Step 7 replaces the hand-rolled generator with Hypothesis. | Step 7. |

## Deviations found by running the tables against TEL's parser (phase 3)

The same tables run against `tel._parser.parse` in `tests/test_parser.py`. What differs from
`expr.py`, and why:

| Difference | Cases | Why |
|---|---:|---|
| Four `ALLOWED` cases use `format_number` and `pluralize` and are **refused** (`call-not-function`). | 4 | Dropped from the core by decision B (`docs/language.md`, section 6). |
| `DISALLOWED` and `ESCAPES` are checked by **code**, not by message text. | 253 (55 + 198) | Messages are not API (decision D); the table in `tests/test_parser.py` pins the code of each of the 50 read-time refusals. |
| 50 of the 55 `DISALLOWED` cases are refused when the text is read; 5 need a value (`name % 3`, `sorted(items, key=len)`, `name.upper`, `x.real`, `print`). | 5 | They are well-formed. Phase 4 refuses them. |
| 165 of the 198 `ESCAPES` are refused when the text is read; 33 need a value or a size. | 33 | The 33 are listed in `tests/test_parser.py` (`EVALUATION_LEVEL_ESCAPES`) and phase 4 must refuse every one. |
| 4 of the 20 `LIMIT_CASES` are refused when the text is read (`limit-source`, `limit-depth`, `limit-nodes`, `limit-pow-exponent`); 16 are enforced while evaluating. | 16 | Phase 4. |
| `(1).bit_length()`, `name.encode()` and the other mutating or unlisted methods are refused when the text is read (7, plus `format` and `format_map` with a reason of their own). | 9 | `expr.py` refused them when evaluating; the method whitelist is known at read time. |
| `open('f')`, `eval('1')` and every call to a name that is not a built-in are refused when the text is read. | 7 | Same: the callable names are known at read time. |

## Deviations found by running the tables against TEL's evaluator (phase 4)

| Difference | Why |
|---|---|
| `min` and `max` compare several container arguments as values; `expr.py` turned every container argument into a list first, so `min('hello', '')` was `[]` there and `min(a_dict, a_text)` compared their contents instead of raising. | `expr.py` is wrong; found by the differential test (`tests/test_differential.py`, 40,000 random expressions, no other difference). |
| A built-in function's name read as a value is an error (`function-as-value`); `expr.py` returned the function. | A function is not a plain value (T9), and returning it would hand the host a callable. |
| A call to a name the scope defines is refused when the text is read; `expr.py` refused it when evaluating. | The callable names are known at read time. |
| Index and slice bounds and dict keys must be plain; `expr.py` checked only the object being indexed. | Found by the stronger `Trap`: `items[trap:]` called the object's `__index__`. |
| `isinstance` looks at `type(x)`; `expr.py` called `isinstance`, which asks the object for its `__class__`. | An object can lie about its class. |
| The error `column` is 1-based and counts characters. | Decision D; `ast` reports UTF-8 byte offsets, which `expr.py` used as columns. |

The "not ported yet" rows for names and built-ins, attribute rules and the per-rule sandbox claims are
now tests in `tests/test_evaluator.py` and `tests/test_evaluator_limits.py`, each with a removal check.
The statements, `Signal` and template rows stand as before (statements are out of TEL by D10; templates
are phase 6; the scope protocol and name tracking are step 4).

## Templates (phase 6)

The template cases of `expr.py` are tests in `tests/test_template.py`, and 34,000 random templates
(literal pieces, awkward braces and random expressions) give the same value or are both refused by
`expr.py` and TEL (`tests/test_differential.py`). Differences:

| Difference | Why |
|---|---|
| A part ends at the first `}}` after which the text reads as an expression; `expr.py` scanned for strings and brackets. | Exact by construction, including Python 3.12's same-quote nesting in f-strings. No difference was found on the random templates. |
| The error for an unclosed `{{` has the code `template-unclosed` and points at the `{{`; its column is 1-based. | Decisions D and F; the position test is translated (`expr.py` 14 is TEL 15). |
| An empty `{{ }}` is its own error (`template-empty`). | A clear message instead of Python's "invalid syntax" about nothing. |
| The parts share one step budget. | One evaluation, one budget. |
| `NestedTemplate` (a list or mapping with templates inside) is not in TEL. | Decision F: the host walks its own structure. |
| `is_reactive` for a template is not in TEL. | The scope protocol and name tracking are step 4. |
