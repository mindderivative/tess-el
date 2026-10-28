# Security review of the language (step 3)

The outcome of applying the `sandbox-escape-review` and `sharp-edges` skills to what step 3 built:
the parser, the evaluator, templates and the public API. It says what is guaranteed, how that is
checked and how to check it again, what was found on the way, and what is **not** guaranteed.
Step 7 adds a Hypothesis fuzzer and a wider corpus on top of this.

## What is protected, and from whom

TEL evaluates text written by someone who is not necessarily the host: a YAML file a user edits, a
theme someone shares. The host (the Shell) is trusted; the values it puts in a scope are the host's.

| TEL guarantees | for any expression text, with the default or any positive `Limits` |
|---|---|
| No file, process, network or system access, and no `eval` of the text | the text is parsed with `ast`, every node is checked against a whitelist, and what runs is closures built from the checked tree |
| No attribute escape | a name or attribute starting with `_` is refused, and so is any attribute of a module, class, function, frame or similar; Python folds wide characters (NFKC) before the check, so `_＿class＿＿` is `__class__` |
| It stops | text length, tree depth and size, steps, `range`, repeated and joined sequences, `**`, integers and strings are limited, and a size is decided *before* the work where Python would do the work first |
| An error, never a crash | every failure of the text is a `TelError` with a stable `code`; Python's own limits (deep nesting, stack, 4,300-digit integers, null bytes, lone surrogates) are limit errors |
| Messages are safe to log | they name types and names, never a value from the scope |
| Nothing in the scope is asked to run code by an operator | the *inert rule*: operators, truth tests, indexing, text and the built-in functions touch plain values only |

| TEL does **not** guarantee | because |
|---|---|
| What the host's own objects do | reading `obj.title` runs the host's property or `__getattr__`; a `Mapping` subclass counts as plain and its `__getitem__` runs |
| What is *inside* a plain container | the inert rule is shallow: a list is plain, and an object the host put in it is the host's |
| A limit that the host raised | `Limits(max_steps=10**30)` is accepted; it is the host's choice, and a very large value gives up that guarantee |
| Wall-clock time | there is no timer (it would make the same expression pass or fail by machine load); cost is bounded by steps and sizes, which are deterministic |
| Anything about CPython itself | a bug in `ast.parse` or in a built-in type is outside the language |

## How it is checked, and how to check it again

| What | Where | Size |
|---|---|---|
| The reference corpus, as a set, with a pinned outcome per case | `tests/test_reference_tel.py` | 381 cases: 100 allowed, 55 disallowed, 198 escapes, 20 limits, 4 positions |
| The same tables against `expr.py`, where they came from | `tests/test_reference_expr_py.py` (needs the Tesserae clone) | 375 |
| Random expressions and templates against `expr.py` | `tests/test_differential.py` | 8,000 per run; 74,000 when run once for this review; the only disagreement was a bug in `expr.py` (`min`/`max`) |
| Every rule has a test that fails if the rule is removed | `python tools/removal_check.py` | **169 deliberate breakages**: parser 45, evaluator 89, template 20, API 15 |
| Every error code is documented, and every documented code can be raised | `tests/test_error_codes.py`, `docs/error-codes.md` | |
| The API under misuse | `tests/test_api_misuse.py` | 38 |

`tools/removal_check.py` applies each breakage to a source file (a check made `False`, a limit off by
one, a branch dropped), runs the tests that must catch it under a 2 GB memory cap, and restores the
file. A **survivor** means the rule is untested or redundant. It refuses to start on a source file
with uncommitted changes, and reports a *stale* rule when the code has moved away from its pattern.
Run it after any change to `src/tel/` (about 2 to 3 minutes). The sources that the dangerous
breakages would let through (a billion-character text, a `replace` that grows a million-fold) are
exactly why the cap is there.

## What the review found

Each of these was found by the method (a stronger test double, a removal check, a differential test,
or trying the misuse), not by reading:

1. **A real hole.** A slice bound such as `items[trap:]` was not checked, so Python called the
   object's `__index__`. Found when the test double `Trap` was made to record every special method an
   operator could reach, instead of only calls and iteration. Fixed; tested.
2. **Tests that passed for the wrong reason.** With a weak `Trap`, skipping an inert check still ended
   in a refusal (a `TypeError`), so about a dozen removals survived. The removal check showed it.
