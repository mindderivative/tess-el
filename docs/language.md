# TEL language specification, draft 0.1.0

> **Status: draft for the maintainer's approval (Step 3, phase 1, #10).** No code is written until it
> is approved. Section 1 lists the choices that need a decision, each with a recommendation. The
> rest is the language as it would be built if every recommendation were accepted.

TEL is a small, safe expression language and the library that parses and evaluates it. It
evaluates *values and structure only*: no file, process, network or system access (T2). Syntax is a
Python-like subset, checked against a whitelist: anything not listed here is refused.

Sources: the decisions in [`decisions.md`](decisions.md), the brief's requirements T1 to T14, and the
behaviour of Tesserae UI's `expr.py` (read for reference; see
[`reference-cases.md`](reference-cases.md)).

## 1. Decisions needed

| # | Question | Recommendation |
|---|---|---|
| A | **Evaluation strategy.** Walk the checked tree, or compile it once to Python closures? | **Closures.** The spike ([section 11](#11-evaluation-strategy)) is 2.2 to 4.3 times faster than walking and 7 to 16 times faster than `expr.py`. The spike omits the safety checks, so the real gain will be smaller; phase 4 re-measures against the 3x target. |
| B | **Core built-ins.** | Keep 23 (the 22 basic ones plus `clamp`). Drop `format_number`, `pluralize` and the five date helpers from the core; a host supplies such helpers itself ([section 6](#6-built-in-functions-and-methods)). |
| C | **Literal `{{` in a template.** | No special escape: write `{{ '{{' }}`. |
| D | **Errors.** | One base class with three subclasses and a stable `code` on every error; **public `line` and `column` are 1-based** (`expr.py`'s column is 0-based). |
| E | **The language version argument.** | Required, keyword-only: `language="0.1"`. No default, so a file that declares no version cannot silently change meaning when TEL is upgraded. |
| F | **Nested templates** (a list or mapping with `{{ }}` strings inside). | Not in the core; the host walks its own structure. A helper may come later. |

**Resolved: statements and events are not in TEL (D10, 2026-10-26).** TEL is an expression
language and nothing else. Handlers, assignment, calls to actions and event handling belong to the
consumer, which may use TEL to evaluate expressions (for example argument expressions) at the time
an event fires. This replaces D2 and D5; see [section 7](#7-events-and-statements-are-the-hosts).

## 2. Principles

1. **Whitelist, not blacklist.** Every allowed node, name, attribute and call is listed here and has
   a refusal test and a removal check (`sandbox-escape-review`).
2. **A bad expression is an error, never a hang.** Every limit has a named error that fails fast.
3. **Compile once, evaluate many (T4).** Checking happens at compile time wherever it can.
4. **The caller owns trust.** TEL evaluates against a scope the caller supplies. It never reaches
   outside the scope and the built-ins.
5. **Plain values out (T9).** Results are ordinary Python values.
6. **No reactive types, no Tesserae names (T1).** The host unwraps its own signals in `lookup`.
7. **Silent changes are errors.** Nothing here has a value that quietly means "unlimited" or "off".

## 3. Versioning and the API surface

The language version starts at `0.1.0` (D8). A host declares only major and minor (`shell: 0.1`) and
passes it to TEL; TEL has no file key of its own. Sketch of the public surface (names are final once
approved):

```python
import tel

expr = tel.compile_expression(
    "count + 1 if ready else 0", language="0.1", origin=tel.Origin("A.yaml", 14, 7)
)
expr.evaluate(scope)  # -> value

template = tel.compile_template("Battery {{ battery }}%", language="0.1")
template.evaluate(scope)  # -> "Battery 63%"; None if the text has no {{ }}
```

- `language` accepts a version this release supports (`"0.1"` today) and raises `TelVersionError`
  otherwise; it never guesses. It must be text: YAML reads an unquoted `0.1` as a number (and `0.10`
  as `0.1`), so a float is refused with a message that says to quote it (`code` `language-not-text`). `tel.LANGUAGE` is the newest supported version, for hosts that want it.
- `limits=` takes a `tel.Limits` (section 9). `origin=` takes a `tel.Origin`. `functions=` and
  `methods=` register the host's own functions and methods (section 12).
- `evaluate_tracked(scope)` evaluates and also returns the names the evaluation read (section 12.3).
- A compiled object is immutable and safe to share between threads; `evaluate` keeps no state on it.
  It is its own copy (`copy.copy` and `deepcopy` return it) and cannot be pickled (the error says to
  send `.source` and compile again).
- **The arguments are checked where they are passed.** The text must be a `str` (a subclass, such as
  the strings a round-trip YAML loader makes, is copied to a plain `str` and none of its methods run);
  `limits` must be a `tel.Limits`; `origin` a `tel.Origin` or `None`; a scope must have `lookup`
  (`TypeError: ... wrap a dict in tel.MapScope(...)`). A scope whose `names()` fails still gets the real
  error, without the hint.
- Everything else is private. The package exports its public names in `__all__`.

## 4. Expressions

An expression is one Python expression, parsed with the standard `ast` module.

| Construct | Allowed | Notes |
|---|---|---|
| Constants | `int`, `float`, `str`, `True`, `False`, `None` | No bytes, complex, or `...`. |
| Names | `x` | Looked up in the scope, then the built-ins. The scope wins. A name starting with `_` is refused, except `_` as a throwaway loop variable (`[0 for _ in items]`). Python folds wide characters (NFKC) before TEL sees a name, so `_＿class＿＿` is `__class__` and is refused. |
| Attributes | `x.y` | Read-only, public (section 5). |
| Subscripts, slices | `x[i]`, `x[a:b:c]` | Only on plain values. |
| Unary | `not`, `-`, `+` | |
| Binary | `+ - * / // % **` | `%` on text is refused (use an f-string). `**` has a limit. |
| Boolean | `and`, `or` | Return an operand, like Python. |
| Comparison | `== != < <= > >=`, `in`, `not in`, `is`, `is not` | Chains allowed. `is` compares only with `None`, `True` or `False`. |
| Conditional | `a if c else b` | |
| f-strings | `f'{x:>8.2f}'`, `!r`, `!s` | Conversions and format specs are limited to plain values. |
| Displays | `[...]`, `(...)`, `{...}`, `{k: v}` | `*x` is allowed in list, tuple and call arguments; `**x` is refused. |
| Comprehensions | list, set, dict, generator; `for ... in ... if ...` | Loop variables are local to the comprehension. Not `async`. |
| Calls | `f(a, *b, k=v)` | Only a built-in function or a whitelisted method (section 6), decided when the text is read. The callee must be a plain name or `value.method`; a comprehension variable cannot be called; a keyword argument name may not start with `_`. A call always means the built-in: a scope that defines `len` does not change what `len(x)` calls. |

**Refused, with a clear message:** `lambda`, `:=`, `await`, `yield`, `& | ^ << >> ~ @`, any name or
attribute starting with `_`, statements, `**` unpacking, bytes, complex, `...`, `async`
comprehensions, and everything not listed above.

What is decided when the text is **read** (before any value exists): the node whitelist, private
names and attributes, the constant types, `is` operands, `**` unpacking, which function or method
may be called, the `isinstance` types, comprehension targets, and the limits that can be seen in the
text (length, depth, node count, an integer or string literal, a constant `**` exponent: any constant
integer exponent over `max_pow_exponent` is refused whatever the left side is). Everything that needs
a value (attributes of a scope object, operand types, sizes of results) is decided when the
expression is **evaluated** (phase 4).

`isinstance(x, int)` names a type, not a variable: the type name is read from the text, so a scope
that defines `int` does not change it, and a comprehension variable named `int` makes the call an error.

`max_nodes` and `max_depth` count syntax-tree nodes other than operators and contexts (`Load`,
`Add`, ...): those are shared and have no children, so they are checked where they stand and not
counted. The root `Expression` is depth 1. Text that is valid Python *statements* (`x = 1`, `import os`) is a
`syntax-error` whose hint says TEL has none.

The reference tables `ALLOWED` (100 cases), `DISALLOWED` (55) and `ESCAPES` (198) are this section's
tests; [`reference-cases.md`](reference-cases.md) says which are decided at read time.

## 5. Values and attribute access

**The inert rule.** Operators, truth tests, subscripts, formatting, iteration, membership tests and
the built-in functions only touch *plain values*: `None`, `bool`, `int`, `float`, `str`, `list`,
`tuple`, `dict`, `set`, `frozenset`, `range`, `Mapping`, `Decimal`, `date`, `time`, `timedelta` and
`Enum`. An object of any other class may carry code in `__add__`, `__eq__`, `__bool__`, `__len__`,
`__getitem__` or `__format__`, so an expression may only *read its attributes*.

**Attribute reads.**

| The value is | `x.y` gives |
|---|---|
| a `Mapping` | the item `"y"`; a missing key is an error that names the nearest key. |
| any other object | the public instance attribute `y`, if it is not callable; a method is an error ("is a method"), a missing attribute names the nearest one. |
| a module, class, function, method, code, frame, generator, traceback or descriptor | never readable. |

**Left to step 4 (the scope protocol):** whether an object may narrow what it exposes (`expr.py` has
`__expose__`), and how a host supplies helper functions. Step 3 supports mappings and plain objects.

## 6. Built-in functions and methods

**Judged one by one (D4):** a function stays if it is generally useful, safe, pure and cheap to call.

| Function | Verdict | Reason |
|---|---|---|
| `len min max abs round sum` | keep | Basic, pure, cheap. |
| `str int float bool` | keep | Conversion. |
| `sorted reversed range enumerate zip` | keep | Return lists or `range`; inputs are size-limited and charged to the step budget. |
| `any all list dict tuple set` | keep | Same. |
| `isinstance` | keep | The second argument must be one of `str int float bool list dict`. |
| `clamp(x, low, high)` | keep | Pure, common for percentages and positions, no locale. |
| `format_number(x, digits)` | **drop** | `f'{x:,.1f}'` does it. |
| `pluralize(n, one, other)` | **drop** | Specific to English; `'item' if n == 1 else 'items'` does it. |
| `date_add_days`, `date_weekday`, `days_in_month`, `format_date` | **drop** | Specific formatting. A host that wants them supplies them. |
| `current_date` | **drop** | Reads the clock: an impure value would break "evaluate only when an input changed" (T14). The host passes the time as a value, like the Shell's clock module. |

**Methods** (the same whitelist as `expr.py`, by type):

- `str`: `lower upper title capitalize strip lstrip rstrip split splitlines join startswith endswith
  replace find count zfill isdigit isalpha center ljust rjust removeprefix removesuffix`
- `list`, `tuple`: `index count`
- `dict` and mappings: `get keys values items`

`format` and `format_map` are never allowed (a format string can reach attributes). Methods that
mutate (`append`, `pop`, `update`, ...) are refused. Width arguments (`center`, `ljust`, `rjust`,
`zfill`) are checked against `max_string`.

**Host-supplied functions and methods** (a host's own `format_number`, date helpers, ...) are pure
functions the host registers explicitly when it compiles; TEL never discovers them. See section 12.

## 7. Events and statements are the host's

TEL has no statements, no handlers and no event vocabulary (D10). There is no assignment, no call
to a host action, and no `compile_statements`. An assignment or an `if` statement is refused like
any other construct that is not listed in section 4.

A host that handles events does it itself and uses TEL for the values: when an event fires, it puts
whatever it likes in the scope (an `event` name, if it wants one) and evaluates its argument
expressions. `event` is then an ordinary name: nothing in TEL reserves it, binds it or treats it
specially, and the attribute rules of section 5 decide what `event.value` may read.

The Shell maps an event to a module method or a shell action on its own side.

## 8. Templates

Text with embedded expressions (D3). The text between `{{` and `}}` is one expression.

- A template with no `{{` is not a template: `compile_template` returns `None`.
- A template that is *exactly* one part (`{{ n }}`, with optional surrounding spaces inside the
  braces only) evaluates to that part's value with its type kept.
- Otherwise the result is text: literal pieces and each part's text, joined. `None` becomes the empty
  string; any other value goes through `str()`.
- **Where a part ends.** A part ends at the first `}}` after which the text reads as one Python
  expression. So a `}}` inside a string or behind a `{` belongs to the expression (`{{ '}}' }}`,
  `{{ {'a': 1}['a'] }}`, `{{ f'{{x}}' }}`), exactly as Python reads it, with no scanner of TEL's own to
  disagree with Python (3.12 allows the same quote inside an f-string). `}}}` has two possible
  endings; the first that reads wins. Text before the first `}}` that holds no quote and no `{`
  cannot hide one, so that `}}` ends the part without a trial. If no ending reads, the error is the
  syntax error of the first.
- An unclosed `{{` (`template-unclosed`) or a part with nothing in it (`template-empty`) is a
  `TelSyntaxError` that points at the opening `{{`. A part that is not an expression, or that the
  whitelist refuses, is that error, placed at the part in the file.
- **Positions.** Each part is compiled with the template's origin moved past the text before it
  (`Origin.advance`), so an error in the second part of a multi-line template is on the right line
  and column. Without an `origin`, positions are in the template text (line 1, column 1 at its start).
- **What a part gives in text:** `None` is nothing; a text is itself; any other plain value is
  `str(value)`; an object that is not plain is `value-not-plain`, pointing at the part. The text is
  limited by `max_string`, and `max_source` limits the whole template text.
- **One budget.** The parts of a template share one step budget, so a template of many loops cannot
  cost many budgets. Each evaluation starts a new one.
- **Literal `{{`** (recommendation C): write `{{ '{{' }}`. No escape syntax is added.
- **In YAML:** a plain scalar that *starts* with `{` is a flow mapping, so a value that begins with
  `{{` must be quoted (`"{{ x }}"`). `Battery {{ x }}%` needs no quotes.
- Nested templates in lists and mappings are the host's (recommendation F).

## 9. Limits

`tel.Limits` is a frozen dataclass. **Every field must be a positive integer; `0`, a negative number,
`None` and `inf` raise `ValueError` at construction.** There is no value that turns a limit off.

| Field | Default | Error when exceeded |
|---|---:|---|
| `max_source` | 2,000 | characters of expression text |
| `max_depth` | 40 | nesting of the syntax tree |
| `max_nodes` | 1,000 | nodes in the syntax tree (not counting operators and contexts) |
| `max_steps` | 200,000 | steps in one evaluation |
| `max_range` | 100,000 | length of a `range` |
| `max_sequence` | 1,000,000 | items in a repeated or joined sequence |
| `max_pow_exponent` | 64 | exponent of `**` |
| `max_int_bits` | 4,096 | bits in an integer result |
| `max_string` | 1,000,000 | characters in a string result |

**Steps are charged where cost can grow, not per node.** A straight-line expression is at most
`max_nodes` nodes, so it needs no counter. A loop is paid for **before it starts**: its length times
`1 + the nodes of its target + the nodes of its conditions` (plus the nodes of the element, for the
innermost loop of a comprehension), so `[i for i in range(10)]` costs `10 x (1 + 1 + 1) = 30` and fails
at `max_steps=29` without running. A call to an iterating built-in, a spread (`*x`) and an unpacking
charge the length of what they iterate. Building text or a sequence (`*`, `+`, `join`, `replace`, the
width methods) charges its length divided by 64, so a chain of large strings is stopped.
There is no wall-clock limit: it would make the same expression succeed or fail by machine load.

Limits are checked at compile time where they can be (`max_source`, `max_depth`, `max_nodes`, a
constant `**` exponent) and during evaluation otherwise. Each failure is a `TelLimitError` with a
`code` naming the limit.

## 10. Errors and positions

```
TelError(ValueError)
├── TelSyntaxError      # compile time: not valid, or not allowed (the whitelist)
├── TelEvaluationError  # evaluation time: undefined name, bad operand, no such attribute
└── TelLimitError       # any limit, at compile time or evaluation time
```

`TelVersionError` (an unsupported `language`) is a `TelError` too, raised before parsing.

Every error carries:

| Field | Meaning |
|---|---|
| `message` | Text for people. Not a stable API. |
| `code` | A short stable identifier (`private-name`, `unknown-name`, `limit-steps`, ...). Match on this, not on the message (recommendation D). |
| `source` | The expression text. |
| `line`, `column`, `end_column` | **1-based**, in the host file when an `Origin` was given, otherwise in the text. `end_column` is just past the last character of the span, or `None` (a span over several lines). All three are `None` for an error with no position, such as `TelVersionError`. |
| `hint` | "did you mean ...", where there is a near match. |

`error.render()` returns the source line with a caret under the span. `str(error)` is
`file:line:column: message`. **Messages never contain values from the scope**, only names and types,
so an error is safe to log.

`Origin(file, line, column)` is where the expression text starts in its file (1-based), so a column
inside a YAML scalar maps to the file (T6). `origin.advance(text)` gives the origin of what follows
`text`: the parser uses it to skip leading whitespace, and templates use it to place each `{{ }}` part.
Columns count characters, not bytes (Python's `ast` reports UTF-8 byte offsets, which `expr.py`
used as columns, so a caret drifted after any non-ASCII character) and not display width. Leading whitespace and later lines of a multi-line
expression are accounted for.

TEL logs nothing and does not depend on Loguru (a standing rule): the host turns errors into its own
messages.

**Compared with `expr.py`:** the error class and the 1-based `column` differ; ported reference cases
that check positions add 1 to the column, and cases that match message text are changed to match
`code` where the message wording changes. Each such change is listed in
[`reference-cases.md`](reference-cases.md) when phase 7 runs the tables.

## 11. Evaluation strategy

A checked `ast` can be run by walking it for every evaluation, or compiled once into a tree of Python
functions (closures) that are then just called. The spike (`benchmarks/spikes/closure_vs_walk.py`,
Python 3.14.8, same machine as the baseline) compares them on eight of the baseline workloads:

| Workload | `expr.py` µs | Walk µs | Closures µs | Closures vs `expr.py` |
|---|---:|---:|---:|---:|
| name | 0.56 | 0.10 | 0.04 | 12.9x |
| add | 1.36 | 0.28 | 0.10 | 14.0x |
| compare | 1.82 | 0.60 | 0.17 | 10.9x |
| conditional | 1.97 | 0.59 | 0.14 | 14.3x |
| arithmetic | 4.01 | 0.91 | 0.32 | 12.7x |
| attribute | 1.02 | 0.20 | 0.09 | 11.1x |
| subscript | 3.54 | 0.77 | 0.22 | 16.2x |
| f-string | 2.19 | 0.89 | 0.29 | 7.5x |

**Measured on the real evaluator (phase 4).** With every safety check in, closures are a median
6.1 times faster than `expr.py` on the baseline workloads (minimum 2.7, the 100-item comprehension 10.9),
below the spike's 7 to 16 as the caveat said they would be. The numbers, and where the remaining
memory and compile time go, are in [`benchmarks.md`](benchmarks.md#tel-against-the-target-step-3-phase-4-2026-10-27).
The choice stands: closures beat walking the same checked tree by 2 to 4 times in the spike, and no
benchmark has given a reason to revisit it.

**Closures are built to be small and quick to make.** A closure binds what it uses as default
arguments (a captured variable costs a 40-byte cell, a default 8), nested closures carry no
annotations (Python 3.14 allocates an `__annotate__` function for each annotated one, which is why
`tel._compiler` has a mypy override), a compiled expression keeps no syntax tree, and the common
shapes are one closure: `name op number`, `x op constant`, and a single-generator list comprehension.

## 12. Scope, name tracking, host functions and methods (step 4)

> **Status: approved by the maintainer on 2026-10-29 (decision D12).** Decisions A to F were
> approved with the scope of step 4, host methods were added to D the same day, and G to K were
> approved as recommended.

### 12.1 Decisions

| # | Question | Recommendation |
|---|---|---|
| G | **How a host adds methods** (`price.formatted()`). The object declares them, or the host lists them. | **The host lists them per type, at compile time** (`methods={Price: {"formatted": fn}}`). TEL, not the object, decides what is callable: an object that declared its own methods could expose whatever it likes, and a method found by looking at the object is exactly the lookup the language refuses to do (section 5). |
| H | **Methods on plain types** (`'abc'.titlecase()`, `n.formatted()` on an `int`). | **Allowed**: it is how a host brings back what step 3 dropped (`format_number`, date helpers). A host method may not reuse the name of a built-in method of the same kind of value (so `upper` can never be replaced), and may not be named `format` or `format_map`. |
| I | **What a host function or method may return.** | **A plain value**, as approved in D, checked and size-limited like the result of a built-in. Returning a host object (`workspace(1).name`) would be as safe as a scope value; it is left out because T9 says plain values out and it is easy to add later and hard to take back. |
| J | **A mistake in the registration** (a private name, a built-in's name, a non-callable). | **A `ValueError` or `TypeError` from `compile_expression`**, naming the entry, not a `TelError`: it is the host's bug, not the expression author's (section 3). |
| K | **The names read when an evaluation fails.** | **`TelError.reads`**: `None` for an error that did not come from a tracked evaluation, and a `frozenset` of the names asked for, including the one that was missing, when it did (decision C). |

### 12.2 The scope

```python
class Scope(Protocol):
    def lookup(self, name: str) -> Any: ...  # the value, or raises KeyError
    def names(self) -> Iterable[str]: ...  # optional; only for "did you mean"
```

The contract, clause by clause (each has a test, phase 4):

1. `lookup(name)` returns the value of `name` or raises `KeyError`. Any other exception is the host's
   bug and propagates unchanged; it is never turned into a `TelError`.
2. **It may be asked any number of times, in any order, for the same name in one evaluation**
   (`a + a` asks twice; an expression that does not use a name never asks), and must give the same
   answer each time. TEL does not cache.
3. **It must be quick and have no effect**: it is called while an expression is being evaluated, and
   a tracked evaluation relies on it asking only for what the expression needs. It may evaluate
   another expression (re-entrancy is tested).
4. It returns plain values wherever it can: a host with reactive types unwraps them here. A value
   that is not plain is carried and its attributes can be read, but no operator, comparison, index,
   text or function argument may touch it (section 5). A function or class in a scope is a value an
   expression can return and nothing else; it has no attributes to read and cannot be called.
5. `names()` is optional and is called only to build a hint. If it fails the real error is raised
   without the hint.
6. A scope is not copied or inspected by TEL beyond `lookup` and `names`. `tel.MapScope(values)`
   copies a mapping once, when it is made.

### 12.3 Name tracking (decisions A, B, C, F)

```python
tracked = expr.evaluate_tracked(scope)  # Tracked(value=..., reads=frozenset({"battery", "state"}))
value, reads = tracked
```

- **`evaluate(scope)` is unchanged**, and no slower. `evaluate_tracked(scope)` runs the same compiled
  expression with a lookup that records each name asked for, and returns `Tracked(value, reads)`, a
  `NamedTuple`. **The cost is about 350 to 470 ns more per evaluation** (measured on the built
  version: `count + 1` 210 ns plain, 570 tracked; a 100-item comprehension 1.7 µs and 2.1 µs): a
  set, a recording function that wraps `lookup` (one more call per name read), a copy of the set
  and the result. The first estimate, 120 to 180 ns, left out the last three. It is still about 2.5
  times faster than `expr.py` evaluating `count + 1` without any tracking (1.4 µs).
- **`reads` is the set of names the evaluation actually asked the scope for**, which can be fewer
  than `expr.names` (the syntactic names): in `a if flag else b` an evaluation reads `flag` and one
  of `a`, `b`. The host re-collects `reads` after every evaluation, because the next one may read
  something else.
- **Top-level names only** (B): `ws.name` reads `ws`. What `ws.name` itself depends on is the host's
  reactive layer, which knows its own objects.
- **Not reads**: a comprehension's loop variables; the name of a built-in or host function in a call
  (F); a method name.
- **A name that is missing is still read** (C): the recording happens before the lookup, so the
  `reads` of a failing evaluation include the name that failed.
- **Errors carry the reads (K).** A `TelError` raised during a tracked evaluation has
  `error.reads`; an exception from the host's `lookup` propagates unchanged and its reads are lost,
  because it is the host's bug.
- **A constant expression** is one whose `expr.names` is empty (`2 * 60`, `'x'.upper()`): its value
  does not depend on the scope. A host evaluates it once. This is documented, not an API (E).
- **Templates**: `Template.evaluate_tracked` returns the union of its parts' reads; a template that is
  exactly one part keeps the part's type, as `evaluate` does. A template with no parts has no
  `Template` object and so nothing to track.
- **Free-threaded safety**: the recording set belongs to one call; nothing is shared between calls.

### 12.4 Host functions

```python
expr = tel.compile_expression(
    "format_number(total, 1)",
    language="0.1",
    functions={"format_number": lambda x, digits=0: f"{x:,.{digits}f}"},
)
```

- `functions=` is a mapping from a name to a callable, on `compile_expression` and
  `compile_template`. It is copied when the expression is compiled, so changing the host's dict later
  changes nothing.
- **A call means the registered function** whatever the scope says (as for the built-ins), and
  the function name is not a read (F). Reading the name as a value is the same error as for a
  built-in (`function-as-value`).
- **Name rules (J)**, checked at compile time with a `ValueError`: an identifier; not starting with
  `_`; not a Python keyword; not the name of a built-in function (`len` can never be replaced); a
  callable.
- **Arguments** must be plain values (section 5), and lists, tuples, dicts and sets are passed as
  they are, not copied: **a function that changes its arguments changes the host's data**. That is
  the host's contract; TEL cannot check purity.
- **The result must be plain (I)**, with the sizes of section 9 applied (`max_string`,
  `max_int_bits`); a result that is not plain is `result-not-plain`. The cost of a call is one step
  plus the length of a text result divided by 64, as for a method.
- **An exception** from the function is `bad-call` naming the function and the exception's class,
  never its message (it may hold values from the scope). `TelError` raised inside propagates.
- **Calls** take positional arguments, `*spread` (limited like the built-ins') and keyword arguments;
  `**` is refused by the parser, as for the built-ins, and a keyword name starting with `_` too.

### 12.5 Host methods (decisions D, G, H)

```python
expr = tel.compile_expression(
    "price.formatted() + ' ' + name.titlecase()",
    language="0.1",
    methods={Price: {"formatted": Price.formatted}, str: {"titlecase": str.title}},
)
```

- `methods=` is a mapping from a **type** to a mapping from a method name to a callable, copied when
  compiled. `fn(receiver, *args, **kwargs)` is called with the value the method was called on.
- **Which receiver (G)**: the value's exact type is looked up first, then its base classes in order
  (so a registration for `Price` serves a subclass of it). An object that is not of a registered
  type has no methods: `method-not-for-type`, as for a number with `.upper()`. **The object is never
  asked what it can do.**
- **Plain types (H)** may be registered (`str`, `int`, `float`, `list`, `dict`, ...). A registration
  may not reuse a method name of the built-in whitelist (section 6) for a type it covers (the
  built-in set is not replaceable), may not be `format` or `format_map`, and may not start with `_`.
  `object` and the types of section 5 whose attributes are denied (modules, classes, functions) cannot
  be registered.
- **Arguments, results, errors and cost** are the rules of 12.4. The **receiver** is passed as it is
  and need not be plain: it is the type the host named.
- **Reads**: the receiver is whatever the left side reads (`price` is a read); the method name is not.

### 12.6 What the parser decides, and what is left to evaluation

The parser decides, from the text and the registrations, which names may be called and which method
names may follow a `.`: a method name that is in no registration and not in the built-in list is
refused when the text is read (`method-not-available`), as before. Whether *this* value has that
method is decided when it is evaluated (`method-not-for-type`). A function name that is not a
built-in and not registered stays `call-not-function`.

### 12.7 New errors

| Code | Class | When |
|---|---|---|
| `result-not-plain` | `TelEvaluationError` | a host function or method returned something that is not a plain value |
| `bad-call` | `TelEvaluationError` | (existing) a host function or method raised |

A bad registration is a `ValueError` or `TypeError`, not a code.

## 13. Out of scope

Statements, handlers and event handling (never: D10). Reactive types, subscriptions and re-running
(the host's). `if`, `elif` and `else` on entries, repeaters, and the `<name>_0001` naming (step 5); the Python builder (step 6); the fuzzer and per-rule removal checks
for the whole language (step 7); judging the efficiency target (step 8).

## 14. Evaluation rules, as built (phase 4)

Settled while writing the evaluator; each has a test.

- **A built-in function's name is not a value.** `len` alone is a `function-as-value` error ("call it, as
  len(...)"); a scope that defines `len` wins for the name read as a value, and `len(x)` always calls the
  built-in. This is also why a function can never be handed to `sorted(key=...)` in 0.1.
- **Index and slice bounds must be plain**, like every other operand (`items[trap:]` is refused).
  Dict keys and set members must be plain *and* hashable (`bad-key`).
- **Exceptions are named, not quoted.** A failing built-in or method is `bad-call` with the function's
  name and the exception's class (`int() failed (ValueError)`); a host property that raises is
  `attribute-failed`. Messages never contain a value from the scope, so an error is safe to log.
- **Sizes are decided before the work** where Python would do the work first: a repeat or join, a `**`,
  a width (`center`, `ljust`, `rjust`, `zfill`), a `replace` that would grow the text, a `join`, a `range`,
  and the width or precision of an f-string format spec (written in the text: checked once, when the
  expression is compiled).
- **`dict.keys()`, `.values()`, `.items()`, `reversed`, `enumerate`, `zip` and generator expressions give
  lists**, so every result is a plain value that can be kept and compared.
- **`isinstance` and `issubclass`-style checks never ask the object**: `isinstance(x, str)` looks at
  `type(x)`, so an object that lies about its `__class__` is just an object.
- **An exception from `scope.lookup` other than `KeyError` is the host's and propagates**; `TelError` is for
  problems with the expression.
- **`Expression` is immutable and thread-safe**: all state of one evaluation is on the stack of that
  call.
