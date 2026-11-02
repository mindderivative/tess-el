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
| What a property reads | a tracked evaluation reports the path of the property (`r.Top_Bar.Area`), not the attributes the host's code reads inside it |
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

## Step 4: tracking, host functions and methods, the scope contract

Applying `sandbox-escape-review` and `sharp-edges` to what step 4 added: `evaluate_tracked` and
`Tracked` (names, then paths), `Expression.paths` / `Template.paths`, `TelError.reads`, and the
`functions=` and `methods=` arguments. Everything below was tried against the built code.

**What the new surface can and cannot do**

| Surface | Guarantee | Where it is pinned |
|---|---|---|
| `reads` and `paths` hold only names and attribute names that appear in the expression text | no value from the scope is ever put in them, so an error's `reads` is as safe to log as its message | `tests/test_tracking.py`, `tests/test_paths.py` (a `Spy` oracle checks every attribute asked of the host) |
| A path is built only from identifiers the parser already accepted | a `_x` or dunder step is refused at parse time, so `a.__class__.__name__` never reaches a path | `tests/test_parser.py`, the reference corpus |
| Tracking changes no value and no error | `evaluate_tracked(...).value` equals `evaluate(...)` for every allowed case; the scope is asked exactly as a plain evaluation asks | `tests/test_tracking.py`, `tests/test_paths.py`, `tests/test_scope_contract.py` |
| A host function or method is called with plain arguments only and must return a plain value | an object, module or class in or out is refused (`value-not-plain`, `result-not-plain`); the host's exception text is dropped (`f() failed (ZeroDivisionError)`); the result is held to the text and integer limits and charged steps | `tests/test_host.py` |
| A registration cannot widen the language | a built-in function or method name, a `_x` name, a keyword, a non-NFKC name, `format` / `format_map`, and `object` or a type whose attributes are never readable are refused when registered (`ValueError` / `TypeError`) | `tests/test_host.py` |
| The scope is used only through `lookup` and `names` | a scope that logs every attribute asked of it sees nothing else; TEL keeps no scope between evaluations | `tests/test_scope_contract.py` |

**Misuse tried** (each line was run, and the "now" column is what happened):

| Misuse | Now |
|---|---|
| `reads.add(...)`, `paths.add(...)`, assigning to a `Tracked` | `reads` and `paths` are `frozenset`; `Tracked` is immutable; `paths` is a new object each call, so nothing can be shared by accident |
| `evaluate_tracked({"a": 1})` | the same `TypeError` as `evaluate` ("wrap a dict in tel.MapScope(...)") |
| `functions={"f": 3}`, `functions=["f"]`, `functions={"_f": len}`, `functions={"len": len}` | `TypeError` ("must be callable"), `TypeError` (needs a mapping), `ValueError`, `ValueError` (cannot replace a built-in) |
| `methods={"str": {...}}` (a string, not a class), `methods={object: ...}`, `methods={str: {"upper": ...}}` | `TypeError` (a key must be a class), `ValueError`, `ValueError` |
| A host function that returns `object()` or a module, takes an `object()`, raises, or returns 10^8 characters | `result-not-plain`, `value-not-plain`, `bad-call` naming the exception class only, a `TelLimitError` before the text is used |
| An attribute path whose property raises | `attribute-failed`, with no text from the host's exception; the failing path is on `TelError.reads` |
| `pickle` of a `Tracked` | works (it holds a value and a frozenset of text); `TelError` pickles with its `reads` |