3. **Python's own limits.** Deep nesting raises `SyntaxError` ("too many nested parentheses"),
   `MemoryError` ("parser stack overflowed") or `RecursionError`; a long digit string raises a
   `SyntaxError`; a lone surrogate raises `UnicodeEncodeError`; an invalid escape prints a
   `SyntaxWarning` to stderr. All are now errors of the language, or silent.
4. **Columns.** `ast` reports UTF-8 byte offsets as columns (which `expr.py` used), so a caret drifted
   after any non-ASCII character. TEL counts characters.
5. **A version trap.** YAML reads `shell: 0.10` as the float `0.1`. `language` must be text, and a float
   is refused with a message that says to quote it.
6. **`expr.py` bugs found on the way:** every container argument of `min`/`max` was turned into a list;
   a built-in function's name could be returned as a value; only the object being indexed was checked,
   not the index.
7. **Checks that were dead code**, removed because removing either of a pair changed nothing: a
   second private-target check, a literal-length check the parser already made, a blank check that
   parsing already made.
8. **Python 3.14 specifics.** t-strings parse and are refused by name; an annotated nested function
   allocates an `__annotate__` function (so the compiler module has a documented mypy override);
   `except A, B:` without parentheses is valid and is what the formatter writes.

## The public API under the `sharp-edges` method

Surface: `compile_expression`, `compile_template`, `Expression.evaluate`, `Template.evaluate`,
`MapScope` / `Scope`, `Limits`, `Origin`, the `TelError` classes. Adversaries considered: the
**scoundrel** (writes the expression text), the **lazy host** (copies an example) and the **confused
host** (passes the wrong thing). Each misuse was tried (see `tests/test_api_misuse.py`):

| Misuse | Before | Now |
|---|---|---|
| Text that is `None`, `bytes`, an `int` | `TypeError: object of type 'NoneType' has no len()`, or "a bytes-like object is required" | `TypeError: the text must be a str, not NoneType` |
| A `str` subclass (a round-trip YAML loader makes them) | accepted; the parser called its overridden methods | copied to a plain `str` with `str.__str__`; none of its methods run |
| `limits=` a dict or `None`; `origin=` a tuple or string | `AttributeError` deep inside, or a wrong position | `TypeError: limits must be a tel.Limits, not dict` (and the same for `origin`) |
| `evaluate(a_dict)` (the likeliest mistake) | `'dict' object has no attribute 'lookup'` | `TypeError: the scope needs a lookup(name) method ... wrap a dict in tel.MapScope(...)` |
| A scope whose `names()` raises | the host's exception replaced the real "unknown name" error | the error is raised, without the hint |
| `copy.copy(expression)`, `pickle.dumps(expression)` | `AttributeError: an Expression is immutable`; "Can't pickle local object" | a copy is the object itself; pickling says to send `.source` and compile again |
| `Limits(0)`, `Limits(None)`, `Limits(True)`, a positional limit | refused when made | unchanged |
| A version as a float or `None` | refused | unchanged |

Left as it is, on purpose:

- **`Limits` can be raised without bound.** The host decides; a guarantee-turning-off value is never
  chosen by default.
- **`Origin(file, line, column)` takes two ints in a row.** Swapping them is possible; it is validated
  (1-based) and matches `expr.py` and the spec's examples.
- **`compile_template` returns `None` for text with no part.** The type is `Template | None`, so a type
  checker makes the caller handle it.
- **A template that is exactly one part gives that part's value, not text.** That is the point of it
  (T3); `Template.evaluate` documents it.
- **`Scope.lookup` may return anything.** Values that are not plain are never operated on, only read
  from; a module, class or function in a scope has no attributes an expression can read.

## Not covered yet (step 7)

- A Hypothesis grammar fuzzer over the whole language, including the properties "never hangs past the
  limit", "only ever a `TelError`", "never reaches a name outside the scope". The random tests so far
  are hand-written generators.
- Free-threaded Python (3.14t): the parser serialises its warnings guard with a lock and a compiled
  expression keeps no state between calls, but this has not been run on a free-threaded build.
- Adversarial timing under a slow machine: the tests' ceilings are generous and the real figures are
  milliseconds, but nothing measures worst-case cost per step.
- The host's objects in scopes (Shell values): their safety is the Shell's, and step 4's scope protocol
  is where the contract is written down.
