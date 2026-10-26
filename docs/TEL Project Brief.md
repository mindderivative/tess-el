---
title: TEL Project Brief
aliases: [TEL Brief, tess-el Brief, Tesserae Expression Language Brief]
type: spec
status: draft
owner: phil
created: 2026-10-25
updated: 2026-10-25
tags: [spec/runtime, tel, needs-verification]
related: ["[[ADR-0008 Tesserae Expression Language]]", "[[Expression Language Requirements]]", "[[Expression Languages for YAML]]", "[[ADR-0007 Shell UI Layer]]"]
depends_on: ["[[ADR-0008 Tesserae Expression Language]]"]
---

# TEL project brief

> [!summary]
> A hand-off document for the `tess-el` project. It explains what the Tesserae Expression Language (TEL) is, why it exists, who will use it, what the plan is, what the first consumer needs, and where to start. Tesserae Shell is the primary consumer; Tesserae UI is secondary. TEL starts from Tesserae UI's `expr.py` and is redesigned as a completely separate, standalone project. Written 2026-10-25 from the Tesserae Shell design vault; nothing here has been tested.

> [!info] How to use this note
> It is written to be read outside the vault. The vault's canonical notes are linked in [References](#references); if this brief and those notes disagree, the notes win and this brief is updated. The vault holds the Shell's needs. TEL's own grammar and design belong in the TEL repository, not in the vault.

## 1. What TEL is

The **Tesserae Expression Language** is a small, safe expression language, and a Python library that parses and evaluates it. It lets a plain YAML file say things like "show this only when the battery is low", "make one button per workspace", "use this colour when that value is above 80", and lets a Python program build the same thing as code. It is written in Python, used like any other Python library, and written `tel` in code, as `tre` is for the Tesserae Rendering Engine.

