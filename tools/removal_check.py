#!/usr/bin/env python3
"""The removal check: break each rule of the language on purpose and see that a test fails.

    python tools/removal_check.py [--list] [--group GROUP]... [--only TEXT]...

`sandbox-escape-review` asks that every rule has a test that fails if the rule is removed. This is
that proof, repeatable: each `Rule` is one deliberate breakage (a condition made `False`, a check
dropped, a limit off by one), applied to a source file, tested, and undone. A rule whose breakage
leaves the tests green is a SURVIVOR: either the rule is untested, or it is redundant (then remove
the rule). Exit status 1 if any rule survives or its pattern is stale (the code moved under it).

The tests run under a 2 GB address-space limit, because removing a size check lets the test that
guards it try to build a text of a billion characters. A source file with uncommitted changes is
refused, so the original is always one `git checkout` away; the file is restored from memory after
every rule as well. Run it with the project's venv python.

GROUPS name the code and the tests that must catch it:

    parser     the whitelist, names, attributes, calls, constants, limits of the text
    evaluator  the value rules, sizes, the step budget, comprehensions, calls, formatting
    template   the reader for `{{ }}` parts and the template's evaluation
    api        what a host that passes the wrong thing is told
"""

import argparse
import os
import resource
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Rule:
    path: str  # the source file to break
    old: str  # the text to replace; it must occur exactly once, or `nth` says which occurrence
    new: str  # what to put there
    what: str  # what the breakage means, in words
    nth: int | None = None  # the n-th (0-based) line holding `old`, when `old` is on several lines


TESTS = {
    "parser": ["tests/test_parser.py", "tests/test_error_codes.py", "tests/test_errors.py"],
    "evaluator": ["tests/test_evaluator.py", "tests/test_evaluator_limits.py"],
    "template": ["tests/test_template.py", "tests/test_evaluator_limits.py"],
}

