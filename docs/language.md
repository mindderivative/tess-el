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
- `limits=` takes a `tel.Limits` (section 9). `origin=` takes a `tel.Origin`.
- A compiled object is immutable and safe to share between threads; `evaluate` and `run` keep no
  state on it.
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

**Host-supplied functions** (a host's own `format_number`, date helpers, ...) are designed with the
scope protocol in step 4. They would be pure functions the host registers explicitly; TEL never
discovers them.

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
- A `}}` inside a string or a bracket belongs to the expression: `{{ '}}' }}`, `{{ {'a': 1}['a'] }}`.
- An unclosed `{{`, or an empty part, is a `TelSyntaxError` that points at the opening `{{`.
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

## 12. The scope, as far as step 3 needs it

Step 4 designs the full protocol and name tracking (T5). Step 3 needs only a read-only lookup:

```python
class Scope(Protocol):
    def lookup(self, name: str) -> Any: ...  # raises KeyError if the name is not there
    def names(self) -> Iterable[str]: ...  # optional; for "did you mean"
```

The scope returns plain values: a host with reactive types unwraps them in `lookup`.
`tel.MapScope(values)` is provided for plain dicts, tests and standalone use.

## 13. Out of scope for step 3

Statements, handlers and event handling (never: D10). Name tracking and the full scope protocol
(step 4); `if`, `elif` and `else` on entries, repeaters, and the `<name>_0001` naming (step 5); the Python builder (step 6); the fuzzer and per-rule removal checks
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
