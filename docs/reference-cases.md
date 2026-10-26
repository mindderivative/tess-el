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
| The escape corpus run again as a handler | 198 | Whether statements are part of TEL is an open syntax question (brief section 9). | Step 7, once that is decided. |
| Statements: assignment, augmented assignment, calls, `event`, `is_action_name`, the handler budget, the handler fuzzer | 32 | Same question. | Decided with the maintainer, then step 3 and 7. |
| `Signal` and `Computed` read as values, recording a dependency | 5 | Tesserae's reactive types; TEL has none (T1, T5). | Replaced by the scope protocol, step 4. |
| `is_reactive` and the syntactic `names` | 2 | `expr.py` reports the names *in the text*; T5 asks for the names an evaluation *read*. | Step 4. |
| Templates: `{{ }}`, a closing `}}` inside a string, the unclosed error, reactive templates | 4 | The delimiter is undecided. | Step 3 or 5, after the syntax decision. |
| Attribute rules: object attributes read-only, `__expose__`, mappings by attribute, a dataclass, modules, classes and functions have no attributes | 11 | What a scope may hold is the protocol's decision. | Steps 3 and 4. |
| Names and built-ins: "did you mean", the scope wins over built-ins, a loop variable cannot be called, the documented built-in list, `event` is not a name | 5 | The list includes Tesserae-flavoured helpers (`format_number`, `pluralize`, date helpers) and `event` is a Tesserae name; whether TEL keeps them is the maintainer's call. | Step 3. |
| Sandbox claims, one test each: a container that is not a built-in is never iterated or searched (8), `isinstance` takes only basic types (5), the power cap, `%` formatting is refused on text, bad keys and indexes are expression errors, deep nesting does not overflow the stack, a slow expression fails and does not hang, a big legitimate expression fits the budget | 19 | They are the removal checks for specific rules. | Step 7, each with its removal check. |
| The fuzzers over expressions (4,000 random) and one-token mutations (1,600) | 2 | Step 7 replaces the hand-rolled generator with Hypothesis. | Step 7. |