RULES: dict[str, list[Rule]] = {
    "parser": [
        Rule(
            "src/tel/_parser.py",
            "if len(source) > limits.max_source:",
            "if len(source) >= limits.max_source:",
            "source limit off by one",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "    _check_text(text, here)\n",
            "    pass\n",
            "null bytes and surrogates not checked",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            '        warnings.simplefilter("ignore")\n        return ast.parse(text, mode="eval")',
            '        return ast.parse(text, mode="eval")',
            "warnings not suppressed",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            '            warnings.simplefilter("ignore")\n            ast.parse(text, mode="exec")',
            '            ast.parse(text, mode="exec")',
            "warnings in the statement hint not suppressed",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            'if message.startswith("too many nested parentheses"):',
            "if False:",
            "deep parentheses not a limit",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            'if "integer string conversion" in message:',
            "if False:",
            "huge digit string not a limit",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "if depth > self.limits.max_depth:",
            "if depth >= self.limits.max_depth:",
            "depth off by one",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "if self.nodes > self.limits.max_nodes:",
            "if self.nodes >= self.limits.max_nodes:",
            "nodes off by one",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "        if named is not None:",
            "        if False:",
            "nodes not refused by name",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "        elif kind in _PLAIN_NODES:\n            self.children(node, depth)\n        else:\n            raise self.refuse(node)",
            "        else:\n            self.children(node, depth)",
            "whitelist not enforced",
            None,
        ),
        Rule("src/tel/_parser.py", "        self.nodes += 1\n", "", "nodes not counted", None),
        Rule(
            "src/tel/_parser.py",
            '    if "\\x00" in text:',
            "    if False:",
            "null byte allowed",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "                if type(value) not in _SINGLETONS:",
            "                if True:",
            "singletons visited as nodes",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "if type(value) not in _PLAIN_CONSTANTS:",
            "if False:",
            "bytes/complex allowed",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "if type(value) is int and value.bit_length() > self.limits.max_int_bits:",
            "if False:",
            "big int literal allowed",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "if type(value) is str and len(value) > self.limits.max_string:",
            "if False:",
            "long string literal allowed",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            'if name.startswith("_") and not (name == "_" and self.is_bound("_")):',
            "if False:",
            "private names allowed",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            'if node.attr.startswith("_"):\n            raise self.private_attribute(node, node.attr)',
            "if False:\n            raise self.private_attribute(node, node.attr)",
            "private attributes allowed",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "if isinstance(op, ast.Is | ast.IsNot) and not (",
            "if False and not (",
            "is with anything allowed",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            '            if key is None:\n                raise self.fail(value, "dict-unpack"',
            '            if False:\n                raise self.fail(value, "dict-unpack"',
            "dict ** allowed",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "and right.value > self.limits.max_pow_exponent",
            "and right.value >= self.limits.max_pow_exponent",
            "exponent off by one",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "            if keyword.arg is None:",
            "            if False:",
            "call ** allowed",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            '            if keyword.arg.startswith("_"):',
            "            if False:",
            "private keyword allowed",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "            if bound or func.id not in self.functions:",
            "            if func.id not in self.functions:",
            "comprehension variable callable",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "            if bound or func.id not in self.functions:",
            "            if bound:",
            "any name callable",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "            if func.attr in FORMAT_METHODS:",
            "            if False:",
            "format gets no reason of its own",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "            if func.attr not in METHOD_NAMES:",
            "            if False:",
            "any method callable",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            '            raise self.fail(node, "call-target", "only a function or method can be called")',
            "            pass",
            "any callee allowed",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "            and not self.is_bound(args[1].id)\n",
            "",
            "shadowed isinstance type accepted",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "            len(args) == 2\n",
            "            len(args) >= 1\n",
            "isinstance arity not checked",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "            and args[1].id in ISINSTANCE_TYPES",
            "",
            "any isinstance type accepted",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            '            if target.id.startswith("_") and target.id != "_":',
            "            if False:",
            "private loop variable allowed",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "        if node.is_async:",
            "        if False:",
            "async comprehension allowed",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "        self._bound[-1] |= self._targets(node.target)",
            "        self._targets(node.target)",
            "comprehension targets not bound",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "        self.visit(node.iter, depth + 1)  # sees the names bound before this generator, not its own\n        self._bound[-1] |= self._targets(node.target)\n",
            "        self._bound[-1] |= self._targets(node.target)\n        self.visit(node.iter, depth + 1)\n",
            "iterable sees its own target",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "        if not self.is_bound(name):\n            self.names.add(name)",
            "        self.names.add(name)",
            "bound names counted as free",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "        hint = _STATEMENT_WORDS",
            "        hint = None",
            "statement hint dropped",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "    here = origin.advance(lead) if origin is not None else None",
            "    here = origin",
            "origin not moved past leading space",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "    text = source.strip()",
            "    text = source",
            "text not stripped",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "        raise _too_deep(text, here, limits) from None\n    assert",
            "        raise\n    assert",
            "recursion not a limit error",
            None,
        ),
        Rule(
            "src/tel/_whitelist.py",
            "    ast.Starred,\n)",
            "    ast.Starred, ast.Lambda,\n)",
            "lambda allowed",
            None,
        ),
        Rule("src/tel/_whitelist.py", "isinstance clamp", "isinstance", "clamp dropped", None),
        Rule(
            "src/tel/_whitelist.py",
            'ISINSTANCE_TYPES: frozenset[str] = frozenset("str int float bool list dict"',
            'ISINSTANCE_TYPES: frozenset[str] = frozenset("str int float bool list dict object"',
            "object accepted by isinstance",
            None,
        ),
        Rule(
            "src/tel/_whitelist.py",
            "    replace find count",
            "    append replace find count",
            "append callable",
            None,
        ),
        Rule(
            "src/tel/_whitelist.py",
            '    ast.YieldFrom: "yield",\n',
            "",
            "yield from not named",
            None,
        ),
    ],
    "evaluator": [
        Rule(
            "src/tel/_compiler.py",
            "charge(S, R, pos, size * per)",
            "charge(S, R, pos, 0)",
            "loop cost not charged",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if size > S.limits.max_sequence:",
            "if False:",
            "sequence size of iterated values",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if len(text) > S.limits.max_string:",
            "if False:",
            "check_string off",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if number.bit_length() > S.limits.max_int_bits:",
            "if False:",
            "check_int off",
            None,
        ),
        Rule(
            "src/tel/_compiler.py", "if not inert(a):", "if False:", "left operand not checked", 0
        ),
        Rule(
            "src/tel/_compiler.py", "if not inert(b):", "if False:", "right operand not checked", 0
        ),
        Rule(
            "src/tel/_compiler.py",
            "if op is ast.Mod and isinstance(a, str):",
            "if False:",
            "percent formatting allowed",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if abs(b) > limits.max_pow_exponent:",
            "if abs(b) >= limits.max_pow_exponent:",
            "exponent off by one",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if abs(b) > limits.max_pow_exponent:",
            "if False:",
            "runtime exponent unchecked",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "abs(b) * math.log2(abs(a) or 1) > limits.max_int_bits:",
            "False:",
            "power size unchecked",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if size > limits.max_sequence:",
            "if False:",
            "repeat size unchecked",
            0,
        ),
        Rule(
            "src/tel/_compiler.py",
            "charge(S, R, pos, size >> 6)",
            "charge(S, R, pos, 0)",
            "repeat not charged",
            0,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if size > limits.max_sequence:",
            "if False:",
            "join size unchecked",
            1,
        ),
        Rule(
            "src/tel/_compiler.py",
            "charge(S, R, pos, size >> 6)",
            "charge(S, R, pos, 0)",
            "concatenation not charged",
            1,
        ),
        Rule(
            "src/tel/_compiler.py",
            "except ZeroDivisionError:",
            "except KeyError:",
            "division by zero leaks",
            None,
        ),
        Rule(
            "src/tel/_compiler.py", "except OverflowError:", "except KeyError:", "overflow leaks", 0
        ),
        Rule(
            "src/tel/_compiler.py",
            "if type(result) is int:",
            "if False:",
            "int result unchecked",
            0,
        ),
        Rule(
            "src/tel/_compiler.py",
            "elif type(result) is str:",
            "elif False:",
            "str result unchecked",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "elif type(result) is complex:",
            "elif False:",
            "complex result allowed",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if op is ast.Is or op is ast.IsNot:",
            "if False:",
            "is asks the value",
            None,
        ),
        Rule(
            "src/tel/_compiler.py", "if not inert(a):", "if False:", "comparison left unchecked", 0
        ),
        Rule(
            "src/tel/_compiler.py", "if not inert(b):", "if False:", "comparison right unchecked", 0
        ),
        Rule(
            "src/tel/_compiler.py",
            "except TypeError:",
            "except KeyError:",
            "comparison type error leaks",
            0,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if isinstance(base, Mapping):",
            "if False:",
            "mapping attributes",
            0,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if isinstance(base, DENIED_BASES):",
            "if False:",
            "denied bases readable",
            0,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if isinstance(base, PRIMITIVES):",
            "if False:",
            "primitive attributes readable",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if callable(getattr(type(base), name, None)):",
            "if False:",
            "method hint lost",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if callable(value):",
            "if False:",
            "callable attribute returned",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if isinstance(base, DENIED_BASES):",
            "if False:",
            "indexing denied bases",
            0,
        ),
        Rule(
            "src/tel/_compiler.py", "if not inert(base):", "if False:", "index base unchecked", None
        ),
        Rule(
            "src/tel/_compiler.py",
            "if not inert(index) and type(index) is not slice:",
            "if False:",
            "index unchecked",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if isinstance(base, Mapping):",
            "if False:",
            "mapping methods",
            0,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if not inert(value):",
            "if False:",
            "call arguments unchecked",
            0,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if name not in allowed:",
            "if False:",
            "any method on a value",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            'elif name == "join" and args:',
            "elif False:",
            "join not checked",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if isinstance(result, _VIEWS):",
            "if False:",
            "dict views returned",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "check_string(S, pos, result)",
            "pass",
            "method result unchecked",
            1,
        ),
        Rule(
            "src/tel/_compiler.py",
            "charge(S, R, pos, len(result) >> 6)",
            "pass",
            "method result not charged",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if name in ITERATING:",
            "if False:",
            "iterating built-ins not charged",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "check_string(S, pos, result)",
            "pass",
            "built-in str result unchecked",
            1,
        ),
        Rule(
            "src/tel/_compiler.py",
            "check_int(S, pos, result)",
            "pass",
            "built-in int result unchecked",
            1,
        ),
        Rule(
            "src/tel/_compiler.py",
            "except OverflowError:",
            "except KeyError:",
            "huge range leaks",
            1,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if size > S.limits.max_range:",
            "if False:",
            "range size unchecked",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if len(run) > 9 or int(run) > S.limits.max_string:",
            "if False:",
            "format spec width unchecked",
            None,
        ),
        Rule(
            "src/tel/_compiler.py", "if not inert(value):", "if False:", "format value unchecked", 0
        ),
        Rule("src/tel/_compiler.py", "elif conversion == 114:", "elif False:", "!r ignored", None),
        Rule("src/tel/_compiler.py", "elif conversion == 97:", "elif False:", "!a ignored", None),
        Rule(
            "src/tel/_compiler.py",
            "return not truthy(operand(L, R))",
            "return not operand(L, R)",
            "not asks the value",
            None,
        ),
        Rule("src/tel/_compiler.py", "if not inert(value):", "if False:", "sign unchecked", 1),
        Rule(
            "src/tel/_compiler.py",
            "except TypeError:",
            "except KeyError:",
            "sign type error leaks",
            1,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if truthy(result) != is_and:",
            "if bool(result) != is_and:",
            "and/or ask the value",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "return body(L, R) if truthy(test(L, R)) else orelse(L, R)",
            "return body(L, R) if test(L, R) else orelse(L, R)",
            "if asks the value",
            None,
        ),
        Rule("src/tel/_compiler.py", "measure(S, R, pos, value)", "pass", "spread unchecked", 1),
        Rule(
            "src/tel/_compiler.py", "if not inert(item):", "if False:", "set member unchecked", None
        ),
        Rule(
            "src/tel/_compiler.py",
            "except TypeError:",
            "except KeyError:",
            "unhashable set member leaks",
            1,
        ),
        Rule("src/tel/_compiler.py", "if not inert(k):", "if False:", "dict key unchecked", 0),
        Rule(
            "src/tel/_compiler.py",
            "except TypeError:",
            "except KeyError:",
            "unhashable key leaks",
            1,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if total > limit:",
            "if False:",
            "f-string total unchecked",
            None,
        ),
        Rule("src/tel/_compiler.py", "measure(S, R, pos, item)", "pass", "unpack unchecked", None),
        Rule(
            "src/tel/_compiler.py",
            "if len(values) != len(inner):",
            "if False:",
            "unpack count unchecked",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "measure(S, R, pos, source, cost)  # the whole loop is paid for before it starts",
            "pass",
            "loops not charged",
            0,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if not truthy(condition(L, R)):",
            "if False:",
            "loop conditions ignored",
            0,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if not inert(value):",
            "if False:",
            "set comprehension unchecked",
            2,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if not inert(k):",
            "if False:",
            "dict comprehension key unchecked",
            0,
        ),
        Rule(
            "src/tel/_compiler.py",
            "measure(S, R, pos, value)",
            "pass",
            "argument spread unchecked",
            1,
        ),
        Rule(
            "src/tel/_compiler.py",
            "and args[0] > limits.max_string:",
            "and False:",
            "width methods unchecked",
            None,
        ),
        Rule(
            "src/tel/_compiler.py", 'if name == "replace":', "if False:", "replace unchecked", None
        ),
        Rule("src/tel/_compiler.py", "R.steps += steps", "pass", "charge does nothing", None),
        Rule(
            "src/tel/_compiler.py",
            "if ta is type(b) and (ta is int or ta is float or ta is str):",
            "if True:",
            "plain comparison unchecked",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "                if not compare_pair(S, pos, op, a, b):\n                    return False",
            "                if not b:\n                    return False",
            "chained comparison unchecked",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "            measure(S, R, pos, source, cost)  # the whole loop is paid for before it starts\n            slots = R.slots\n            out: list[Any] = []",
            "            slots = R.slots\n            out: list[Any] = []",
            "simple comprehension not charged",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "                        if not truthy(condition(L, R)):\n                            break\n                    else:\n                        append(element(L, R))",
            "                        if False:\n                            break\n                    else:\n                        append(element(L, R))",
            "simple comprehension ignores conditions",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "                check_format_spec(S, pos, text)",
            "                pass",
            "static format spec unchecked",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "    if spec and not checked:",
            "    if False:",
            "dynamic format spec unchecked",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "            raise unknown_name(S, name_pos, R, name) from None\n        ta = type(a)\n        if ta is int or ta is float:",
            "            raise KeyError(name) from None\n        ta = type(a)\n        if ta is int or ta is float:",
            "inline name unknown error leaks",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "        if ta is type(k) or (ta is int or ta is float) and type(k) is not str:\n            return fn(a, k)\n        return compare_pair(S, pos, op, a, k)\n\n    return with_constant",
            "        if True:\n            return fn(a, k)\n        return compare_pair(S, pos, op, a, k)\n\n    return with_constant",
            "inline compare unchecked",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "                    return call_method(S, R, pos, value, name, [f(L, R) for f in fns], _NO_KWARGS)",
            "                    return call_method(S, R, pos, value, name, [f(L, R) for f in fns[:0]], _NO_KWARGS)",
            "plain method arguments dropped",
            None,
        ),
        Rule(
            "src/tel/expression.py",
            "run.slots = [None] * self._slots",
            "run.slots = [None]",
            "too few loop slots",
            None,
        ),
        Rule(
            "src/tel/expression.py",
            "        except RecursionError:\n            raise self._too_deep() from None\n\n    def _run",
            "        except KeyError:\n            raise self._too_deep() from None\n\n    def _run",
            "stack overflow at evaluation leaks",
            None,
        ),
        Rule(
            "src/tel/expression.py",
            "    check_language(language)\n",
            "",
            "language not checked",
            None,
        ),
        Rule(
            "src/tel/_values.py",
            "        return bool(value)\n    return True",
            "        return bool(value)\n    return bool(value)",
            "truthy asks every value",
            None,
        ),
        Rule(
            "src/tel/_builtins.py",
            "return max(low, min(high, x))",
            "return min(low, max(high, x))",
            "clamp reversed",
            None,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if type(result) is int and result.bit_length() > S.limits.max_int_bits:",
            "if False:",
            "fast path int unchecked 0",
            0,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if type(result) is int and result.bit_length() > S.limits.max_int_bits:",
            "if False:",
            "fast path int unchecked 1",
            1,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if type(result) is int and result.bit_length() > S.limits.max_int_bits:",
            "if False:",
            "fast path int unchecked 2",
            2,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if ta is int or ta is float:",
            "if True:",
            "number fast path unchecked 0",
            0,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if ta is int or ta is float:",
            "if True:",
            "number fast path unchecked 1",
            1,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if ta is type(k) or (ta is int or ta is float) and type(k) is not str:",
            "if True:",
            "constant comparison unchecked 0",
            0,
        ),
        Rule(
            "src/tel/_compiler.py",
            "if ta is type(k) or (ta is int or ta is float) and type(k) is not str:",
            "if True:",
            "constant comparison unchecked 1",
            1,
        ),
    ],
    "template": [
        Rule(
            "src/tel/template.py",
            "    if _OPEN not in text:\n        return None",
            "    if False:\n        return None",
            "plain text is a template",
            None,
        ),
        Rule(
            "src/tel/template.py",
            "    if len(text) > limits.max_source:",
            "    if False:",
            "whole text not limited",
            None,
        ),
        Rule(
            "src/tel/template.py",
            '        if end < 0:\n            raise _error(text, origin, start, "template-unclosed"',
            '        if False:\n            raise _error(text, origin, start, "template-unclosed"',
            "unclosed not detected",
            None,
        ),
        Rule(
            "src/tel/template.py",
            "        if not text[body:end].strip():",
            "        if False:",
            "empty part not detected",
            None,
        ),
        Rule(
            "src/tel/template.py",
            "            while end >= 0 and not reads_as_expression(text[body:end]):",
            "            while False:",
            "first }} always ends a part",
            None,
        ),
        Rule(
            "src/tel/template.py",
            "                end = text.find(_CLOSE, end + 1)  # overlapping",
            "                end = text.find(_CLOSE, end + 2)  # overlapping",
            "overlapping endings missed",
            None,
        ),
        Rule(
            "src/tel/template.py",
            "        if _HIDING.search(text, body, end):",
            "        if False:",
            "no trial parse ever",
            None,
        ),
        Rule(
            "src/tel/template.py",
            "        if end < 0:\n            end = first",
            "        if end < 0:\n            end = end",
            "own syntax error not reported",
            None,
        ),
        Rule(
            "src/tel/template.py",
            "            placed = start.advance(text[:index])",
            "            placed = start",
            "parts not placed after the text before them",
            None,
        ),
        Rule(
            "src/tel/template.py",
            "    start = origin if origin is not None else Origin()",
            "    start = origin if origin is not None else None",
            "no positions without an origin",
            None,
        ),
        Rule(
            "src/tel/template.py",
            "    if not inert(value):\n        raise TelEvaluationError(",
            "    if False:\n        raise TelEvaluationError(",
            "objects put in text",
            None,
        ),
        Rule(
            "src/tel/template.py",
            "            if total > limit:",
            "            if False:",
            "text not limited",
            None,
        ),
        Rule(
            "src/tel/template.py",
            "        only = parts[0] if len(parts) == 1 and isinstance(parts[0], Expression) else None",
            "        only = None",
            "a lone part loses its type",
            None,
        ),
        Rule(
            "src/tel/template.py",
            "                    value = part._fn(lookup, run)",
            "                    value = part.evaluate(scope)",
            "parts do not share a budget",
            None,
        ),
        Rule(
            "src/tel/template.py",
            "                    if part._slots:\n                        run.slots = [None] * part._slots",
            "                    if False:\n                        run.slots = None",
            "parts get no loop slots",
            None,
        ),
        Rule(
            "src/tel/template.py",
            '                    elif value is None:\n                        text = ""',
            "                    elif value is None:\n                        text = str(value)",
            "None is not nothing in the loop",
            None,
        ),
        Rule(
            "src/tel/template.py",
            "        return frozenset().union(*(p.names for p in self._parts if isinstance(p, Expression)))",
            "        return frozenset()",
            "names not collected",
            None,
        ),
        Rule(
            "src/tel/template.py",
            "        run.scope = scope\n        try:\n            lookup = scope.lookup",
            "        run.scope = None\n        try:\n            lookup = scope.lookup",
            "scope not given to the run",
            None,
        ),
        Rule(
            "src/tel/_parser.py",
            "    except SyntaxError, ValueError, RecursionError, MemoryError:\n        return False\n    return True",
            "    except KeyError:\n        return False\n    return True",
            "unreadable part crashes",
            None,
        ),
        Rule(
            "src/tel/expression.py",
            "        run.slots = [None] * self._slots if self._slots else None",
            "        run.slots = None",
            "no loop slots in a shared run",
            None,
        ),
    ],
}