Its owner is the maintainer (Phil Hodgins, `mindderivative`). Repository: [mindderivative/tess-el](https://github.com/mindderivative/tess-el). Licence: MIT. Local project: `/home/phil/Projects/pyDev/projects/tess-el`. On 2026-10-25 the local clone held only the MIT `LICENSE`.

**Package name.** The maintainer's order of preference for PyPI is `tesserae-expression-language`, then `tel`, then `tess-el`. On 2026-10-25 `tel` already exists on PyPI, and no package named `tesserae-expression-language` or `tess-el` was found. Check again when registering.

## 2. Why it exists

Tesserae Shell is a tool for building desktop shells (bars, panels, frames, popups) from YAML files and Python modules. A shell file needs conditions, repeaters (one entry per workspace, per tray icon) and values that follow live data (a clock, a battery level). The maintainer decided the Shell's YAML has a full expression language, and that Python can build the same shell as code, with the same result.

Existing options were surveyed ([[Expression Languages for YAML]]): Jinja2 and its YAML wrapper jinjyaml, simpleeval, CEL (`cel-python`), a restricted evaluator on Python's `ast`. None fit as they are: Jinja2 and jinjyaml render text at load time, not live values, and the Jinja2 sandbox documentation says it is no perfect security; simpleeval and CEL would need work around them for live re-evaluation, name tracking and error positions. The maintainer chose to design a language of their own, so it does what the consumers need. Tesserae UI "needs something better than what it is currently using", and TEL is meant to be that too.

## 3. Consumers

| Consumer | Role | What it means for TEL |
|---|---|---|
| **Tesserae Shell** | **Primary.** Drives TEL's requirements and priorities. | The first and most demanding user. Its needs are in [section 5](#5-requirements-from-the-shell). |
| **Tesserae UI** (`tesserae-ui`) | **Secondary.** May adopt TEL later, replacing `expr.py`. | TEL must not be shaped around Shell-only ideas, so Tesserae UI can adopt it. Tesserae UI needs no changes from the Shell side. |
| **Anyone** | Adopts TEL in plain YAML by importing the parser in a Python script. | TEL must run alone: no Shell, no Tesserae UI, no tre, no GUI. |

**Independence.** TEL does not depend on the Shell, on Tesserae UI or on tre. The Shell depends on TEL. The maintainer keeps the Tesserae project completely separate and handles all contact with it; the Shell side does not contact the Tesserae project about `expr.py` or TEL.

## 4. The starting point: Tesserae UI's `expr.py`

TEL starts from `expr.py` and redesigns it. It is a starting point, not the design: TEL is separated from it and made much more efficient. Facts below were read from the local Tesserae clone (`/home/phil/Projects/pyDev/projects/tesserae`, commit `0eda3fe`, 2026-10-25). The code was read; it was not run or timed.

### What it is

`src/tesserae/expr.py`, 1,198 lines: "a sandboxed subset of Python". It parses with Python's `ast`, checks every node against a whitelist, and runs a small evaluator of its own. Nothing is ever `eval`ed. Its design is written up in Tesserae's `design/yaml-language.md`, sections 8 (expressions) and 9 (handlers).

### What it offers

| Part | Behaviour |
|---|---|
| `compile_expr(source, origin=, limits=)` → `Expr` | One expression. `evaluate(scope)`, `evaluate_raw`, `is_reactive(scope)`, `bare_name`. |
| `compile_template(text)` → `Template` or `None` | Text with `{{ ... }}` parts; a single part keeps the value's type, text around it makes a string. A `}}` inside a string or bracket belongs to the expression. |
| `compile_statements(source)` → `Statements` | A handler: assignments (`=`, `+=`, ...) and calls separated by `;`. `run(scope, event=)`. |
| `NestedTemplate` | A list or mapping with `{{ }}` strings inside it (a `Text`'s `runs`): evaluates to the same shape with each string worked out; reactive if any string is. |
| `Scope` (duck-typed; `MapScope` is the plain one) | `lookup(name)`, `names()`, `is_reactive(name)`, `assign(name, value)`, `is_action(path)`, `call_action(path, args, kwargs)`. |
| `Origin(file, line, column)` | Where the expression text starts in its file, so errors name the file, line and column inside a YAML scalar. |
| `ExprError` | Carries message, source, line, column, end column, a hint; `render()` draws a caret. Includes "did you mean" suggestions. |
| `Limits` | Caps: source 2,000 characters; syntax-tree depth 40; 1,000 nodes; 200,000 steps per evaluation; `range` 100,000; repeated sequences 1,000,000; `**` exponent 64; integers 4,096 bits; strings 1,000,000 characters. Each is a named error. |

**Allowed syntax** (Python `ast` nodes): constants, names, read-only attributes, subscripts and slices, unary and binary operators (`+ - * / // % **`), `and`/`or`/`not`, comparisons (`== != < <= > >= in not in is is not`), the conditional expression `a if c else b`, f-strings, list/tuple/dict/set displays, comprehensions with conditions, calls to whitelisted functions and methods, starred arguments.

**Not allowed:** lambda, await, yield, the walrus operator, bitwise operators, statements inside expressions, any attribute starting with `_`, `format`/`format_map` (they reach attributes), `getattr`, `eval`, `exec`, `open`, `type`, `globals`, `__import__`, and anything not whitelisted. An attribute or call on a module, class or function is denied.

**Built-ins:** `len min max abs round sum str int float bool sorted reversed range enumerate zip any all list dict tuple set isinstance`, plus `format_number`, `pluralize`, `clamp`, and date helpers (`date_add_days`, `date_weekday`, `days_in_month`, `format_date`, `current_date`). Whitelisted methods exist for `str`, `list`, `tuple` and `dict`.

**Static and reactive.** `Expr.is_reactive(scope)` says whether any name the expression reads is reactive in the scope. The caller binds a reactive one (re-evaluated on change) and substitutes the value of a static one.

**Directives.** `for:` and `if:` live in Tesserae's view loader, not in `expr.py`. `for: item in items` repeats a node; `if: unread > 0` includes it. They need a stable `key:` when the list is reactive, so nodes persist across list changes. There is no `else` (reserved: `elif:`, `else:`).

**Tests.** `tests/test_expr.py` has 49 test functions. The design's security plan lists a corpus of escape attempts that must all fail (`().__class__.__bases__`, `__import__('os')`, format-string attribute escapes, lambda tricks, generator frame access, unicode-identifier tricks, deep nesting, huge `range`/repeat/`**`) and a fuzzer over the node set. Whether that corpus and fuzzer exist in the tests was not checked.

### What ties it to Tesserae

- It imports `tesserae.reactive` (`Signal`, `Computed`), and unwraps them when it reads a name.
- Its reserved names are Tesserae's: `hovered`, `focused`, `pressed`, `event`, `app`.
- Its built-ins include Tesserae-flavoured helpers (`format_number`, `pluralize`, date helpers).
- Its handler statements assume a ViewModel with methods and writable Signals.
- Its directives and the `{{ }}` template form belong to Tesserae's view format.

These are what a standalone TEL must separate: no reactive types of its own, no Tesserae names, a scope supplied by the caller.

## 5. Requirements from the Shell

These are the Shell's needs (the canonical version is [[Expression Language Requirements]]). TEL is designed to meet them without depending on the Shell.

| # | Requirement |
|---|---|
| T1 | **Independent library.** Pure Python, installed like any library. It imports neither the Shell, tre nor Tesserae UI. |
| T2 | **Safe.** Evaluates values and structure only: no file, process, network or system access, no `eval`, no attribute escape. Limits on steps, size and repeated or powered values, so a bad expression is an error and never a hang. |
| T3 | **Two jobs, one language.** Values (a number, text, a colour) and structure (whether an entry exists, how many copies). TEL owns both. |
| T4 | **Live.** Compile once, evaluate many times. The caller can re-run an expression when an input changes. |
| T5 | **Name tracking.** After evaluation the caller can ask which names the expression read, so only expressions whose inputs changed are re-run. The name lookup is a plug-in point the caller supplies (a scope); TEL needs no reactive types of its own. |
| T6 | **Positions.** Every error carries file, line and column, with an origin the caller supplies so a column inside a YAML scalar maps to the file. |
| T7 | **Same result from Python.** The language has a Python form, so a shell written in Python builds the same tree as one written in YAML. |
| T8 | **Conditions and repeaters.** `{if condition, a, b}` is the maintainer's example. Repeaters make one entry per item of a list. |
| T9 | **Plain values out.** Results are plain Python values. Conversions to what the renderer accepts (for example a HEX colour to RGBA) are the Shell's. |
| T10 | **Versioned.** A file can say which language version it uses, so later changes do not break old files. |
| T11 | **Runs on Python 3.14** with no heavy dependencies. (3.14 is the Shell's minimum. TEL's own minimum is the TEL project's call.) |
| T12 | **Testable headless.** Parse and evaluate without a display. |
| T13 | **Standalone.** Anyone can use TEL in plain YAML by importing its parser in a Python script. |
| T14 | **Efficient.** Much more efficient than `expr.py`: parse once, cheap re-evaluation, nothing re-run unless an input changed. The target and benchmark are set in the TEL project. |

Acceptance criteria the Shell will use to judge TEL:

- A TEL expression compiles once and evaluates against a caller-supplied scope.
- After evaluation, the caller can list the names it read.
- An expression with an error reports file, line and column inside the YAML file.
- An expression that tries file, process or attribute access is refused with a clear error.
- An expression over a limit fails with an error and returns promptly.
- The same shell written in Python and in YAML builds the same tree.
- TEL installs and runs on Python 3.14 with no import of the Shell, tre or Tesserae UI.

## 6. How the Shell will use it

Context, so TEL's design fits the first user. The Shell's design is in the vault; this is the part that touches TEL.

- **Shell files.** YAML files with a required top-level `shell:` key (a version) and `type:` (`Shell`, `Module`, `Theme`, `Style`, `Stylesheet`). A shell is one file, or a `Main_Shell.yaml` that imports `<Name>_Shell.yaml` files with `import:` under `children:`. Imports nest. The file format, imports and surface kinds are the Shell's, not TEL's.
- **Surfaces.** Bar, Frame, Panel, Popup. Each has style properties (size, colour, border, radius, shadow, animation) that can be written as TEL expressions over live values.
- **Modules.** A module is a YAML file plus a matching `<Name>_Module.py`. The module keeps its own data and sends values to shell-provided entry points. The Shell passes them to the renderer and to TEL expressions that read them. A clock module sends the time; a label shows `{{ clock.time }}`.
- **Names and references.** Each entry has a required `name`, unique per monitor and scoped to its file. A UID (UUIDv7) is written into the file by the Shell and kept in a registry. Cross-file references resolve through the registry. TEL should see these as names in a scope the Shell supplies.
- **Monitors.** A root names a monitor; repeaters may make one entry per monitor or per workspace.
- **Live data.** Values change while the shell runs (time every second, battery, volume, workspaces). The Shell updates only what changed. Python is never in layout or paint; module and expression callbacks run on the event-loop thread, and blocking work runs on module threads that hand results over.
- **Logging.** The Shell is likely to use Loguru ([[Logging with Loguru]]). TEL should not depend on it: raise errors that carry positions, or use the standard `logging` module, and the Shell turns them into its own messages.

## 7. Where TEL ends and the Shell begins

A proposed boundary, for the TEL project and the maintainer to agree. The maintainer said TEL owns structures and values and everything it needs to run on its own.

| Concern | Owner | Note |
|---|---|---|
| Expression syntax, evaluator, limits, sandbox | TEL | |
| Conditions and repeaters (structure) | TEL | `if`, repeat, with keys for stable identity |
| Templates (text with embedded expressions) | TEL | |
| Names and scopes (lookup protocol) | TEL defines the protocol; the caller supplies the scope | |
| Name tracking (which names were read) | TEL | |
| Error positions and rendering | TEL | The caller supplies an `Origin` |
| Language version in a file | TEL | The Shell's `shell:` key is separate |
| Python builder (same result as YAML) | TEL | Parity is a TEL requirement (T7) |
| Shell file schema (`shell:`, `type:`, `kind:`, `children:`, `root:`) | Shell | |
| `import:` and file composition | Open: Shell recommended, since it needs the Shell's registry and paths | A standalone TEL user may want imports too |
| UIDs, registry, module loading | Shell | |
| Value conversion (HEX to RGBA, units) | Shell | |
| Surfaces, tre, rendering, Wayland | Shell | |

## 8. The plan

The maintainer's decisions so far (ADR-0008, 2026-10-25):

1. TEL is a separate library, in its own repository.
2. `expr.py` is the starting point, as a redesign.
3. TEL owns structure and values, and runs alone.
4. Syntax, statements and form are worked out in the TEL project.

A suggested order of work. This is a suggestion from the Shell side, not a decision:

| Step | Work | Done when |
|---|---|---|
| 1 | Project setup: packaging, `pyproject.toml`, tests, CI, docs skeleton, version policy | `pip install` works; an empty test passes |
| 2 | Baseline `expr.py`: port its tests as a behaviour reference; measure parse and evaluation time and memory | Numbers recorded for the efficiency target (T14) |
| 3 | Core: parser, whitelist, evaluator, `Limits`, `Origin`, `ExprError` with carets; no reactive types | The `expr.py` behaviours that are not Tesserae-specific pass |
| 4 | Scope protocol and name tracking | The caller can list the names an evaluation read (T5) |
| 5 | Structure: conditions and repeaters with stable keys | Both work from YAML text (T8) |
| 6 | Python builder with parity to the YAML form | A parity test shows both produce the same tree (T7) |
| 7 | Security corpus and fuzzer | Every escape in the corpus fails; each rule has a test that fails if the rule is removed |
| 8 | Performance work against the step 2 baseline | T14 target met |
| 9 | Packaging, PyPI name, release, docs | A tagged release installs on Python 3.14 |

## 9. Syntax questions the TEL project owns

Not decided. The Shell side has these preferences or examples:

- The maintainer's example form: `{if condition, do something, do something else}`.
- `expr.py` uses Python-style expressions inside `{{ }}`: `count + 1 if ready else 0`.
- Options to settle: Python-like expressions only; a call form (`if(cond, a, b)`); both. Whether statements (assignments, calls, as in Tesserae handlers) are part of TEL or only expressions. How `else` and `elif` are written. How a repeater names its item and its key. What the template delimiter is. How a file declares its TEL version.
- Whatever the syntax, it must fit as a YAML scalar or as a small structure inside YAML, so ordinary YAML tooling still parses the file.

## 10. Open items

- [ ] TEL's versioning and release process (the maintainer's).
- [ ] The PyPI name (check availability when registering).
- [ ] TEL's minimum Python version.
- [ ] Whether `import:` is TEL's or the Shell's ([section 7](#7-where-tel-ends-and-the-shell-begins)).
- [ ] The efficiency target and benchmark (T14).
- [ ] Syntax and statements ([section 9](#9-syntax-questions-the-tel-project-owns)).
- [ ] How the project and the Shell version together: the Shell pins a TEL version.

## 11. What is verified and what is not

| Verified (read 2026-10-25) | Not verified |
|---|---|
| `expr.py` size, API, limits, whitelist, built-ins, error model (read the source) | Its performance and memory use (nothing was run or timed) |
| Tesserae's design sections 8 and 9 (read) | Whether its security corpus and fuzzer exist in the tests |
| The `tess-el` repository and local project hold only `LICENSE` | That `expr.py` or its tests run on Python 3.14 |
| `tel` is taken on PyPI; the other two names were not found | That the other two names can be registered |
| The survey of Jinja2, jinjyaml, simpleeval and CEL used package pages and docs | Any candidate's behaviour (none was run) |

## References

Vault notes (canonical):

- [[ADR-0008 Tesserae Expression Language]] · [[Expression Language Requirements]] · [[Expression Languages for YAML]]
- [[ADR-0007 Shell UI Layer]] (the Shell's file format, modules, registry, names) · [[ADR-0006 Shell Independent of Tesserae UI]]
- [[Surface Types]] · [[V1 Scope]] · [[Logging with Loguru]]

Outside the vault:

- TEL repository: `https://github.com/mindderivative/tess-el` (local `/home/phil/Projects/pyDev/projects/tess-el`)
- Tesserae `expr.py`: `/home/phil/Projects/pyDev/projects/tesserae/src/tesserae/expr.py`
- Tesserae design, sections 8 and 9: `/home/phil/Projects/pyDev/projects/tesserae/design/yaml-language.md`
- Tesserae tests: `/home/phil/Projects/pyDev/projects/tesserae/tests/test_expr.py`
- Tesserae binding expressions guide: `https://mindderivative.github.io/tesserae/guide/bindings/`
