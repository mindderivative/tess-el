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
    tracking   which names an evaluation read, and the reads on an error
    host       the host's own functions and methods
    paths      attribute paths read by a tracked evaluation, and the static paths
    ternary    the `cond ? a : b` rewrite: pairing, f-string fields, positions mapped back
    condition  conditions and the `select` chain: truth, short-circuit, the reads of a chain
    repeater   the repeater header, the keys and the items of a list
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
            "            if func.attr not in self.method_names:",
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
            "    elif isinstance(result, str):\n        check_string(S, pos, result)\n        charge(S, R, pos, len(result) >> 6)",
            "    elif isinstance(result, str):\n        check_string(S, pos, result)",
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
            "    elif type(result) is int:\n        check_int(S, pos, result)\n    return result\n\n\ndef make_range",
            "    return result\n\n\ndef make_range",
            "built-in int result unchecked",
            None,
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
            "        except RecursionError:\n            raise self._too_deep() from None\n\n    def evaluate_tracked",
            "        except KeyError:\n            raise self._too_deep() from None\n\n    def evaluate_tracked",
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
            "    except _ternary.RewriteError, SyntaxError, ValueError, RecursionError, MemoryError:\n        return False\n    return True",
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
        "            except AttributeError:\n                raise no_lookup() from None\n        return self._fn(lookup, run)",
        "            except KeyError:\n                raise no_lookup() from None\n        return self._fn(lookup, run)",
        "a scope without lookup (expression)",
    ),
    Rule(
        _T,
        "        except AttributeError:\n            raise no_lookup() from None\n        return self._evaluate(run, lookup)",
        "        except KeyError:\n            raise no_lookup() from None\n        return self._evaluate(run, lookup)",
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


TESTS["tracking"] = ["tests/test_tracking.py"]
_X, _Tp = "src/tel/expression.py", "src/tel/template.py"
RULES["tracking"] = [
    Rule(
        _X,
        "            reads.add(name)\n            return lookup(name)",
        "            return lookup(name)",
        "expression: reads are not recorded",
    ),
    Rule(
        _X,
        "            reads.add(name)\n            return lookup(name)",
        "            r = lookup(name)\n            reads.add(name)\n            return r",
        "expression: a missing name is not recorded",
    ),
    Rule(
        _X,
        "        reads.add(name)\n        return lookup(name)",
        "        return lookup(name)",
        "template: reads are not recorded",
    ),
    Rule(
        _X,
        "        reads.add(name)\n        return lookup(name)",
        "        r = lookup(name)\n        reads.add(name)\n        return r",
        "template: a missing name is not recorded",
    ),
    Rule(
        _X,
        "        except TelError as error:\n            raise attach(error, reads) from None",
        "        except TelError as error:\n            raise",
        "expression: errors do not carry the reads",
    ),
    Rule(
        _X,
        "            raise attach(self._too_deep(), reads) from None",
        "            raise self._too_deep() from None",
        "expression: a stack overflow does not carry the reads",
    ),
    Rule(_X, "    error.reads = frozen\n", "", "attach: reads not set on the error"),
    Rule(
        _X,
        '    error._kwargs["reads"] = frozen\n',
        "",
        "attach: reads lost when the error is pickled",
    ),
    Rule(
        _X, "(value, frozenset(reads)))", "(value, reads))", "expression: reads is not a frozenset"
    ),
    Rule(
        _Tp, "(value, frozenset(reads)))", "(value, reads))", "template: reads is not a frozenset"
    ),
    Rule(
        _Tp,
        "            raise attach(error, reads) from None",
        "            raise",
        "template: errors do not carry the reads",
    ),
    Rule(
        _Tp,
        "            value = self._evaluate(run, recorder(reads, scope))",
        "            value = self._evaluate(run, scope.lookup)",
        "template: parts are not tracked",
    ),
    Rule(
        _X,
        "            value = self._run(run, record)",
        "            value = self._run(run, lookup)",
        "expression: tracked evaluation does not record",
    ),
    Rule(
        _X,
        "        except AttributeError:\n            raise no_lookup() from None\n\n        def record",
        "        except KeyError:\n            raise no_lookup() from None\n\n        def record",
        "expression: tracked evaluation without lookup",
    ),
    Rule(
        _X,
        "    except AttributeError:\n        raise no_lookup() from None\n\n    def record",
        "    except KeyError:\n        raise no_lookup() from None\n\n    def record",
        "template: tracked evaluation without lookup",
    ),
]


TESTS["host"] = ["tests/test_host.py", "tests/test_error_codes.py"]
_H, _K, _Ex, _Tm, _Pa = (
    "src/tel/_host.py",
    "src/tel/_compiler.py",
    "src/tel/expression.py",
    "src/tel/template.py",
    "src/tel/_parser.py",
)
RULES["host"] = [
    Rule(_H, "    if not name.isidentifier():", "    if False:", "host name: not an identifier"),
    Rule(
        _H,
        '    if unicodedata.normalize("NFKC", name) != name:',
        "    if False:",
        "host name: not in normal form",
    ),
    Rule(_H, '    if name.startswith("_"):', "    if False:", "host name: private"),
    Rule(_H, "    if keyword.iskeyword(name):", "    if False:", "host name: keyword"),
    Rule(_H, "    if not isinstance(name, str):", "    if False:", "host name: not text"),
    Rule(_H, "    if not callable(value):", "    if False:", "host entry: not callable"),
    Rule(
        _H,
        "        if name in BUILTIN_NAMES:",
        "        if False:",
        "host function replaces a built-in",
    ),
    Rule(
        _H,
        "            if name in FORMAT_METHODS:",
        "            if False:",
        "host method named format",
    ),
    Rule(
        _H,
        "            if name in covered:",
        "            if False:",
        "host method replaces a built-in method",
    ),
    Rule(
        _H,
        "    if issubclass(kind, str):\n        found |= STR_METHODS",
        "    if False:\n        found |= STR_METHODS",
        "text subclass methods not protected",
    ),
    Rule(
        _H,
        "    if issubclass(kind, (list, tuple)):\n        found |= SEQUENCE_METHODS",
        "    if False:\n        found |= SEQUENCE_METHODS",
        "sequence subclass methods not protected",
    ),
    Rule(
        _H,
        "    if issubclass(kind, Mapping):\n        found |= DICT_METHODS",
        "    if False:\n        found |= DICT_METHODS",
        "mapping subclass methods not protected",
    ),
    Rule(
        _H,
        "        if kind is object or issubclass(kind, DENIED_BASES):",
        "        if False:",
        "methods registered for object or denied types",
    ),
    Rule(
        _H, "        if not isinstance(kind, type):", "        if False:", "methods key not a class"
    ),
    Rule(
        _H, "    if not isinstance(functions, Mapping):", "    if False:", "functions not a mapping"
    ),
    Rule(_H, "    if not isinstance(methods, Mapping):", "    if False:", "methods not a mapping"),
    Rule(
        _H,
        "        if not isinstance(table, Mapping):",
        "        if False:",
        "a type's methods not a mapping",
    ),
    Rule(
        _H,
        "        for kind in type(receiver).__mro__:",
        "        for kind in (type(receiver),):",
        "base classes not searched",
    ),
    Rule(
        _H,
        "            if table is not None and name in table:",
        "            if table is not None:",
        "methods not found name by name",
    ),
    Rule(
        _H,
        '        object.__setattr__(self, "call_names", BUILTIN_NAMES | frozenset(own_functions))',
        '        object.__setattr__(self, "call_names", BUILTIN_NAMES)',
        "host functions not callable",
    ),
    Rule(
        _H,
        '            self, "method_names", METHOD_NAMES.union(*(t.keys() for t in own_methods.values()))',
        '            self, "method_names", METHOD_NAMES',
        "host method names refused by the parser",
    ),
    Rule(
        _K,
        "    check_arguments(S, pos, name, args, kwargs)\n    charge(S, R, pos, 1)",
        "    charge(S, R, pos, 1)",
        "host call arguments unchecked",
    ),
    Rule(
        _K,
        "    check_arguments(S, pos, name, args, kwargs)\n    charge(S, R, pos, 1)",
        "    check_arguments(S, pos, name, args, kwargs)",
        "host call not charged",
    ),
    Rule(
        _K,
        '    if not inert(result):\n        raise S.fail(\n            pos,\n            "result-not-plain"',
        '    if False:\n        raise S.fail(\n            pos,\n            "result-not-plain"',
        "host result not checked",
    ),
    Rule(
        _K,
        "        charge(S, R, pos, len(result) >> 6)\n    elif type(result) is int:",
        "        pass\n    elif type(result) is int:",
        "host text result not charged",
    ),
    Rule(
        _K,
        "    elif type(result) is int:\n        check_int(S, pos, result)\n    return result\n\n\ndef call_builtin",
        "    return result\n\n\ndef call_builtin",
        "host int result unchecked",
    ),
    Rule(
        _K,
        "            result = function(receiver, *args, **kwargs)",
        "            result = function(*args, **kwargs)",
        "host method gets no receiver",
    ),
    Rule(
        _K,
        "        host = S.host.method(base, name)\n        if host is not None:",
        "        host = S.host.method(base, name)\n        if False:",
        "host methods not used",
    ),
    Rule(
        _K,
        "    if name in BUILTIN_NAMES or name in S.host.functions:",
        "    if name in BUILTIN_NAMES:",
        "host function read as a value",
    ),
    Rule(
        _K,
        "        if name not in FUNCTIONS:  # the parser allowed it",
        "        if False:  # the parser allowed it",
        "host functions not compiled",
    ),
    Rule(
        _Pa,
        "            if func.attr not in self.method_names:",
        "            if func.attr not in METHOD_NAMES:",
        "parser ignores host method names",
    ),
    Rule(
        _Tm,
        "    registry = make_registry(functions, methods)\n",
        "    registry = make_registry(None, None)\n",
        "template ignores the host registration",
    ),
    Rule(
        _Ex,
        "        source, origin=origin, limits=limits, registry=make_registry(functions, methods)",
        "        source, origin=origin, limits=limits, registry=EMPTY",
        "expression ignores the host registration",
    ),
]


TESTS["paths"] = ["tests/test_paths.py", "tests/test_tracking.py"]
_C2, _E2, _T2 = "src/tel/_compiler.py", "src/tel/expression.py", "src/tel/template.py"
RULES["paths"] = [
    Rule(
        _C2,
        "                    raise unknown_name(S, root_pos, R, name) from None\n                if type(value) is dict:",
        "                    raise KeyError(name) from None\n                if type(value) is dict:",
        "one-step chain: unknown root error",
    ),
    Rule(
        _C2,
        "                raise unknown_name(S, root_pos, R, name) from None\n            for attr, pos in steps:",
        "                raise KeyError(name) from None\n            for attr, pos in steps:",
        "chain: unknown root error",
    ),
    Rule(
        _C2,
        "        raise unknown_name(S, root_pos, R, root) from None\n    done = 0",
        "        raise KeyError(root) from None\n    done = 0",
        "tracked chain: unknown root error",
    ),
    Rule(
        _C2,
        "    except KeyError:\n        paths.add(root)\n",
        "    except KeyError:\n",
        "tracked chain: a missing root is not reported",
    ),
    Rule(
        _C2,
        '        paths.add(".".join([root, *[step[0] for step in steps[: done + 1]]]))',
        "        pass",
        "tracked chain: the failing path is not reported",
    ),
    Rule(
        _C2,
        "steps[: done + 1]",
        "steps[:done]",
        "tracked chain: the failing step is left out of its path",
    ),
    Rule(
        _C2,
        "    paths.add(path)\n    return value",
        "    return value",
        "tracked chain: the path is not reported",
    ),
    Rule(
        _C2,
        "                    value = value[name]\n                    done += 1\n                    continue",
        "                    value = value[name]\n                    continue",
        "tracked chain: dict steps are not counted",
    ),
    Rule(
        _C2,
        "            value = read_attribute(S, pos, value, name)\n            done += 1",
        "            value = read_attribute(S, pos, value, name)",
        "tracked chain: steps are not counted",
    ),
    Rule(
        _C2,
        "                if R.paths is not None:\n                    return walk_chain_tracked(S, R, R.paths, name, root_pos, ((attr, pos),), path)",
        "                if False:\n                    return walk_chain_tracked(S, R, R.paths, name, root_pos, ((attr, pos),), path)",
        "one-step chain: no tracking",
    ),
    Rule(
        _C2,
        "            if R.paths is not None:\n                return walk_chain_tracked(S, R, R.paths, name, root_pos, steps, path)",
        "            if False:\n                return walk_chain_tracked(S, R, R.paths, name, root_pos, steps, path)",
        "chain: no tracking",
    ),
    Rule(
        _C2,
        "        if type(base) is ast.Name:\n            for frame in self.scopes:\n                if base.id in frame:\n                    break",
        "        if type(base) is ast.Name:\n            for frame in self.scopes:\n                if False:\n                    break",
        "a loop variable's chain is a read",
    ),
    Rule(
        _C2,
        "        self.paths.add(node.id)  # a bare name is a path of one step",
        "        pass",
        "static paths: bare names are missing",
    ),
    Rule(
        _C2,
        '            path = f"{name}.{node.attr}"\n            self.paths.add(path)',
        '            path = f"{name}.{node.attr}"',
        "static paths: one-step chains are missing",
    ),
    Rule(
        _C2,
        '        path = ".".join([name, *[n.attr for n in nodes]])\n        self.paths.add(path)',
        '        path = ".".join([name, *[n.attr for n in nodes]])',
        "static paths: chains are missing",
    ),
    Rule(
        _C2,
        "                self.paths.add(left.id)  # this closure reads the name itself\n                return arithmetic_name_number",
        "                return arithmetic_name_number",
        "static paths: name op number is missing",
    ),
    Rule(
        _C2,
        "            self.paths.add(left.id)  # this closure reads the name itself\n            return comparison_name_constant",
        "            return comparison_name_constant",
        "static paths: name op constant is missing",
    ),
    Rule(_C2, "frozenset(compiler.paths)", "frozenset()", "static paths: not returned"),
    Rule(
        _E2,
        "        run.paths = reads\n        try:\n            lookup = scope.lookup",
        "        try:\n            lookup = scope.lookup",
        "expression: tracked run does not record paths",
    ),
    Rule(
        _T2,
        "        run.paths = reads\n        try:\n            value = self._evaluate",
        "        try:\n            value = self._evaluate",
        "template: tracked run does not record paths",
    ),
    Rule(
        _E2,
        '        return frozenset(path.partition(".")[0] for path in self.reads)',
        "        return self.reads",
        "Tracked.names returns the paths",
    ),
    Rule(
        _E2,
        "        return frozenset(self._paths)",
        "        return frozenset(self._names)",
        "Expression.paths returns the names",
    ),
    Rule(
        _T2,
        "        return frozenset().union(*(p.paths for p in self._parts if isinstance(p, Expression)))",
        "        return frozenset().union(*(p.names for p in self._parts if isinstance(p, Expression)))",
        "Template.paths returns the names",
    ),
]


_T, _P, _S = "src/tel/_ternary.py", "src/tel/_parser.py", "src/tel/_spans.py"

TESTS["ternary"] = ["tests/test_ternary.py"]

RULES["ternary"] = [
    Rule(
        _T,
        "tokens = _Scanner(text).tokens() if _HAS_FSTRING.search(text) else _tokens_fast(text)",
        "tokens = _tokens_fast(text)",
        "f-strings are read by the fast reader, which skips their fields",
    ),
    Rule(
        _T,
        '            elif word == "," or word == "!":',
        '            elif word == "!":',
        "a comma does not end a part",
    ),
    Rule(
        _T,
        '            elif word == "," or word == "!":',
        '            elif word == ",":',
        "a `!` does not end the expression of an f-string field",
    ),
    Rule(
        _T,
        "                if waiting:\n                    waiting -= 1\n                else:\n                    cut = True",
        "                if waiting:\n                    waiting -= 1\n                else:\n                    pass",
        "a colon that no `?` waits for does not end a part (slices, dicts)",
    ),
    Rule(
        _T,
        "                in_for = after_for = cut = True",
        "                in_for = after_for = True",
        "`for` does not end a part",
    ),
    Rule(
        _T,
        '            elif word == "in" and after_for:\n                after_for = False\n                cut = True',
        '            elif word == "in" and after_for:\n                after_for = False',
        "the `in` of a comprehension does not end a part",
    ),
    Rule(
        _T,
        '            elif word == "if" and in_for:\n                cut = True',
        '            elif word == "if" and in_for:\n                pass',
        "the `if` of a comprehension filter does not end a part",
    ),
    Rule(
        _T,
        "                    self.colon[waiting.pop()] = i",
        "                    self.colon[waiting.pop(0)] = i",
        "a `?` in the middle does not wait for its own colon",
    ),
    Rule(
        _T,
        "                    self.colon[waiting.pop()] = i",
        "                    waiting.pop()",
        "the colon is never found",
    ),
    Rule(
        _T,
        "        if self.first_in(self.conditions, owner, lo, hi) is not None:",
        "        if False:",
        "`?:` mixed with `if/else` is accepted",
    ),
    Rule(
        _T,
        "        if colon is None or colon >= hi:\n",
        "        if False:\n",
        "a `?` with no colon is not refused",
    ),
    Rule(
        _T,
        "        k = bisect.bisect_left(indexes, lo)",
        "        k = bisect.bisect_right(indexes, lo)",
        "a `?` or `if` at the start of a part is not found",
    ),
    Rule(
        _T,
        "        return indexes[k] if k < len(indexes) and indexes[k] < hi else None",
        "        return indexes[k] if k < len(indexes) else None",
        "a `?` or `if` after the end of a part is taken for one of its own",
    ),
    Rule(
        _T,
        "                owner, closes, waiting = i, match[i], []",
        "                owner, closes = i, match[i]",
        "a bracket shares the pending `?` of the one around it",
    ),
    Rule(
        _T,
        "        if colon is None or colon >= hi:\n",
        "        if colon is None:\n",
        "a `:` after the end of the part is taken for its colon",
    ),
    Rule(
        _T,
        "        if self.blank(ca, mark):",
        "        if False:",
        "a missing condition is not refused",
    ),
    Rule(
        _T,
        "        if self.blank(end, t.starts[colon]):",
        "        if False:",
        "an empty middle is not refused",
    ),
    Rule(
        _T,
        "        if self.blank(t.ends[colon], cb):",
        "        if False:",
        "an empty else part is not refused",
    ),
    Rule(
        _T,
        "            if b <= cb and a >= ca and not s[b:cb].strip():",
        "            if False:",
        "the closing brackets can land inside a trailing comment",
    ),
    Rule(
        _T,
        "                pb = self.before_comments(pa, pb)\n",
        "",
        "a part's end is not moved before its trailing comments",
    ),
    Rule(
        _T,
        '        out.append(Piece("(", ca))  # the conditional starts where its condition does',
        '        out.append(Piece("(", end))',
        "the conditional is reported after its `?`, not where its condition starts",
    ),
    Rule(
        _T,
        '                if field and len(waiting) == 1 and c == "}":\n                    return i',
        '                if field and len(waiting) == 1 and c == "}":\n                    pass',
        "a field does not end at its closing brace",
    ),
    Rule(
        _T,
        "                elif field and len(waiting) == 1:\n                    return i",
        "                elif field and len(waiting) == 1:\n                    pass",
        "a format spec starts nowhere: its `?` is an operator",
    ),
    Rule(
        _T,
        '            elif c == "!" and field and len(waiting) == 1 and not s.startswith("!=", i):\n                return i',
        '            elif c == "!" and field and len(waiting) == 1 and not s.startswith("!=", i):\n                pass',
        "a field's conversion is part of its expression",
    ),
    Rule(
        _T,
        '            elif c == "{" and not spec and s.startswith("{{", i):\n                i += 2',
        '            elif c == "{" and not spec and s.startswith("{{", i):\n                i += 1',
        "doubled opening braces of an f-string start a field",
    ),
    Rule(
        _T,
        '                if i < n and s[i] == ":":\n                    self.emit(":", i, i + 1)',
        '                if i < n and s[i] == ":":\n                    pass',
        "a format spec is not read",
    ),
    Rule(
        _T,
        '        if kind == "o" and text.startswith(":=", a):\n            continue',
        "        if False:\n            continue",
        "`:=` is read as a colon (fast reader)",
    ),
    Rule(
        _T,
        '                elif s.startswith(":=", i):\n                    i += 2\n                    continue',
        "                elif False:\n                    i += 2\n                    continue",
        "`:=` is read as a colon (f-string reader)",
    ),
    Rule(
        _T,
        "        if end and index > 0:\n            return self.to_original(index - 1) + 1",
        "        if False:\n            return self.to_original(index - 1) + 1",
        "the end of a node is mapped like its start",
    ),
    Rule(
        _T,
        "if self.copied[k] else self.sources[k]",
        "if True else self.sources[k]",
        "inserted text is mapped like copied text",
    ),
    Rule(
        _T,
        "    exc.end_lineno = exc.end_offset = None",
        "    pass",
        "a syntax error keeps the end of the rewritten text",
    ),
    Rule(
        _P,
        "        pieces = _ternary.pieces_of(text)\n    except _ternary.RewriteError as exc:",
        "        pieces = None\n    except _ternary.RewriteError as exc:",
        "the parser ignores the rewrite",
    ),
    Rule(
        _P,
        "            _ternary.move_syntax_error(exc, text, pieces)",
        "            pass",
        "a syntax error of the rewritten text is reported at its own position",
    ),
    Rule(
        _P,
        "        return _parse_quietly(text if pieces is None else _ternary.join(text, pieces))",
        "        return _parse_quietly(text)",
        "the tree is read from the original text",
    ),
    Rule(
        _P,
        "        pieces = _ternary.pieces_of(text)\n        _parse_quietly(text if pieces is None else _ternary.join(text, pieces))",
        "        pieces = _ternary.pieces_of(text)\n        _parse_quietly(text)",
        "a template part is judged on the original text",
    ),
    Rule(
        _P,
        "    except _ternary.RewriteError, SyntaxError, ValueError, RecursionError, MemoryError:",
        "    except SyntaxError, ValueError, RecursionError, MemoryError:",
        "an unpaired `?` makes a template part raise instead of not reading as an expression",
    ),
    Rule(
        _P,
        "    except RecursionError:\n        raise _too_deep(text, here, limits) from None\n    tree = _read",
        "    except ZeroDivisionError:\n        raise _too_deep(text, here, limits) from None\n    tree = _read",
        "a rewrite too deep for Python is a crash, not a depth error",
    ),
    Rule(
        _S,
        '    if "?" in source:  # the tree of a `?:` text has the positions of its rewrite',
        "    if False:  # the tree of a `?:` text has the positions of its rewrite",
        "errors are reported at the positions of the rewritten text",
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


_C = "src/tel/condition.py"

TESTS["condition"] = ["tests/test_condition.py"]

RULES["condition"] = [
    Rule(
        _C,
        "        return truthy(self.expression.evaluate(scope))",
        "        return bool(self.expression.evaluate(scope))",
        "a condition asks a host object for its truth",
    ),
    Rule(
        _C,
        "(truthy(value), reads)",
        "(bool(value), reads)",
        "a tracked condition asks a host object for its truth",
    ),
    Rule(
        _C,
        "        return truthy(self.expression.evaluate(scope))",
        "        return self.expression.evaluate(scope)",
        "a condition gives the value, not a bool",
    ),
    Rule(
        _C,
        "        if condition.holds(scope):",
        "        if True:",
        "the first condition always wins",
    ),
    Rule(
        _C,
        "    return None\n\n\ndef select_tracked",
        "    return 0\n\n\ndef select_tracked",
        "no winner is not None",
    ),
    Rule(
        _C,
        "        reads |= more\n",
        "        pass\n",
        "a chain keeps only the reads of the winner",
    ),
    Rule(
        _C,
        "        if holds:\n            return tuple",
        "        if True:\n            return tuple",
        "the tracked chain stops at the first condition",
    ),
    Rule(
        _C,
        "            raise attach(error, reads | (error.reads or frozenset())) from None",
        "            raise attach(error, error.reads or frozenset()) from None",
        "an error in a chain loses the reads of the earlier conditions",
    ),
    Rule(
        _C,
        "    if isinstance(conditions, Condition):",
        "    if False:",
        "a single condition is not told apart from a chain",
    ),
    Rule(
        _C,
        "        if not isinstance(condition, Condition):",
        "        if False:",
        "a chain accepts what is not a condition",
    ),
    Rule(
        _C,
        "            functions=functions,",
        "            functions=None,",
        "compile_condition drops the host functions",
    ),
    Rule(
        _C,
        "            methods=methods,",
        "            methods=None,",
        "compile_condition drops the host methods",
    ),
    Rule(
        _C,
        "            origin=origin,",
        "            origin=None,",
        "compile_condition drops the origin",
    ),
    Rule(
        _C,
        "            limits=limits,",
        "            limits=DEFAULT_LIMITS,",
        "compile_condition drops the limits",
    ),
    Rule(
        _C,
        '        raise AttributeError("a Condition is immutable")\n\n    def __delattr__',
        "        pass\n\n    def __delattr__",
        "a condition can be changed",
    ),
]


_R = "src/tel/repeater.py"

TESTS["repeater"] = ["tests/test_repeater.py", "tests/test_error_codes.py"]

RULES["repeater"] = [
    Rule(
        _R, r"\s+in(?!\w)(?P<rest>", r"\s+in(?P<rest>", "`in` at the start of a word is the keyword"
    ),
    Rule(
        _R,
        r'_IN = re.compile(r"(?<!\w)in(?!\w)")',
        r'_IN = re.compile(r"in(?!\w)")',
        "`in` at the end of a word is looked for as the keyword",
    ),
    Rule(
        _R,
        "    if not header.strip():\n        raise _syntax(",
        "    if False:\n        raise _syntax(",
        "an empty header is not refused",
    ),
    Rule(
        _R,
        "        if keyword_at is None:",
        "        if False:",
        "a header with no `in` is not told apart",
    ),
    Rule(
        _R,
        "        if not before.strip():",
        "        if False:",
        "a missing loop variable is not told apart",
    ),
    Rule(
        _R,
        '    if not found.group("rest").strip():',
        "    if False:",
        "a header with nothing after `in` is accepted",
    ),
    Rule(
        _R,
        "        if keyword.iskeyword(name):\n            raise _syntax(",
        "        if False:\n            raise _syntax(",
        "a keyword is accepted as a loop variable",
    ),
    Rule(
        _R,
        '        if name.startswith("_") and name != "_":',
        "        if False:",
        "a private loop variable is accepted",
    ),
    Rule(
        _R,
        '        if name.startswith("_") and name != "_":',
        '        if name.startswith("_"):',
        "the throwaway name is private",
    ),
    Rule(
        _R,
        '        if name in targets and name != "_":',
        "        if False:",
        "a repeated loop variable is accepted",
    ),
    Rule(
        _R,
        '        if name in targets and name != "_":',
        "        if name in targets:",
        "two throwaway names are a repeat",
    ),
    Rule(
        _R,
        "origin.advance(header[:rest_at]) if origin else None",
        "origin",
        "the list is positioned at the start of the header",
    ),
    Rule(
        _R,
        "end_column=end_column if end_line == line and end_column > column else None,",
        "end_column=end_column,",
        "a header span over lines is drawn on one",
    ),
    Rule(
        _R,
        '    if not text.isidentifier() or keyword.iskeyword(text) or text.startswith("_"):',
        '    if keyword.iskeyword(text) or text.startswith("_"):',
        "a name that is not an identifier is accepted",
    ),
    Rule(
        _R,
        '    if not text.isidentifier() or keyword.iskeyword(text) or text.startswith("_"):',
        '    if not text.isidentifier() or text.startswith("_"):',
        "a keyword is accepted as the name",
    ),
    Rule(
        _R,
        '    if not text.isidentifier() or keyword.iskeyword(text) or text.startswith("_"):',
        "    if not text.isidentifier() or keyword.iskeyword(text):",
        "a private name is accepted as the name",
    ),
    Rule(
        _R,
        '        end_column=None if "\\n" in text else len(text) + 1,',
        "        end_column=len(text) + 1,",
        "a key error over lines is drawn on one",
    ),
    Rule(
        _R,
        '        end_column=None if "\\n" in text else len(text) + 1,',
        "        end_column=None,",
        "a key error is never underlined",
    ),
    Rule(
        _R,
        "        origin=expression.origin,\n    )\n\n\ndef _run",
        "        origin=None,\n    )\n\n\ndef _run",
        "a repeater error loses its origin",
    ),
    Rule(
        _R,
        '    if not callable(getattr(scope, "lookup", None)):',
        "    if False:",
        "a scope without lookup is not refused",
    ),
    Rule(
        _R,
        "            return self.bindings[name]\n        except KeyError:\n            return self.parent.lookup(name)",
        "            return self.bindings[name]\n        except KeyError:\n            raise",
        "an item scope does not fall through to the host",
    ),
    Rule(
        _R,
        "            return self.bindings[name]\n        except KeyError:",
        "            return self.parent.lookup(name)\n        except KeyError:",
        "the host hides the loop variable",
    ),
    Rule(
        _R,
        "        found = list(self.bindings)\n",
        "        found = []\n",
        "the loop variables are not among the names",
    ),
    Rule(
        _R,
        "            found += [n for n in self.parent.names() if n not in self.bindings]",
        "            found += list(self.parent.names())",
        "a hidden host name is listed twice",
    ),
    Rule(
        _R,
        "        except Exception:  # `names` is optional and only builds a hint\n            pass",
        "        except Exception:\n            raise",
        "a parent without names breaks the item scope",
    ),
    Rule(
        _R, "            if made in seen:", "            if False:", "a duplicate key is accepted"
    ),
    Rule(
        _R,
        "            seen[made] = index\n",
        "            pass\n",
        "the keys seen are not remembered",
    ),
    Rule(
        _R,
        "        if isinstance(source, set | frozenset):",
        "        if False:",
        "a set is repeated",
    ),
    Rule(
        _R,
        "        if not isinstance(source, str | list | tuple | range | Mapping):",
        "        if False:",
        "a value that is not a collection is repeated",
    ),
    Rule(
        _R,
        "        if len(source) > limit:",
        "        if len(source) >= limit:",
        "a list at the limit is refused",
    ),
    Rule(
        _R,
        "        if len(source) > limit:",
        "        if False:",
        "a list over the limit is accepted",
    ),
    Rule(
        _R,
        "        if len(targets) == 1:\n            return {targets[0]: value}",
        "        if False:\n            return {targets[0]: value}",
        "one name is unpacked too",
    ),
    Rule(
        _R,
        "        if not isinstance(value, list | tuple) or len(value) != len(targets):",
        "        if False:",
        "an item of the wrong shape is unpacked",
    ),
    Rule(
        _R,
        "        if not isinstance(value, list | tuple) or len(value) != len(targets):",
        "        if len(value) != len(targets):",
        "a text or a number is unpacked",
    ),
    Rule(
        _R,
        "        if type(key) is tuple:\n            if all(_plain_part(part) for part in key):",
        "        if isinstance(key, tuple):\n            if all(_plain_part(part) for part in key):",
        "a tuple subclass is a key",
    ),
    Rule(
        _R,
        "            if all(_plain_part(part) for part in key):",
        "            if True:",
        "a tuple of anything is a key",
    ),
    Rule(
        _R,
        "    return isinstance(value, int | str) and not isinstance(value, bool)",
        "    return isinstance(value, int | str)",
        "a bool is a key",
    ),
    Rule(
        _R,
        "    return isinstance(value, int | str) and not isinstance(value, bool)",
        "    return isinstance(value, int)",
        "a text is not a key",
    ),
    Rule(
        _R,
        "    return isinstance(value, int | str) and not isinstance(value, bool)",
        "    return isinstance(value, str) and not isinstance(value, bool)",
        "a number is not a key",
    ),
    Rule(
        _R,
        "    return str.__str__(value) if isinstance(value, str) else int.__int__(value)",
        "    return value",
        "a key subclass keeps its own methods",
    ),
    Rule(
        _R,
        "                return tuple(_plain(part) for part in key)",
        "                return key",
        "the parts of a tuple key keep their own methods",
    ),
    Rule(
        _R,
        "        _need_lookup(scope)\n        run = Run()",
        "        run = Run()",
        "items over a non-scope is accepted",
    ),
    Rule(
        _R,
        "        run.steps += len(source)",
        "        run.steps += 0",
        "a long list is not charged",
    ),
    Rule(
        _R,
        "        if run.steps > e.limits.max_steps:",
        "        if False:",
        "a list over the budget is accepted",
    ),
    Rule(_R, "            run.scope = layered\n", "", "a key reads paths through the host scope"),
    Rule(
        _R,
        "        run = Run()\n        run.scope = scope\n",
        "        run = Run()\n",
        "the list reads paths with no scope",
    ),
    Rule(
        _R,
        "        return expression._run(run, lookup)\n    except RecursionError:\n        raise expression._too_deep() from None",
        "        return expression._run(run, lookup)\n    except RecursionError:\n        raise",
        "a stack overflow is not a depth error",
    ),
    Rule(
        _R,
        "        _need_lookup(parent)\n",
        "        pass\n",
        "an item scope over a non-scope is accepted",
    ),
    Rule(
        _R, "    check_language(language)\n", "", "the repeater's language version is not checked"
    ),
    Rule(_R, "    name = _check_name(name)\n", "", "the name is not checked"),
    Rule(
        _R,
        "    items = compile_expression(rest, origin=rest_origin, **common)",
        "    items = compile_expression(rest, origin=origin, **common)",
        "the list is positioned at the header, not after `in`",
    ),
    Rule(
        _R,
        "    made = compile_expression(key, origin=key_origin, **common)",
        "    made = compile_expression(key, origin=origin, **common)",
        "the key is positioned at the header",
    ),
    Rule(
        _R,
        "        language=language, limits=limits, functions=functions, methods=methods\n",
        "        language=language, limits=limits, functions=None, methods=methods\n",
        "the repeater drops the host functions",
    ),
    Rule(
        _R,
        "        language=language, limits=limits, functions=functions, methods=methods\n",
        "        language=language, limits=limits, functions=functions, methods=None\n",
        "the repeater drops the host methods",
    ),
    Rule(
        _R,
        "        language=language, limits=limits, functions=functions, methods=methods\n",
        "        language=language, functions=functions, methods=methods\n",
        "the repeater drops the limits",
    ),
    Rule(
        _R,
        '        raise AttributeError("a Repeater is immutable")\n\n    def __delattr__',
        "        pass\n\n    def __delattr__",
        "a repeater can be changed",
    ),
    Rule(
        _R,
        '        raise AttributeError("an Item is immutable")\n\n    def __delattr__',
        "        pass\n\n    def __delattr__",
        "an item can be changed",
    ),
]


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
