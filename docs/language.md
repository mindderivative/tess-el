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
| C | **Do statements have `if`?** | **No.** Statements are assignments and calls only. Conditional *structure* (`if`, `elif`, `else` on an entry) is step 5; inside a value, use `a if c else b`. |
| D | **`event`.** | A handler-only name, read-only, reserved, bound once per run ([section 7](#7-statements-and-event)). |
| E | **Literal `{{` in a template.** | No special escape: write `{{ '{{' }}`. |
| F | **Errors.** | One base class with three subclasses and a stable `code` on every error; **public `line` and `column` are 1-based** (`expr.py`'s column is 0-based). |
| G | **The language version argument.** | Required, keyword-only: `language="0.1"`. No default, so a file that declares no version cannot silently change meaning when TEL is upgraded. |
| H | **Nested templates** (a list or mapping with `{{ }}` strings inside). | Not in the core; the host walks its own structure. A helper may come later. |
| I | **Statements and `event` at all?** A message from the `shell` session (2026-10-26) says the maintainer's position is that TEL is expressions and structure only, and that handlers and events belong to the consumer, which may use TEL only to evaluate argument expressions at event time. That conflicts with D2 and D5, which the maintainer gave directly in this project. | **Hold until the maintainer confirms.** Sections 7 and 12 (statements, `event`, the writable and action parts of the scope) are written so they can be removed whole: expressions do not depend on them. If statements go, phase 5 (#14) is dropped and D2 and D5 are replaced by a new decision. |

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

handler = tel.compile_statements("n += 1; window.close()", language="0.1")
handler.run(scope, event=payload)  # -> None

template = tel.compile_template("Battery {{ battery }}%", language="0.1")
template.evaluate(scope)  # -> "Battery 63%"; None if the text has no {{ }}
```

- `language` accepts a version this release supports (`"0.1"` today) and raises `TelVersionError`
  otherwise; it never guesses. `tel.LANGUAGE` is the newest supported version, for hosts that want it.
- `limits=` takes a `tel.Limits` (section 9). `origin=` takes a `tel.Origin`.
- A compiled object is immutable and safe to share between threads; `evaluate` and `run` keep no
  state on it.
- Everything else is private. The package exports its public names in `__all__`.

## 4. Expressions

An expression is one Python expression, parsed with the standard `ast` module.

| Construct | Allowed | Notes |
|---|---|---|
| Constants | `int`, `float`, `str`, `True`, `False`, `None` | No bytes, complex, or `...`. |
| Names | `x` | Looked up in the scope, then the built-ins. The scope wins. A name starting with `_` is refused. |
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
| Calls | `f(a, *b, k=v)` | Only a built-in function or a whitelisted method (section 6). The callee must be a plain name or `value.method`. |

**Refused, with a clear message:** `lambda`, `:=`, `await`, `yield`, `& | ^ << >> ~ @`, any name or
attribute starting with `_`, statements, `**` unpacking, bytes, complex, `...`, `async`
comprehensions, and everything not listed above.

The reference tables `ALLOWED` (100 cases), `DISALLOWED` (55) and `ESCAPES` (198) are this section's
tests.

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

## 7. Statements and `event`

A handler is a short list of statements, separated by `;` or newlines (D2).

| Statement | Form | Rule |
|---|---|---|
| Assignment | `name = expr` | One plain name. The scope must say the name is writable. |
| Augmented | `name += expr` (also `-= *= /= //= %= **=`) | Same; `\|= <<=` and the other bitwise forms are refused. |
| Call | `action(args)`, `window.close()` | The callee is a dotted name that the *scope* declares an action. Not a built-in, not a method. |

Everything else is refused with a message that names it: `if`, `for`, `while`, `del`, `import`,
`def`, `class`, `with`, `raise`, `return`, `pass`, annotated assignment, attribute or subscript
targets (`x.y = 1`, `x[0] = 1`), chained assignment, tuple targets, and a bare expression
statement. There is no `if` statement (decision C): conditional structure is step 5.

Writable names and callable actions come from the scope, never from the text. A loop variable cannot
be assigned and cannot shadow an action. Statements run in order; the first error stops the run,
and writes already made stay (they are not rolled back). One step budget covers the whole run.

**`event` (D5, recommendation D).**

- It exists only in statements, as `event`. In an expression it is an ordinary, undefined name.
- The host supplies it per run: `handler.run(scope, event=payload)`. TEL keeps no reference to it
  after the run.
- It is read-only and follows the attribute rules of section 5 (`event.value`, `event["value"]`).
- The name is reserved: a scope that defines `event` is an error at compile time of the handler,
  so the same text cannot mean two things.
- Efficiency: the compiled handler binds it in one local slot, with no scope lookup per read.
- The payload is the host's. TEL does not copy or validate it beyond the inert rule.

## 8. Templates

Text with embedded expressions (D3). The text between `{{` and `}}` is one expression.

- A template with no `{{` is not a template: `compile_template` returns `None`.
- A template that is *exactly* one part (`{{ n }}`, with optional surrounding spaces inside the
  braces only) evaluates to that part's value with its type kept.
- Otherwise the result is text: literal pieces and each part's text, joined. `None` becomes the empty
  string; any other value goes through `str()`.
- A `}}` inside a string or a bracket belongs to the expression: `{{ '}}' }}`, `{{ {'a': 1}['a'] }}`.
- An unclosed `{{`, or an empty part, is a `TelSyntaxError` that points at the opening `{{`.
- **Literal `{{`** (recommendation E): write `{{ '{{' }}`. No escape syntax is added.
- **In YAML:** a plain scalar that *starts* with `{` is a flow mapping, so a value that begins with
  `{{` must be quoted (`"{{ x }}"`). `Battery {{ x }}%` needs no quotes.
- Nested templates in lists and mappings are the host's (recommendation H).

## 9. Limits

`tel.Limits` is a frozen dataclass. **Every field must be a positive integer; `0`, a negative number,
`None` and `inf` raise `ValueError` at construction.** There is no value that turns a limit off.

| Field | Default | Error when exceeded |
|---|---:|---|
| `max_source` | 2,000 | characters of expression text |
| `max_depth` | 40 | nesting of the syntax tree |
| `max_nodes` | 1,000 | nodes in the syntax tree |
| `max_steps` | 200,000 | steps in one evaluation or run |
| `max_range` | 100,000 | length of a `range` |
| `max_sequence` | 1,000,000 | items in a repeated or joined sequence |
| `max_pow_exponent` | 64 | exponent of `**` |
| `max_int_bits` | 4,096 | bits in an integer result |
| `max_string` | 1,000,000 | characters in a string result |

**Steps are charged where cost can grow, not per node.** A straight-line expression is at most
`max_nodes` nodes, so it needs no counter. A comprehension charges its iterations times the node
count of its body (known at compile time); a call to an iterating built-in charges its input's
length first. This is what makes closures fast (section 11) without losing the guarantee.
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
| `code` | A short stable identifier (`private-name`, `unknown-name`, `limit-steps`, ...). Match on this, not on the message (recommendation F). |
| `source` | The expression text. |
| `line`, `column`, `end_column` | **1-based**, in the host file when an `Origin` was given, otherwise in the text. |
| `hint` | "did you mean ...", where there is a near match. |

`error.render()` returns the source line with a caret under the span. `str(error)` is
`file:line:column: message`. **Messages never contain values from the scope**, only names and types,
so an error is safe to log.

`Origin(file, line, column)` is where the expression text starts in its file (1-based), so a column
inside a YAML scalar maps to the file (T6). Leading whitespace and later lines of a multi-line
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

**Caveat.** The spike has none of the safety checks (the inert rule, size checks on `*`, `**` and
`+`, attribute rules, positions on error), and `expr.py` has all of them. The real gain will be
smaller. Closures still win by 2.2 to 4.3 times over walking with the same checks, because a check is
decided once at compile time (a private attribute name, a method that is not on the list) or sits in
the one place a value can grow (`*`, `**`, `+` on sequences, string methods). The 3x target (D1) is
judged in phase 4 on the real evaluator, and if closures do not reach it the choice is revisited
with numbers.

## 12. The scope, as far as step 3 needs it

Step 4 designs the full protocol and name tracking (T5). Step 3 needs only:

```python
class Scope(Protocol):
    def lookup(self, name: str) -> Any: ...  # raises KeyError if the name is not there
    def names(self) -> Iterable[str]: ...  # optional; for "did you mean"
    # statements only:
    def is_writable(self, name: str) -> bool: ...
    def assign(self, name: str, value: Any) -> None: ...
    def is_action(self, path: str) -> bool: ...
    def call_action(self, path: str, args: list[Any], kwargs: dict[str, Any]) -> Any: ...
```

The scope returns plain values: a host with reactive types unwraps them in `lookup`.
`tel.MapScope(values, writable=..., actions=...)` is provided for plain dicts, tests and standalone use.

## 13. Out of scope for step 3

Name tracking and the full scope protocol (step 4); `if`, `elif` and `else` on entries, repeaters, and
the `<name>_0001` naming (step 5); the Python builder (step 6); the fuzzer and per-rule removal checks
for the whole language (step 7); judging the efficiency target (step 8).
