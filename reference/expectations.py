"""What TEL must do with the reference cases that `expr.py` decides differently or later.

The parser decides what it can from the text (`tests/test_parser.py`); these are the cases it
leaves to evaluation, each with the error code the evaluator must raise (`tests/test_evaluator.py`),
and the cases TEL deliberately refuses because it dropped the helper they use.
"""

#: `ALLOWED` cases that use helpers dropped from the core (decision B in `docs/language.md`).
DROPPED_HELPER_CASES = {
    "format_number(1234.5, 1)",
    "pluralize(1, 'item')",
    "pluralize(2, 'item')",
    "pluralize(2, 'child', 'children')",
}

#: Well-formed `DISALLOWED` cases that need a value to be refused.
EVALUATION_LEVEL = {
    "name % 3": "percent-format",
    "name.upper": "attribute-is-method",
    "print": "unknown-name",
    "sorted(items, key=len)": "function-as-value",
    "x.real": "no-attribute",
}

#: Well-formed `ESCAPES` that are refused when evaluated, reviewed one by one.
EVALUATION_LEVEL_ESCAPES = {
    # a value of the wrong kind: iteration, `%`, attributes, keys
    "'%s' % x": "percent-format",
    "'%(a)s' % {'a': 1}": "percent-format",
    "(x for x in [1]).gi_frame": "no-attribute",
    "(x for x in [1]).gi_frame.f_globals": "no-attribute",
    "[i for i in trap]": "not-iterable",
    "list(trap)": "value-not-plain",
    "sorted(trap)": "value-not-plain",
    "sum(trap)": "value-not-plain",
    "dict(trap)": "value-not-plain",
    "[*trap]": "not-iterable",
    "(*trap,)": "not-iterable",
    "trap.dangerous": "attribute-is-method",
    "obj.method": "attribute-is-method",
    "str.upper(name)": "function-as-value",
    "x.real": "no-attribute",
    "x.numerator": "no-attribute",
    "x.imag": "no-attribute",
    "True.real": "no-attribute",
    "d['__class__']": "bad-index",
    "x['__class__']": "bad-index",
    "getattr": "unknown-name",
    # sizes that only evaluation can see
    "'a' * 10**9": "limit-sequence",
    "[0] * 10**9": "limit-sequence",
    "10 ** 10 ** 10": "limit-pow-exponent",
    "9 ** 9 ** 9": "limit-pow-exponent",
    "range(10**12)": "limit-range",
    "list(range(10**7))": "limit-range",
    "sum(range(10**7))": "limit-range",
    "'x'.zfill(10**9)": "limit-string",
    "'x'.center(10**9)": "limit-string",
    "'x'.ljust(10**9)": "limit-string",
    "[i for i in range(10**6)]": "limit-range",
    "[0 for a in range(1000) for b in range(1000)]": "limit-steps",
}

#: `LIMIT_CASES` the parser can decide from the text.
PARSE_LEVEL_LIMITS = {
    "'x' * 2000": "limit-source",
    "[" * 45 + "]" * 45: "limit-depth",
    "[" + ",".join(["1"] * 1100) + "]": "limit-nodes",
    "2 ** 65": "limit-pow-exponent",
}

#: `LIMIT_CASES` enforced while evaluating.
EVALUATION_LEVEL_LIMITS = {
    "[x for x in range(100000)]": "limit-steps",
    "[x for x in range(10) for y in range(10) for z in range(10)]": "limit-steps",
    "range(100001)": "limit-range",
    "range(10**9)": "limit-range",
    "'a' * 1000001": "limit-sequence",
    "[0] * 2_000_000": "limit-sequence",
    "3 * 'ab' * 400000": "limit-sequence",
    "'a' * 600000 + 'b' * 600000": "limit-sequence",
    "10 ** 64 ** 2": "limit-pow-exponent",
    "9 ** 64 * 9 ** 64 * 9 ** 64 * 9 ** 64 * 9 ** 64 * 9 ** 64 * 9 ** 64 * 9 ** 64"
    " * 9 ** 64 * 9 ** 64 * 9 ** 64 * 9 ** 64": "limit-int-bits",
    'f\'{"a" * 600000}{"b" * 600000}\'': "limit-string",
    "'-'.join(['x' * 500000, 'y' * 600000])": "limit-string",
    "'x'.center(2000000)": "limit-string",
    "'x'.zfill(10**7)": "limit-string",
    "list(range(100000)) + list(range(100000)) + list(range(100000))": "limit-steps",
    "sum([[1]] * 500000, [])": "limit-steps",
}
