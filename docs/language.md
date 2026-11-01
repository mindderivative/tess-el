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
| `reads` | The names a tracked evaluation had asked the scope for when it failed (a `frozenset`, including a name that was missing), or `None` when the error did not come from `evaluate_tracked`. |

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
7. **Attribute steps on what a scope returns** (added with path tracking). An attribute chain on a
   value from `lookup` reads each step with one `getattr` on the host's object, in order, and reads
   nothing else; it happens again at every use and every evaluation, and an attribute the
   expression does not reach is never read. Like `lookup`, a property must be quick and have no
   effect. Unlike `lookup`, an exception from a property is not propagated: it becomes
   `attribute-failed`, with no text from the host's exception. A method is not an attribute
   (`attribute-is-method`).

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
- **`reads` is the set of paths the evaluation actually read** (a name such as `flag`, or an
  attribute chain on a name such as `RootShell.DP1.Width`; see 12.8, which changed decision B), which
  can be fewer than `expr.paths`: in `a if flag else b` an evaluation reads `flag` and one of `a`,
  `b`. The host re-collects `reads` after every evaluation, because the next one may read something
  else. `Tracked.names` gives the top-level names behind `reads`.
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
- **Name rules (J)**, checked at compile time with a `ValueError` (a `TypeError` for something of the
  wrong kind): a `str` that is an identifier; in NFKC normal form (Python folds names written in wide
  characters, so `ｆmt` could never be written as such); not starting with `_`; not a Python keyword;
  not the name of a built-in function (`len` can never be replaced); the value callable. A loop
  variable of the same name makes the call an error (`call-not-function`), as for a built-in.
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
  `object` and the types of section 5 whose attributes are denied (modules, classes, functions,
  frames, ...) cannot be registered, nor can their subclasses; the built-in method names of a type
  are protected for its subclasses too (a `str` subclass cannot replace `upper`).
- **Found name by name**: the nearest class that registered *that name* serves it, so a subclass
  registering `two` does not hide a base class's `one`.
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

### 12.8 Path tracking (built; decision D13)

> **Status: approved by the maintainer on 2026-10-31 (decisions L to R as recommended) and built.** It
> changed decision B (top-level names only). Phase 4b, `tests/test_paths.py`, removal group `paths`.

**Why.** The Shell supplies a tree of plain objects as the scope and writes
`RootShell.DP1.Top_Bar.Width`. Today a tracked evaluation reports `{RootShell}`, so every
expression that reads anything under `RootShell` depends on all of it. With paths it depends on
`RootShell.DP1.Top_Bar.Width`.

```python
expr = tel.compile_expression(
    "RootShell.DP1.Top_Bar.Width + RootShell.DP1.Top_Bar.Height", language="0.1"
)
value, reads = expr.evaluate_tracked(scope)
# reads == {"RootShell.DP1.Top_Bar.Width", "RootShell.DP1.Top_Bar.Height"}
expr.paths  # the same two, known from the text before any evaluation
```

#### Decisions