TESTS["api"] = ["tests/test_api_misuse.py"]
_A, _E, _T, _C = (
    "src/tel/_arguments.py",
    "src/tel/expression.py",
    "src/tel/template.py",
    "src/tel/_compiler.py",
)
RULES["api"] = [
    Rule(
        _A,
        "    if issubclass(type(value), str):\n        return str.__str__(value)",
        "    if issubclass(type(value), str):\n        return value",
        "a str subclass is used as it is",
    ),
    Rule(
        _A,
        "    if issubclass(type(value), str):\n        return str.__str__(value)\n    raise TypeError",
        "    if True:\n        return str.__str__(value)\n    raise TypeError",
        "a non-str is not named",
    ),
    Rule(_A, "    if not isinstance(limits, Limits):", "    if False:", "limits are not checked"),
    Rule(
        _A,
        "    if origin is not None and not isinstance(origin, Origin):",
        "    if False:",
        "origin is not checked",
    ),
    Rule(
        _E,
        "    source, limits, origin = as_text(source), check_limits(limits), check_origin(origin)\n",
        "",
        "expression arguments are not checked",
    ),
    Rule(
        _T,
        "    text, limits, origin = as_text(text), check_limits(limits), check_origin(origin)\n",
        "",
        "template arguments are not checked",
    ),
    Rule(
        _E,
        "        except AttributeError:\n            raise no_lookup() from None\n        return self._fn(lookup, run)",
        "        except KeyError:\n            raise no_lookup() from None\n        return self._fn(lookup, run)",
        "a scope without lookup (expression)",
    ),
    Rule(
        _T,
        "        except AttributeError:\n            raise no_lookup() from None\n        if self._single",
        "        except KeyError:\n            raise no_lookup() from None\n        if self._single",
        "a scope without lookup (template)",
    ),
    Rule(
        _C,
        "        except Exception:\n            known = []",
        "        except KeyError:\n            known = []",
        "a failing names() hides the error",
    ),
    Rule(_E, "    def __copy__(self)", "    def _copy_(self)", "an Expression is not its own copy"),
    Rule(
        _E,
        "    def __deepcopy__(self, memo: Any)",
        "    def _deepcopy_(self, memo: Any)",
        "an Expression is not its own deep copy",
    ),
    Rule(
        _E,
        "    def __reduce__(self)",
        "    def _reduce_(self)",
        "an Expression pickling error is not explained",
    ),
    Rule(_T, "    def __copy__(self)", "    def _copy_(self)", "a Template is not its own copy"),
    Rule(
        _T,
        "    def __deepcopy__(self, memo: Any)",
        "    def _deepcopy_(self, memo: Any)",
        "a Template is not its own deep copy",
    ),
    Rule(
        _T,
        "    def __reduce__(self)",
        "    def _reduce_(self)",
        "a Template pickling error is not explained",
    ),
]


