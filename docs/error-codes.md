# Error codes

Every error TEL raises has a `code`: a short stable identifier. Match on the code, never on the
message. A test (`tests/test_error_codes.py`) keeps this page and the source in step: a code that is
raised but not listed here, or listed and never raised, fails it.

## `TelSyntaxError`: the text is not valid, or is not allowed

| Code | When |
|---|---|
| `empty-expression` | The text is empty or only whitespace. |
| `syntax-error` | Python cannot read the text as one expression. If the text is valid as statements, the hint says TEL has none. |
| `invalid-text` | The text contains a null byte or a lone surrogate. |
| `disallowed-construct` | A construct that is not in the language: `lambda`, `:=`, `await`, `yield`, `& \| ^ << >> ~ @`, a t-string, or any syntax-tree node not on the whitelist. |
| `constant-type` | A constant that is not `None`, `bool`, `int`, `float` or `str`: bytes, complex, `...`. |
| `private-name` | A name, loop variable or argument name starting with `_` (except `_` as a loop variable). |
| `private-attribute` | An attribute starting with `_`. |
| `is-operand` | `is` or `is not` compared with anything but `None`, `True` or `False`. |
| `dict-unpack` | `**` in a dict display. |
| `call-unpack` | `**` in a call. |
| `call-target` | A call whose callee is not a name or `value.method`. |
| `call-not-function` | A call to a name that is not a built-in function (or a function the host allowed), or to a comprehension variable. |
| `method-format` | `format` or `format_map` (a format string can read attributes). |
| `method-not-available` | A method that is not on the whitelist, such as `append`, `pop`, `update`. |
| `isinstance-type` | `isinstance` with anything but one of `str int float bool list dict` as its second argument. |
| `comprehension-async` | An `async` comprehension. |
| `comprehension-target` | A comprehension loop variable that is not a name or names in a tuple. |

## `TelEvaluationError`: the expression could not be evaluated in this scope

Messages name types and names, never values from the scope.

| Code | When |
|---|---|
| `unknown-name` | A name is not in the scope (and is not a built-in being called). The hint suggests the nearest name. |
| `function-as-value` | A built-in function's name is read as a value (`len`, not `len(x)`). |
| `value-not-plain` | An object that is not a plain value is used in an operator, a comparison, a subscript or index, text, a set or dict key, or a function or method argument. |
| `bad-operand` | An operator, sign or `**` that cannot take these types, or a result that is not a real number. |
| `bad-comparison` | `<`, `<=`, `>` or `>=` between types that cannot be ordered. |
| `percent-format` | `%` on text; use an f-string. |
| `division-by-zero` | `/`, `//`, `%` or `**` by zero. |
| `number-too-large` | A number too large for the operation (for example an integer division result that does not fit a float). |
| `no-attribute` | An object or plain value has no readable attribute with that name. |
| `no-key` | A mapping read by attribute has no such key. |
| `attribute-is-method` | An attribute that is a method (or a callable) is read as a value. |
| `attribute-denied` | Reading an attribute of, or indexing, a module, class, function or similar. |
| `attribute-failed` | The host's own property raised while being read. |
| `bad-index` | An index or slice that does not fit the value. |
| `bad-key` | A dict key or set member that cannot be hashed. |
| `not-iterable` | A loop, spread or membership test over something that is not a text, list, tuple, dict, set or range. |
| `bad-unpack` | A loop target with a different number of names than the item has values. |
| `bad-call` | A built-in function or method failed, or was given arguments it cannot take. |
| `method-not-for-type` | A method called on a value that does not have it in TEL (for example `.upper()` on a number). |
| `bad-format` | An f-string format spec that does not fit the value. |

## `TelLimitError`: a limit was exceeded

| Code | When |
|---|---|
| `limit-source` | The text is longer than `max_source`. |
| `limit-depth` | The syntax tree is nested deeper than `max_depth`, or is too deep for Python to read. |
| `limit-nodes` | The syntax tree has more than `max_nodes` nodes. |
| `limit-steps` | An evaluation took more than `max_steps` steps. |
| `limit-range` | A `range` is longer than `max_range`. |
| `limit-sequence` | A repeated or joined sequence is longer than `max_sequence`. |
| `limit-pow-exponent` | A `**` exponent is over `max_pow_exponent`. A constant exponent is refused when the text is read. |
| `limit-int-bits` | An integer, written or computed, is over `max_int_bits` bits. |
| `limit-string` | A string, written or computed, is over `max_string` characters. |

## `TelVersionError`: the language version

| Code | When |
|---|---|
| `unsupported-language` | The version is text but not one this release supports. |
| `language-not-text` | The version is not text. YAML reads an unquoted `0.1` as a number. |