| # | Question | Recommendation |
|---|---|---|
| L | **What `reads` holds.** | **Dotted paths, in place of the top-level names.** A bare name is a path of one step (`battery`), so an expression with no attribute reads is unchanged. `Tracked` stays a 2-tuple (`value, reads`), because a third field would break `value, reads = ...`. A `Tracked.names` property gives the top-level names (`{p.split(".")[0] for p in reads}`), which is exactly what `reads` was. |
| M | **What extends a path.** | **Only attribute steps on a free name.** The path stops at the first subscript, call or other expression: `RootShell.items[0].x` reads `RootShell.items`; `RootShell.name.upper()` reads `RootShell.name` (a method name is not a read; a host method's receiver chain is). A chain rooted at a loop variable is not a read (it is a local); the iterable that made it is: `[w.name for w in RootShell.workspaces]` reads `RootShell.workspaces`. |
| N | **Which paths a tracked evaluation reports.** | **Each chain actually evaluated, in full, and nothing shorter.** `RootShell.DP1.Width` reports that path, not `RootShell` and `RootShell.DP1`: the host derives prefixes if it wants them. A prefix is reported only if it is also read as a value (`RootShell.DP1` returned or compared). Short-circuit and branch rules are unchanged. **On failure** the path asked for is reported up to and including the step that failed (`RootShell.DP1.nope`), as a missing name is today (decision C), and it is on `TelError.reads`. |
| O | **What a property hides.** | **Nothing is promised.** `Top_Bar.Area` as a property of the host's object reads `Width` and `Height` in the host's code; TEL reports `RootShell.DP1.Top_Bar.Area`. What `Area` depends on is the host's, as in B. Said in the docs. |
| P | **Constant subscripts** (`d['k']`, `items[0]`). | **Not part of a path in 0.1.** `d['k']` reads `d`. A mapping read by attribute (`d.k`) is a path (`d.k`), so the two spellings differ. Extending a path through a constant subscript is possible later without breaking anything; it needs a rule for quoting a key that is not an identifier. |
| Q | **`Expression.paths` and `Template.paths`.** | **Yes: the paths in the text, known at compile time**, a `frozenset[str]` that includes every chain the expression could read (both branches of a conditional). `names` stays as it is (the top-level names). It gives the Shell its dependency report before any evaluation, and a tracked `reads` is always a subset of it (apart from the failing path of an error). |
| R | **Names and dots.** | A path is `name(.attr)*` where each part is an identifier TEL already accepts, so a dot never appears inside a part and a path can be split on `.` safely. Mapping keys that are not identifiers are only reachable by subscript, so they never appear in a path. |

#### How it works

- The compiler turns an attribute chain on a free name into **one closure** that reads the root
  and walks the attributes, instead of one closure per attribute (it has to: only a unit knows its
  whole path). The path string is built once, at compile time.
- A tracked evaluation sets `Run.paths`; the chain closure checks it once per chain and adds its
  path. Plain `evaluate` never sets it and pays that one check. **The compiler, not the parser,
  collects `Expression.paths`**: it already knows which names are loop variables, and a parser
  version cost every compile (including expressions with no chain) 3 to 4%. In tracked mode a chain reads its
  root through the scope directly, so the recording `lookup` does not also report the bare root.
  Bare names (no attribute) are still recorded by the recording `lookup`, as today.
- `Tracked.names`, `Expression.paths` and `Template.paths` are the only additions to the API.
  `Tracked` is still `(value, reads)`.

#### What was measured (`benchmarks/spikes/path_tracking.py`, Python 3.14.8)

| Expression (on plain objects) | `evaluate` now | `evaluate_tracked` now | one fused chain (no setup) | the same, recording the path |
|---|---:|---:|---:|---:|
| `ws.name` (1 step) | 573 ns | 995 ns | 464 ns | 462 ns |
| `RootShell.DP1.Top_Bar.Width` (4 steps) | 1,342 ns | 1,777 ns | 1,218 ns | 1,219 ns |
| `RootShell.DP1.Top_Bar.Inner.Deep.Leaf` (6 steps) | 2,109 ns | 2,540 ns | 1,934 ns | 1,929 ns |

- **Recording a path costs about 5 ns** (the last two columns). The fused column leaves out a whole
  evaluation (the `Run` object and the result, about 100 ns), so the fair comparison is `evaluate`
  now minus 100 ns against it: **fusing is about the same speed (0 to 4% faster), not a speed-up**,
  and the one `R.paths` check is lost in that. Plain `evaluate` does not get slower.
- **The expensive part is the attribute read, not the tracking:** about 280 ns per step on a plain
  object (it checks Mapping, the denied types, the primitive types, then `getattr` and `callable`).
  A dict step is about 40 ns. The Shell's tree of plain objects takes the slow path on every step.
  That is a step 8 target (a per-type decision cache), not part of path tracking, and the tracked
  numbers above include it.
- `evaluate_tracked` costs about 400 ns more than `evaluate` today, mostly the recording `lookup`
  and the result; that does not change.

#### What changes for existing code

- `reads` of an expression with an attribute chain on a free name changes from `{"ws"}` to
  `{"ws.name"}`. Any code that wants the old answer uses `Tracked.names`. No expression without an
  attribute chain changes. The tests that pin tracked reads change accordingly (phase 4b lists them).
- `TelError.reads` has the same shape.

#### What was measured on the built version (Python 3.14.8, same machine, before and after)

| | before | after |
|---|---:|---:|
| `evaluate` of `count + 1` | 213 ns | 214 ns |
| `evaluate` of `ws.name` | 569 ns | 577 ns |
| `evaluate` of `RootShell.DP1.Top_Bar.Width` | 1,333 ns | 1,353 ns |
| `evaluate` of a 6-step chain | 2,129 ns | 2,088 ns |
| `evaluate` of `[w.name for w in workspaces if w.active]` | 1,694 to 1,734 ns | 1,726 to 1,759 ns |
| `evaluate_tracked` of `RootShell.DP1.Top_Bar.Width` | 1,762 ns | 1,790 ns |
| compile of `ws.name` | 4.9 µs | 5.0 µs |
| compile of `RootShell.DP1.Top_Bar.Width` | 6.8 µs | 6.9 µs |

Plain evaluation is unchanged within noise (the three comprehension runs overlap). Compile is 1 to 3%
slower on chains and unchanged on expressions without one. A first version put the bookkeeping in the
parser and the chains in the compiler built a tuple of every prefix: that made compiling a chain 20
to 40% slower and was rewritten (prefixes are built only when a step fails; the compiler collects the
paths). **What a tracked evaluation reports:** `evaluate_tracked` of a chain reports the whole path
and not the bare root, because the chain reads its root from the scope directly.

#### Found while building

- The inlined forms `name op number` and `name op constant` read the name inside their own closure
  and bypassed the code that collected the static paths, so `Expression.paths` missed `x` in
  `x < 4`. The existing oracle test (`reads` must be a subset of `paths`) caught it.
- A loop variable that hides a scope name makes its chains local, and the same name after the loop is a
  read again: `[x.y for x in xs] + [x.y]` reads `xs` and `x.y`.

#### Not in this change

Subscript paths (P), per-item reads inside a loop (`w.name` for each `w`), the reads inside a host's
property or method (O), and any speed-up of `read_attribute` (step 8).

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

## 15. `cond ? a : b` (decision D14, built)

> **Status: built; issue #24.** Decisions S to W were taken by the maintainer on 2026-10-31 (S add it,
> T language 0.1, U allow in f-string fields, V refuse unbracketed mixing, W same precedence as
> `if/else`). D14 said to add this spelling if a cost test shows it is cheap; the spike
> (`benchmarks/spikes/ternary.py`) and its numbers are kept below, the numbers of the built code are in
> [benchmarks.md](benchmarks.md#cond--a--b-step-4-24).

**What it is.** A second spelling of `a if cond else b`: `cond ? a : b`. It is a read-time rewrite of
the text into `((a) if (cond) else (b))` before `ast.parse`, so the whitelist, the evaluator, the
tracker and `Expression.paths` see the same tree as for `if/else` and nothing about them changes
(a tracked evaluation of `ok ? a.x : b.y` reports exactly what `a.x if ok else b.y` reports).

**Grammar.** `?:` binds looser than `or`, like `if/else`, and is right-associative:
`a ? b : c ? d : e` is `a ? b : (c ? d : e)`; the middle part may hold another `?:`. The condition
starts where the expression starts: after `(`, `[`, `{`, a `,`, a dict or slice `:`, `for`, the `in` of
a comprehension, or the `if` of its filter. A `:` belongs to the nearest `?` that has none yet, so
`x[a ? 1 : 2 : 3]` is a slice from `a ? 1 : 2` to `3`, and `{k: a ? 1 : 2}` is one dict item.

**What was checked (30,000 random cases, 15,329 with a `?:`).**

- The rewritten text parses to the same tree as the `if/else` spelling in every case (calls, lists,
  dicts, subscripts, slices, comprehension element and filter, f-string fields and format specs,
  nesting in the middle and else parts, any spacing). Mismatches: 0.
- Every `Name` in the tree points at its own spelling in the original text: 0 wrong.
- Text with a `?` only inside a string, a comment or an f-string format spec (`f"{x:?>5}"`) is not
  changed. Templates work, including a `}}` inside a part (`{{ ok ? {'k': {'j': 9}}['k']['j'] : 2 }}`).
- The fast reader (no f-string in the text) and the full reader (f-strings) agree on all 9,118 cases
  they share.

**Cost** (Python 3.14.8, same machine as the other benchmarks; compile is microseconds per expression).

| | before (`if/else` spelling) | with the rewrite patched in | |
|---|---:|---:|---|
| `battery + 1` (no `?`) | 5.86 | 5.95 | 1.015x: noise; the check is one `"?" in text` |
| a long `if/else` chain (no `?`) | 18.37 | 18.30 | 0.996x |
| `'is it ok?' + title` (a `?` in a string) | 6.12 | 7.59 | 1.24x: the text is read, nothing is rewritten |
| `f'{battery:?>5}'` (a `?` in a format spec) | 8.21 | 11.63 | 1.42x |
| `battery < 20 ? 'low' : 'ok'` | 9.01 | 19.26 | **2.14x** |
| `a < 1 ? 'x' : a < 2 ? 'y' : 'z'` | 13.80 | 30.65 | 2.22x |
| `max(a, b ? c : d) + len(t ? s : 'none')` | 19.75 | 42.11 | 2.13x |
| a comprehension with a `?:` filter | 23.52 | 45.61 | 1.94x |
| `f"{ok ? 'yes' : 'no'}: {battery}%"` | 13.33 | 38.30 | 2.87x (the f-string reader is the slow one) |

- **Evaluation and memory are the same**: same tree, so the same closures. Evaluating `battery < 20 ?
  'low' : 'ok'` is 0.257 µs against 0.258; a compiled one keeps 1,410 bytes against 1,408 (measured over
  3,000 copies; over 300 the free lists of `list` and `tuple` make it look like +48, which is not real).
- **Compile of an expression that uses `?:` doubles**: 10 µs more for the simplest, 17 to 22 µs more for
  the larger ones (it grows with the text). For the simplest, reading and rewriting is about 4.8 µs and
  Python parses the longer, bracketed text about 2 µs slower than the `if/else` spelling; the rest is
  the tokens of a larger text. A first version that put every position back into the tree at compile time cost
  4.2x; mapping positions only when an error is made (below) removed half of it. For a shell with a
  thousand such expressions that is 10 to 20 ms at load. `expr.py` compiles the `if/else` form of the simplest one in 8.4 µs (docs/benchmarks.md, `conditional`), so against `expr.py` it is 2.3x (19.3 against 8.4). Against decision D1 criterion 3 ("compile no slower
  than `expr.py`", judged as a median over the workloads) these expressions are 2.3x slower; the median
  over today's workloads does not change, since none of them has a `?`.
- **Errors cost nothing until one happens.** The tree keeps the positions of the rewritten text.
  `node_span` (in `_parser` for compile-time errors, through `packed_span` for evaluation errors) redoes
  the rewrite and maps the position back to the original text; nothing is kept per expression, so the
  memory criterion is untouched. The spike patches those two calls from outside; in `src/` it is a
  few lines in `_Checker.fail` and `Site.fail`.

**Error positions** (all checked in the spike, columns 1-based characters). A failing name, attribute or
operation inside any part reports the column where its own text starts in the original, on one line or
several, after non-ASCII text, in a comprehension, in an f-string field and in a template part
(`ok ? 1 : 1 / 0` reports 1:10, the `1 / 0`). An unpaired `?` is reported at the `?`:

| Text | Error |
|---|---|
| `ok ? 1` | `this '?' has no ':' to go with it` at the `?` |
| `ok ? : 1`, `? 1 : 2`, `ok ? 1 :` | nothing between `?` and `:`; no condition before `?`; nothing after `:` |
| `ok ? 1 if x else 2 : 3` | `'?:' cannot be mixed with 'if ... else' without brackets` |
| `ok ? 1 : 2 : 3`, `(ok ? 1 : 2`, `ok ? 1 : 2)` | Python's own `syntax error`, at the stray `:` or bracket |
| `(ok ? 1 : 2` | `invalid syntax` at 1:9; without the `?`, `(1 if ok else 2` says `'(' was never closed` at 1:1. Unbalanced brackets lose the better message |
| `ok ? __class__ : 1`, `ok ? open('x') : 1` | the usual `private-name`, `call-not-function`, at the name |

These use the existing code `syntax-error`; no new error code is needed.

**The YAML problem, which the cost test did not ask about.** Checked with PyYAML 6.0.3:

| In a YAML file | Result |
|---|---|
| `x: a ? b : c` | **error**: "mapping values are not allowed here" |
| `x: a < 2 ? 'x' : 'y'`, `x: [a ? b : c]`, `x: Battery {{ a ? b : c }}%` | **error** |
| `- a ? b : c` | **silently a mapping**: `[{'a ? b': 'c'}]` |
| `x: a ? b :c`, `x: a?b:c` | works (a colon not followed by a space is text) |
| `x: 'a ? b : c'` or `"..."` | works |
| `x: a if b else c` | works |
| today's colon forms: `x: a[1: 2]`, `x: d['k': 1]` | **error**, the same way |
| `- d['k']: 1` | **silently a mapping**, the same way |
| `x: a[1:2]`, `x: {'k': v}` | works |

So the trap is not new: a slice or dict written with a space after the colon already has it. `?:` makes it much more likely, because a space around `:` is how a conditional is normally written.

A colon followed by a space ends a plain YAML scalar, so a value written with `?:` and the usual spacing
has to be quoted. `if/else` needs no quoting. The silent case (`- a ? b : c` in a list) hands the host a
mapping instead of text, which is the host's to catch and the author's to find out. The Shell puts
expressions in `{{ }}` slots, and a value that starts with `{{` is a YAML flow mapping, so the Shell's
files probably quote them already; for a bare value in plain YAML the advantage of `?:` over `if/else` is
mostly gone.

### Decisions

| # | Question | Recommendation |
|---|---|---|
| S | **Add `?:` at all?** | **Your call; the cost test passes with the caveats above.** Evaluation and memory are untouched, expressions without a `?` are untouched (within 1.5%), those with one compile about twice as slowly (10 to 22 µs more). The YAML trap is the real downside. If you want it, take T to W; if the Shell quotes its values anyway, I would add it. |
| T | **Which language version.** | **0.1**, since nothing is released (pre-alpha, not on PyPI). The alternative is 0.2 with `language="0.1"` refusing the `?`; that needs the parser to know the version, which it does not today (`check_language` only validates). |
| U | **Inside f-string fields** (`f"{ok ? 'a' : 'b'}"`). | **Allow it**, as tested (a `:` that pairs with a `?` is not a format spec). It needs the second, slower reader (2.9x compile). The alternative is to refuse a `?` operator in any text that has an f-string, with a message that says to use `if/else`: one reader, no f-string rules to test. |
| V | **Mixing with `if/else` in one expression without brackets.** | **Refuse** (`ok ? 1 : 2 if x else 3` has no obvious reading). Bracketed mixing is fine. |
| W | **Precedence.** | **Same as `if/else`**: lowest, right-associative, as in the grammar above. |

### As built

- `src/tel/_ternary.py`: the readers and the piece list (`pieces_of`, `join`).
- Hooks: `parse()` and `reads_as_expression` in `_parser.py` (so a template finds the end of a part), and
  `node_span` in `_spans.py`, which maps a position in the rewritten text back to the text the author wrote.
- `tests/test_ternary.py`: the differential test (random expressions written both ways give the same
  tree, every name reports its own position), the error table, templates, limits with wall-clock
  ceilings. Removal group `ternary` in `tools/removal_check.py`.
- A comprehension's iterable may be written with `?:` (`[v for v in xs ? [1] : [2]]`): the rewrite
  brackets the conditional, which Python accepts, and the reading is unambiguous, although the `if/else`
  spelling there (`for v in xs if c else d`) is a syntax error.

## 16. Structure: conditions and repeaters (step 5)

> **Status: draft for the maintainer's approval (step 5, design phase).** Nothing in `src/` changes
> until the decisions and the phases below are approved. The boundary and the surface forms are
> already decided in D15 (`decisions.md`); this section turns them into an API and settles what D15
> left open. The decisions are numbered 5A to 5M so that they do not clash with section 12's letters.

**What D15 fixed.** TEL evaluates expressions and reconciles keyed items; the Shell owns the YAML keys
(`if:`, `elif:`, `else:`, `for:`, `key:`), the tree and the UIDs. A condition is an expression. A
repeater is a header `item in items` (also `i, item in enumerate(items)`) and a separate key
expression. A missing or duplicate key is an error with a position, and the host owns the state
(the previous keys and the `<name>_0001` counters).

**The form in Tesserae UI** (read only, `design/yaml-language.md` section 7): `for: item in items`
with `key: item.id`; `if: unread > 0`; the whole value is an expression and does not take `{{ }}`.
When the list is reactive, nodes whose key persists are kept, new ones are built, removed ones are
destroyed, and the order follows the list. TEL does that bookkeeping and nothing else: building and
destroying nodes is the Shell's.

**Example, as the Shell would use it** (names are proposals, see 5E):

```python
chain = [tel.compile_condition("unread > 0", language="0.1")]           # `if:`; `else:` is the end
rep = tel.compile_repeater("w in workspaces", key="w.id", name="Workspace", language="0.1")

taken = tel.select(chain, scope)                 # which branch: its index, or None for `else`
state = tel.RepeaterState()                      # empty; the host keeps what reconcile returns
result = rep.reconcile(scope, state)             # entries in order, with kept/new/moved, removed keys
state = result.state
for entry in result.entries:                     # entry.key, entry.name ("Workspace_0001"), entry.item
    child_scope = entry.scope(scope)             # `w` bound over the host's scope
```

### 16.1 Decisions

| # | Question | Recommendation |
|---|---|---|
| 5A | **What a condition gives.** Truthy, as the UI says, or strictly a bool. | **Truthy, returned as a plain `bool`** (`Condition.holds(scope)`). `if: items` and `if: name` read naturally and match the UI. A value that is not plain (a host object) is refused as everywhere else (`value-not-plain`). |
| 5B | **The chain** (`if`, `elif`, `else`). The Shell owns the keys, but the tracking is TEL's business. | **A helper `select(conditions, scope)` that tests the conditions in order and stops at the first true one**, returning its index (or `None` when none is true: the `else`). A tracked form returns the reads of every condition tested, up to and including the winner: a host must re-run when an earlier, false condition flips. The helper never evaluates a condition after the winner. |
| 5C | **The header grammar.** | **`target in expression`**, where `target` is a name or comma-separated names (`w`, `i, w`), the same rule as a comprehension target (`comprehension-target`), and the expression is any TEL expression. No nested targets, no `if` filter, no `for` in the header (a filter is `if:` on the node). A header that is not this shape is `repeater-header`, pointing at the part that is wrong. |
| 5D | **What the list may be.** | **Anything a comprehension may loop over**: a list, tuple, set-free order only (a `set` is refused: its order is not stable), a dict (its keys), a `range`, a text. The same size limits apply (`max_range`, `max_sequence`, the step budget). A value that cannot be looped over is `not-iterable`. |
| 5E | **The API.** | **`compile_condition(source, *, language, origin, limits, functions, methods)` returns a `Condition`; `compile_repeater(header, *, key, name, language, origin, limits, functions, methods)` returns a `Repeater`; `Repeater.reconcile(scope, state)` returns a `Reconciliation`; `RepeaterState` is an immutable value the host owns.** The same keywords as `compile_expression`, so a host's registrations carry over. Tracked forms (`holds_tracked`, `reconcile_tracked`) mirror `evaluate_tracked`. `key` and `name` are required: there is no default key. |
| 5F | **What a key may be.** | **An `int`, a `str`, or a tuple of those.** Not a `float`, `bool` or `None`: `1 == 1.0 == True` would make two different items one key. Any other type is `bad-key-type` at the key expression. A key that makes the same value twice in one list is `duplicate-key`, naming both item positions. A key expression that fails fails like any expression. There is no fallback to the position. |
| 5G | **What `reconcile` returns.** | **A `Reconciliation`** with `entries` (in list order: `key`, `name`, `item`, `index`, `status` of `new` or `kept`), `moved` (the keys of kept entries whose order among the kept ones changed), `removed` (the keys that were in the state and are gone, in their old order), and `state`. Everything is a plain value or a tuple of them (T9). |
| 5H | **The name `<name>_0001`** (D7). | **TEL formats it**: `name` is given when the repeater is compiled and the number is assigned the first time a key is seen, from a counter in the state that only grows. A key that disappears and comes back is a new entry with a new number. The number is at least four digits and grows (`_9999`, `_10000`). A name that is not an identifier, or is private (starts with `_`), is a `ValueError` at compile time (the host's bug, as in 12.1 J). |
| 5I | **The item's scope.** | **`entry.scope(parent)` returns a `Scope` that binds the item names over the host's scope**; the host compiles the children as ordinary expressions and evaluates them in it. TEL does not compile children. The binding shadows a host name of the same name, as a comprehension variable does. The key expression is evaluated in the same layered scope. |
| 5J | **Reads through the item** (maintainer's choice, 2026-11-01). | **Reported as written.** A child expression `w.title` evaluated tracked in an entry's scope reports the path `w.title`; the host knows `w` is the entry with key `k` of `workspaces` and re-bases the path itself. No keyed path step is added (D13 decision P stays). Decision M (a chain from a comprehension variable is a local, not a read) is unchanged; it applies inside an expression, while the repeater's item is a free name of each child expression. The list expression and the key report their reads in the usual way. |
| 5K | **Limits.** | **No new `Limits` field.** The list is bounded by `max_sequence` (items in a repeated or joined sequence), each key evaluation has its own step budget (`max_steps`), and the whole reconcile has one more `max_steps` per item. If the builds show these do not fit, a field is added in the same phase with its test and its `limit-*` code. |
| 5L | **New error codes.** | **`repeater-header`** (syntax, compile time), **`bad-key-type`** and **`duplicate-key`** (evaluation). Added to `docs/error-codes.md`; positions as for any expression, and a header error is mapped back to the text the author wrote (the same lazy mapping as `?:`, D14). |
| 5M | **The proof for T8 ("works from YAML text").** | **PyYAML as a dev-only dependency**: a test loads a shell fixture (`if:`/`elif:`/`else:`, a `for:` with `key:`, nested), takes the loaded values and strings, and runs them through `select` and `reconcile`, including two successive loads that add, remove and reorder entries. TEL itself has no runtime dependency. |

**Language version.** Stays 0.1 (nothing is released). The header grammar is only read by
`compile_repeater`; no existing expression changes meaning.

**Security.** The header is parsed by Python's own parser as a comprehension header, so no new
syntax enters the whitelist; the key and the list are ordinary TEL expressions under the usual
limits. The new surface is the state value and the scope layering: `RepeaterState` holds only keys
(plain values), and `entry.scope` can only bind the names of the header. This goes through the
`sandbox-escape-review` and `sharp-edges` skills in the proof phase.

### 16.2 Proposed phases (sub-issues of #5)

| Phase | Work | Decisions |
|---|---|---|
| 1. Spec | This section, approved. | all |
| 2. Conditions | `compile_condition`, `Condition.holds`, `select`, tracked forms, tests, removal rules. | 5A, 5B |
| 3. Repeater header and key | `compile_repeater`, the header reading, key evaluation and checks, the new error codes. | 5C, 5D, 5F, 5L |
| 4. Reconciliation and state | `reconcile`, `RepeaterState`, `<name>_0001`, `entry.scope`, tracked forms. | 5E, 5G, 5H, 5I, 5J, 5K |
| 5. Prove it | The YAML test (5M), the whole removal check, `sandbox-escape-review`, `sharp-edges`, benchmarks, README and docs as built. | 5M |
