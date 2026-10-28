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


#: Every `DISALLOWED` case that is refused when the text is read, with its code.
PARSE_REFUSED = {
    "lambda: 1": "disallowed-construct",
    "(y := 1)": "disallowed-construct",
    "x if": "syntax-error",
    "await x": "disallowed-construct",
    "x & 1": "disallowed-construct",
    "x | 1": "disallowed-construct",
    "x ^ 1": "disallowed-construct",
    "x << 1": "disallowed-construct",
    "x >> 1": "disallowed-construct",
    "~x": "disallowed-construct",
    "x @ x": "disallowed-construct",
    "b'x'": "constant-type",
    "1j": "constant-type",
    "...": "constant-type",
    "{**d}": "dict-unpack",
    "f(**d)": "call-unpack",
    "len(**d)": "call-unpack",
    "x is 3": "is-operand",
    "x is x": "is-operand",
    "x is not 'a'": "is-operand",
    "[i async for i in x]": "comprehension-async",
    "[x for x[0] in items]": "comprehension-target",
    "(1)(2)": "call-target",
    "items[0](1)": "call-target",
    "_x": "private-name",
    "x._y": "private-attribute",
    "x.__class__": "private-attribute",
    "__builtins__": "private-name",
    "open('f')": "call-not-function",
    "eval('1')": "call-not-function",
    "exec('1')": "call-not-function",
    "getattr(x, 'a')": "call-not-function",
    "type(x)": "call-not-function",
    "globals()": "call-not-function",
    "print(1)": "call-not-function",
    "name.format()": "method-format",
    "name.format_map({})": "method-format",
    "name.encode()": "method-not-available",
    "items.append(1)": "method-not-available",
    "items.pop()": "method-not-available",
    "d.update({})": "method-not-available",
    "d.pop('k')": "method-not-available",
    "items.sort()": "method-not-available",
    "(1).bit_length()": "method-not-available",
    "x +": "syntax-error",
    "": "empty-expression",
    "   ": "empty-expression",
    "1 2": "syntax-error",
    "x = 1": "syntax-error",
    "import os": "syntax-error",
}

