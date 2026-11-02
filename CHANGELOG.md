# Changelog

All notable changes to the package. Versions follow [Semantic Versioning](https://semver.org); below
1.0 a minor version may break the API. The language version is separate and is 0.1 for every release
here (`docs/versioning.md`).

## Unreleased

- `Item` and `Entry` are tuples (`(index, key, value, bindings)` and the same plus `(name, status)`):
  `items()` is about 14% and `reconcile()` about 9% faster. They can now be indexed, unpacked and
  compared by value; they are still immutable and cannot be pickled.
- Smaller compiled expressions: a name used as an operand of `+ - *`, or as `name[0]`, `name[-1]`,
  `name['k']`, is read inside its parent's closure (arithmetic 0.75 to 0.57 and subscript 0.73 to 0.36 of
  `expr.py`'s bytes). Same results and errors; text concatenation is unchanged.
- Tested on free-threaded Python 3.14t (thread tests, a CI job). The workflows use actions on Node 24.

## 0.1.0

The first release: everything in the plan up to step 8.

### The language

- Expressions over a whitelist of Python's syntax tree (arithmetic, comparisons, conditionals,
  subscripts, comprehensions, f-strings, a set of built-in functions and methods), with `cond ? a : b`
  as a second spelling of `a if cond else b`.
- `{{ }}` templates, with one step budget for all parts.
- Limits on source size, nesting, nodes, steps, ranges, repeats, powers, integers and strings; every
  limit is a named `TelLimitError`.
- Errors that carry the line and column in the host file (`Origin`), the text, a caret and a hint.

### The host side

- `Scope` (`lookup`), `MapScope`, `evaluate_tracked` (the names and attribute paths an evaluation read),
  host functions and host methods, registered at compile time.
- `compile_condition`, `Condition`, `select` and `select_tracked` for `if` / `elif` / `else` chains.
- `compile_repeater`, `compile_repeater_parts`, `Repeater.items`, `reconcile`, `reconcile_tracked`,
  `RepeaterState`: keyed entries, `<name>_0001` names that are never reused, the fewest moved entries.
- `fill`, `fill_template`, `literal` and `Expression.canonical` / `Template.canonical`: TEL's Python
  form, for building expression text from Python values and comparing two spellings.
- `compile_template` always returns a `Template` (`is_text` for plain text).

### Safety

- A host object may be carried in a scope and its attributes read; nothing may call its methods,
  also not through a list that holds it (`sum`, `sorted`, `==`, `in`, `str`, text).
- An escape corpus (233 lines, every line refused by every entry point), a Hypothesis fuzzer and
  a removal check of more than 500 deliberate breakages, each of which a test must catch.
- `docs/security-review.md` says what is protected, how it is checked and what is not guaranteed.

### Known gaps

- A compiled expression keeps about 0.5 to 0.75 times the memory of the `expr.py` it replaces, not the
  0.5 asked for (`docs/benchmarks.md`, step 8).
- Not run on a free-threaded Python build.