**Left as it is, on purpose** (the host's side of the boundary, written in `docs/language.md` 12.2):

- **A property or a registered function is the host's code.** TEL bounds what goes in and out of it,
  not what it does inside; it must be quick and have no effect (clause 3 and 7). A property that
  reads other state hides that state from `reads` (decision O).
- **`reads` is the answer for the values given.** An expression that took another branch with
  other values reads other names; a host that caches dependencies must record again when a branch can
  flip (`docs/benchmarks.md` has the cost: about 1.9x an evaluation).
- **A scope can hand over any value.** A non-plain value is carried and its attributes are read, never
  operated on (clause 4); a function or class in a scope can be returned and nothing else.

**Found on the way:** inlined forms such as `x < 4` read their name inside their own closure and
missed the code that collects `Expression.paths`; the oracle "reads is a subset of paths" caught it.
A parser-side collection of paths cost every compile 3 to 4%, so the compiler collects them. A host
method looked up by asking the object would run the object's code: methods are found by the receiver's
type, name by name, and the object is never asked.

## The `cond ? a : b` rewrite (D14)

`src/tel/_ternary.py` changes the *text* before `ast.parse`, which is the one place where text the
author wrote becomes other text, so it was reviewed as a parser change (`sandbox-escape-review`).

| Question | Answer | Where it is pinned |
|---|---|---|
| Can the rewrite let through something the whitelist refuses? | No. The rewritten text is parsed by `ast.parse` and checked node by node like any other; the rewrite only adds brackets, `if`, `else` and moves text, so the tree is the one `if/else` makes. A refused name, attribute, call or construct inside any part is refused at its own position | `tests/test_ternary.py`: 3,000 random pairs give the same tree as the `if/else` spelling; the refusal table |
| Can a `?` inside a string, comment or format spec change the text? | No. Strings and comments are skipped by both readers, and a format spec is not read as an expression | `test_a_question_mark_that_is_not_an_operator_changes_nothing` |
| Can it hang or exhaust memory? | The text is bounded by `Limits.max_source` before it is read; reading is linear in the text, also for deeply nested `?:` (the `?`, `:` and `if`/`else` of each bracket are indexed once; with the limits raised, 100, 200, 400 and 800 nested middles take 0.3, 0.6, 2.2 and 2.3 ms, where the first version took 1.2, 4.3, 19.8 and 68.7 ms; deeper ones end as `limit-depth` within a few ms, when the recursion limit is reached); a deep chain or a deep middle (`a?a?a?...b:c:c:c`) ends as `limit-depth` (Python's own parenthesis limit and the recursion limit are mapped), not a crash | `test_a_long_chain_is_a_depth_error_not_a_crash`, `test_a_deep_middle_is_a_depth_error_not_a_crash` |
| Do errors point at the right text? | Yes, in the original text, in characters, on one line or several; the whole conditional is reported from its condition to the end of its else part. Positions are mapped only when an error is made, so an expression keeps nothing for it | `test_every_name_reports_the_position_of_its_own_text` and the position tables |
| Does the new syntax change what a tracked evaluation reads? | No: same tree, same reads and paths | `test_a_tracked_evaluation_of_a_ternary_reads_what_the_if_else_reads` |

Found while building: a trailing `# comment` swallowed the closing brackets of the last part (the
brackets are now put before it); an f-string conversion (`{c ? a : b!r}`) was part of the else
expression; and the first anchor of the conditional was the `?`, so an error at the whole
conditional was reported after its condition. The removal check (group `ternary`) found two branches
that changed nothing (`}}` outside a field; a `?` check in `original_node` that `pieces_of` repeats)
and they were removed.

**A YAML trap, not a TEL one:** a colon followed by a space ends a plain YAML scalar, so a value
written with `?:` has to be quoted (`docs/language.md` section 15, README). The same already holds for
`a[1: 2]` and `- d['k']: 1`.

## Step 5: conditions and repeaters

`src/tel/condition.py` and `src/tel/repeater.py` add no syntax and no node to the whitelist: a
condition, a repeater's list and its key are ordinary expressions compiled by `compile_expression`,
so every parser and evaluator rule applies to them. The new surface is the header reader, the loop
scope, the key rules and the state a host keeps. Reviewed with `sandbox-escape-review` and
`sharp-edges`.

| Question | Answer | Where it is pinned |
|---|---|---|
| Can the header let through something the whitelist refuses? | No. The header is split by a regular expression into names and the list text, and the list text is compiled as an expression. The names are checked like comprehension targets (no keyword, no private name, no repeat) | `test_a_name_that_is_a_keyword_or_private_or_repeated_is_refused`, `test_an_escape_is_refused_in_the_list_the_key_and_a_condition` |
| Do escapes get through the list, the key or a condition? | No: twelve escapes (`__class__`, `__import__`, `open`, lambda, `format`, `getattr`, `eval`, `:=`, a huge `**`, `yield`) are refused at compile time with a position, in all three places | same test, and `test_an_escape_through_a_host_object_item_does_not_get_out_of_the_scope` |
| Can a long list or a costly key hang it? | No. The list and every key share one `max_steps` budget per call (one step per item first); a list over `max_sequence` is refused before any key is made | `test_a_costly_key_over_a_long_list_ends_as_a_limit_error_in_reasonable_time`, `test_a_list_too_long_for_the_budget_is_refused_before_any_key_is_made` |
| Can a huge header hang it? | No. The header counts against `max_source` before it is read, and the reader is linear: three 1,000,000-character bad headers are refused in milliseconds | `test_a_header_over_max_source_is_refused_whole_before_it_is_read`, `test_a_huge_bad_header_is_refused_in_reasonable_time` |
| Can a key run host code? | No. A key is an `int`, a `str` or a tuple of those, copied to plain values with `int.__int__` and `str.__str__`, so a subclass's `__hash__` and `__eq__` never run; a `float`, `bool` or `None` is refused so that `1`, `1.0` and `True` cannot be one key | `test_a_str_or_int_subclass_is_a_key_as_its_plain_value`, `test_the_parts_of_a_tuple_key_are_plain_too` |
| Can a condition run host code? | No. It uses the evaluator's `truthy`: a host object is true without being asked, so its `__bool__` and `__len__` never run | `test_a_host_object_is_true_without_being_asked` |
| Do errors leak a value from the scope? | No. They name types, item positions and names, never a key or a value (`duplicate-key` says "items 1 and 3", not the key) | `test_a_duplicate_key_names_both_items_but_not_the_key` |
| Can the state grow without bound, or be mixed up? | It keeps only the keys of the last list and one counter. A state remembers the repeater's `name`; another name is a `ValueError` | `test_a_state_from_a_repeater_with_another_name_is_refused` |
| Do errors point at the right text? | Yes: the list in the header, the key in its own scalar (`key_origin`), a condition in its scalar, in the file, checked with PyYAML marks | `tests/test_yaml_structure.py` |

**Found while building** (each has a test and, where it is a rule, a removal rule): a host object was
refused as a condition although `not x` accepts it (now the same rule); each key had its own step
budget, so a key of `sum(range(100000))` over a long list ran for minutes (one shared budget); a
state from another repeater gave wrong names silently (now refused); a header was not counted against
`max_source`; and the loop scope's bindings were a public attribute (now private).

**Not guaranteed:** the scope an `Item` or `Entry` gives (`scope(parent)`) is the host's, not a
security boundary: it reads the host's `lookup`, and a host that reaches into its private attributes
can change the entry's own bindings. A `list` or `dict` subclass in the scope is read as the plain
type it extends, which calls its own `__iter__` and `__len__`, as for a comprehension; the safety of
host objects is the Shell's (see the scope contract, `docs/language.md` 12.2).

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