#: The code TEL raises for each `ESCAPES` case, in the order of `cases.ESCAPES` (reviewed in
#: groups on 2026-10-28). The comment on each line is the start of the source it belongs to.
ESCAPE_CODES = [
    "private-attribute",  # '().__class__'
    "private-attribute",  # '().__class__.__bases__'
    "private-attribute",  # '().__class__.__bases__[0].__subclasses__()'
    "private-attribute",  # '[].__class__.__mro__'
    "private-attribute",  # "''.__class__.__mro__[1]"
    "private-attribute",  # 'x.__class__'
    "private-attribute",  # 'x.__dict__'
    "private-attribute",  # 'x.__globals__'
    "private-attribute",  # 'x.__init__.__globals__'
    "private-attribute",  # 'len.__self__'
    "private-attribute",  # 'len.__module__'
    "private-attribute",  # 'obj.__class__'
    "private-attribute",  # '(lambda: 1).__globals__'
    "private-attribute",  # 'trap.__class__'
    "private-attribute",  # 'trap.__dict__'
    "private-attribute",  # 'd.__class__'
    "private-attribute",  # 'items.__class__.__base__'
    "private-attribute",  # "x.__getattribute__('a')"
    "private-attribute",  # 'x.__reduce__()'
    "private-attribute",  # "''.join.__self__"
    "method-not-available",  # "__import__('os').system('true')"
    "private-name",  # '__builtins__'
    "private-name",  # "__builtins__['eval']"
    "private-name",  # '_'
    "private-name",  # '_x'
    "private-name",  # '__name__'
    "private-name",  # '__file__'
    "private-name",  # '_trap'
    "syntax-error",  # '().＿＿class＿＿'
    "syntax-error",  # "＿＿import＿＿('os')"
    "call-not-function",  # "ｅval('1')"
    "syntax-error",  # 'x.＿private'
    "call-not-function",  # "eval('1')"
    "call-not-function",  # "exec('x=1')"
    "call-not-function",  # "compile('1', 'a', 'eval')"
    "call-not-function",  # "open('/etc/passwd')"
    "call-not-function",  # 'input()'
    "call-not-function",  # 'breakpoint()'
    "call-not-function",  # 'help()'
    "call-not-function",  # 'exit()'
    "call-not-function",  # 'quit()'
    "call-not-function",  # "getattr(x, 'real')"
    "call-not-function",  # "setattr(x, 'a', 1)"
    "call-not-function",  # "delattr(x, 'a')"
    "call-not-function",  # "hasattr(x, 'a')"
    "call-not-function",  # 'vars()'
    "call-not-function",  # 'dir()'
    "call-not-function",  # 'globals()'
    "call-not-function",  # 'locals()'
    "call-not-function",  # 'type(x)'
    "call-not-function",  # "type('A', (), {})"
    "call-not-function",  # 'object()'
    "call-not-function",  # 'super()'
    "call-not-function",  # 'id(x)'
    "call-not-function",  # 'hash(x)'
    "call-not-function",  # 'callable(x)'
    "call-not-function",  # 'iter(x)'
    "call-not-function",  # 'next(x)'
    "call-not-function",  # 'print(x)'
    "call-not-function",  # "format(x, '')"
    "call-not-function",  # 'chr(65)'
    "call-not-function",  # "ord('a')"
    "call-not-function",  # 'hex(1)'
    "call-not-function",  # 'bytes(1)'
    "call-not-function",  # 'bytearray(1)'
    "call-not-function",  # "memoryview(b'')"
    "call-not-function",  # 'slice(1)'
    "call-not-function",  # 'property()'
    "call-not-function",  # 'staticmethod(len)'
    "call-not-function",  # 'frozenset()'
    "call-not-function",  # 'issubclass(int, int)'
    "isinstance-type",  # 'isinstance(x, object)'
    "isinstance-type",  # 'isinstance(x, type)'
    "isinstance-type",  # 'isinstance(x, (int, str))'
    "isinstance-type",  # 'isinstance(x, trap)'
    "method-format",  # "'{0.__class__}'.format(x)"
    "method-format",  # "'{x.__class__}'.format(x=x)"
    "method-format",  # "'{}'.format(x)"
    "percent-format",  # "'%s' % x"
    "percent-format",  # "'%(a)s' % {'a': 1}"
    "method-format",  # "'{0}'.format_map({})"
    "method-format",  # "'{0.__class__}'.format_map(x)"
    "private-attribute",  # "f'{x.__class__}'"
    "private-attribute",  # "f'{x!r:{x.__class__}}'"
    "call-not-function",  # 'f\'{__import__("os")}\''
    "call-target",  # "f'{(lambda: 1)()}'"
    "call-target",  # '(lambda: 1)()'
    "disallowed-construct",  # '[lambda: 1 for _ in [1]]'
    "no-attribute",  # '(x for x in [1]).gi_frame'
    "no-attribute",  # '(x for x in [1]).gi_frame.f_globals'
    "private-attribute",  # '[].__class__'
    "private-attribute",  # '[x for x in ().__class__.__mro__]'
    "private-attribute",  # '{k: v for k, v in x.__dict__.items()}'
    "private-attribute",  # '[c for c in ().__class__.__bases__[0].__subclasse
    "private-attribute",  # '(i for i in [1]).__next__()'
    "not-iterable",  # '[i for i in trap]'
    "value-not-plain",  # 'list(trap)'
    "value-not-plain",  # 'sorted(trap)'
    "value-not-plain",  # 'sum(trap)'
    "value-not-plain",  # 'dict(trap)'
    "not-iterable",  # '[*trap]'
    "not-iterable",  # '(*trap,)'
    "call-not-function",  # 'trap()'
    "method-not-available",  # 'trap.dangerous()'
    "attribute-is-method",  # 'trap.dangerous'
    "method-not-available",  # 'trap.x.y()'
    "method-not-available",  # 'obj.method()'
    "attribute-is-method",  # 'obj.method'
    "method-not-available",  # 'd.update({})'
    "method-not-available",  # 'items.append(1)'
    "method-not-available",  # 'items.extend([1])'
    "method-not-available",  # 'items.clear()'
    "method-not-available",  # 'items.pop()'
    "method-not-available",  # 'items.remove(1)'
    "method-not-available",  # 'items.sort()'
    "method-not-available",  # 'items.reverse()'
    "method-not-available",  # 'items.insert(0, 1)'
    "method-not-available",  # "d.pop('k')"
    "method-not-available",  # 'd.popitem()'
    "method-not-available",  # "d.setdefault('a', 1)"
    "method-not-available",  # 'd.clear()'
    "method-not-available",  # 'd.copy()'
    "method-not-available",  # 'name.encode()'
    "method-not-available",  # 'name.translate({})'
    "method-not-available",  # "name.maketrans('a', 'b')"
    "method-format",  # 'name.format()'
    "method-not-available",  # "name.partition('a')"
    "method-not-available",  # 'name.expandtabs()'
    "private-attribute",  # 'int.__call__(1)'
    "function-as-value",  # 'str.upper(name)'
    "method-not-available",  # "int.from_bytes(b'', 'big')"
    "method-not-available",  # '(1).bit_length()'
    "method-not-available",  # '(1.5).as_integer_ratio()'
    "no-attribute",  # 'x.real'
    "no-attribute",  # 'x.numerator'
    "no-attribute",  # 'x.imag'
    "no-attribute",  # 'True.real'
    "syntax-error",  # 'x = 1'
    "syntax-error",  # 'x += 1'
    "disallowed-construct",  # '(y := 1)'
    "syntax-error",  # 'import os'
    "syntax-error",  # 'from os import path'
    "syntax-error",  # 'del x'
    "syntax-error",  # 'pass'
    "syntax-error",  # 'raise ValueError'
    "syntax-error",  # 'assert x'
    "syntax-error",  # 'return x'
    "syntax-error",  # 'yield x'
    "disallowed-construct",  # 'await x'
    "syntax-error",  # 'async def f(): pass'
    "syntax-error",  # 'def f(): pass'
    "syntax-error",  # 'class A: pass'
    "syntax-error",  # 'with x: pass'
    "syntax-error",  # 'try: pass\nexcept: pass'
    "syntax-error",  # 'global x'
    "syntax-error",  # 'nonlocal x'
    "syntax-error",  # 'x; y'
    "syntax-error",  # 'x\ny'
    "call-not-function",  # 'print(x) if x else None'
    "disallowed-construct",  # 'x & 1'
    "disallowed-construct",  # 'x | 1'
    "disallowed-construct",  # 'x ^ 1'
    "disallowed-construct",  # 'x << 1'
    "disallowed-construct",  # 'x >> 1'
    "disallowed-construct",  # '~x'
    "disallowed-construct",  # 'x @ x'
    "syntax-error",  # 'x if x else y if'
    "syntax-error",  # '*x'
    "syntax-error",  # '**x'
    "syntax-error",  # 'x ** '
    "syntax-error",  # '[*]'
    "dict-unpack",  # '{**x}'
    "call-unpack",  # 'f(**x)'
    "bad-index",  # "d['__class__']"
    "private-attribute",  # 'x.__class__ if x else 0'
    "private-attribute",  # 'name.__getitem__(0)'
    "unknown-name",  # 'getattr'
    "bad-index",  # "x['__class__']"
    "limit-sequence",  # "'a' * 10**9"
    "limit-sequence",  # '[0] * 10**9'
    "limit-pow-exponent",  # '10 ** 10 ** 10'
    "limit-pow-exponent",  # '9 ** 9 ** 9'
    "limit-pow-exponent",  # '2 ** 100000'
    "limit-range",  # 'range(10**12)'
    "limit-range",  # 'list(range(10**7))'
    "limit-range",  # 'sum(range(10**7))'
    "limit-string",  # "'x'.zfill(10**9)"
    "limit-string",  # "'x'.center(10**9)"
    "limit-string",  # "'x'.ljust(10**9)"
    "limit-range",  # '[i for i in range(10**6)]'
    "limit-steps",  # '[0 for a in range(1000) for b in range(1000)]'
    "limit-depth",  # '(((((((((((((((((((((((((((((((((((((((((((((((((
    "limit-depth",  # '[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[
    "limit-source",  # '-------------------------------------------------
    "limit-source",  # 'x + x + x + x + x + x + x + x + x + x + x + x + x
    "limit-source",  # "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    "limit-source",  # 'not not not not not not not not not not not not n
    "syntax-error",  # '1 if 1 if 1 if 1 if 1 if 1 if 1 if 1 if 1 if 1 if
]