def apply(text: str, rule: Rule) -> str | None:
    """`text` with the rule's breakage applied, or None if the pattern is not (uniquely) there."""
    if rule.nth is None:
        return text.replace(rule.old, rule.new) if text.count(rule.old) == 1 else None
    lines = text.split("\n")
    hits = [i for i, line in enumerate(lines) if rule.old in line]
    if rule.nth >= len(hits):
        return None
    lines[hits[rule.nth]] = lines[hits[rule.nth]].replace(rule.old, rule.new, 1)
    return "\n".join(lines)


def memory_cap() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))


def tracked_and_clean(path: str) -> bool:
    """Whether git knows the file and it has no uncommitted change."""
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", path], cwd=ROOT, capture_output=True
    )
    clean = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", path], cwd=ROOT)
    return tracked.returncode == 0 and clean.returncode == 0


def caught(group: str) -> bool:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPYCACHEPREFIX=tempfile.mkdtemp())
    command = [
        sys.executable,
        "-B",
        "-m",
        "pytest",
        "-q",
        "-x",
        "-p",
        "no:cacheprovider",
        *TESTS[group],
    ]
    try:
        done = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            preexec_fn=memory_cap,
        )
    except subprocess.TimeoutExpired:
        return True  # a hang is a failure of the test run, which is what a breakage should cause
    return done.returncode != 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--list", action="store_true", help="list the rules and stop")
    parser.add_argument("--group", action="append", choices=sorted(RULES), help="only this group")
    parser.add_argument(
        "--only", action="append", help="only rules whose description contains this"
    )
    args = parser.parse_args(argv)
    problems: list[str] = []
    total = 0
    for group, rules in RULES.items():
        if args.group and group not in args.group:
            continue
        for rule in rules:
            if args.only and not any(o in rule.what for o in args.only):
                continue
            total += 1
            if args.list:
                print(f"{group:<10} {rule.path:<22} {rule.what}")
                continue
            if not tracked_and_clean(rule.path):
                sys.exit(f"{rule.path} has uncommitted changes: commit or stash them first")
            path = ROOT / rule.path
            original = path.read_text()
            broken = apply(original, rule)
            if broken is None:
                print(
                    f"STALE     {group}: {rule.what}  (the pattern is not in {rule.path} any more)"
                )
                problems.append(f"stale: {rule.what}")
                continue
            try:
                path.write_text(broken)
                result = caught(group)
            finally:
                path.write_text(original)
            print(("caught   " if result else "SURVIVED ") + f"{group}: {rule.what}")
            if not result:
                problems.append(f"survived: {rule.what}")
    if args.list:
        print(f"{total} rules")
        return 0
    print(f"{total} rules checked; problems: {problems or 'none'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
