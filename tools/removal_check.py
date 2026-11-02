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
    fill       the Python form: literals, placeholders and filled templates
    canonical  the canonical text of an expression and a template
    contents   a host object inside a container is not touched by built-ins, comparisons or text
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
    "evaluator": [
        "tests/test_evaluator.py",
        "tests/test_evaluator_limits.py",
        "tests/test_contents.py",
    ],
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
            "if size > limits.max_sequence:",
            "if False:",
            "text join size unchecked",
            2,
        ),
        Rule(
            "src/tel/_compiler.py",
            "charge(S, R, pos, size >> 6)",
            "charge(S, R, pos, 0)",
            "text join not charged",
            2,
        ),
        Rule(
            "src/tel/_compiler.py",
            "                if size > limits.max_string:",
            "                if False:",
            "text join result unchecked",
            0,
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
            "src/tel/_compiler.py", "if not inert(value):", "if False:", "format value unchecked", 1
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
        Rule("src/tel/_compiler.py", "if not inert(value):", "if False:", "sign unchecked", 2),
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
            3,
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
            0,
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
            "        return not any(isinstance(part, Expression) for part in self._parts)",
            "        return not self._parts",
            "text is not told apart from a template",
            None,
        ),
        Rule(
            "src/tel/template.py",
            "        return not any(isinstance(part, Expression) for part in self._parts)",
            "        return True",
            "a template with a part is text",
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
            "            while end >= 0 and not reads(text[body:end]):",
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
        "        except AttributeError:\n            raise no_lookup() from None\n        run = Run()\n        run.scope = scope\n        if self._slots:",
        "        except KeyError:\n            raise no_lookup() from None\n        run = Run()\n        run.scope = scope\n        if self._slots:",
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
        "        if word is None:\n            return i + 1",
        "        if word is None:\n            assert word is not None",
        "a quote that cannot start a string crashes the scanner",
    ),
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

TESTS["repeater"] = [
    "tests/test_repeater.py",
    "tests/test_repeater_parts.py",
    "tests/test_reconcile.py",
    "tests/test_error_codes.py",
]

RULES["repeater"] = [
    Rule(
        "src/tel/expression.py",
        "run.slots = [None] * self._slots",
        "run.slots = [None]",
        "too few loop slots for a repeater's list or key",
        1,
    ),
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
        "        origin=expression.origin,\n    )\n\n\ndef _too_expensive",
        "        origin=None,\n    )\n\n\ndef _too_expensive",
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
        "            return self._bindings[name]\n        except KeyError:\n            return self._parent.lookup(name)",
        "            return self._bindings[name]\n        except KeyError:\n            raise",
        "an item scope does not fall through to the host",
    ),
    Rule(
        _R,
        "            return self._bindings[name]\n        except KeyError:",
        "            return self._parent.lookup(name)\n        except KeyError:",
        "the host hides the loop variable",
    ),
    Rule(
        _R,
        "        found = list(self._bindings)\n",
        "        found = []\n",
        "the loop variables are not among the names",
    ),
    Rule(
        _R,
        "            found += [n for n in self._parent.names() if n not in self._bindings]",
        "            found += list(self._parent.names())",
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
        "            raise self._list._too_deep() from None",
        "            raise",
        "a stack overflow in the list is not a depth error",
    ),
    Rule(
        _R,
        "                raise key._too_deep() from None",
        "                raise",
        "a stack overflow in a key is not a depth error",
    ),
    Rule(
        _R,
        "        single = targets[0] if len(targets) == 1 else None",
        "        single = None",
        "one name goes through the many-names path",
    ),
    Rule(
        _R,
        "        _need_lookup(parent)\n",
        "        pass\n",
        "an item scope over a non-scope is accepted",
    ),
    Rule(
        _R,
        "    if len(header) > limits.max_source:",
        "    if False:",
        "a header over the source limit is read",
    ),
    Rule(
        _R,
        "    if len(header) > limits.max_source:",
        "    if len(header) >= limits.max_source:",
        "a header at the source limit is refused",
    ),
    Rule(
        _R,
        "    check_language(language)\n    header = as_text(",
        "    header = as_text(",
        "the repeater's language version is not checked",
    ),
    Rule(
        _R,
        "    check_language(language)\n    names = as_text(",
        "    names = as_text(",
        "the parts repeater's language version is not checked",
    ),
    Rule(
        _R,
        "    name = _check_name(name)\n    if len(header)",
        "    if len(header)",
        "the name is not checked",
    ),
    Rule(
        _R,
        "    name = _check_name(name)\n    if len(names)",
        "    if len(names)",
        "the parts repeater's name is not checked",
    ),
    Rule(
        _R,
        "    return _make(header, targets, rest, rest_origin, key,",
        "    return _make(header, targets, rest, origin, key,",
        "the list is positioned at the header, not after `in`",
    ),
    Rule(
        _R,
        "        header, targets, items, items_origin, key, key_origin, name, language, limits, host",
        "        header, targets, items, names_origin, key, key_origin, name, language, limits, host",
        "the list is positioned at the names, not at the list",
    ),
    Rule(
        _R,
        "    made = compile_expression(key, origin=key_origin, **common)",
        "    made = compile_expression(key, origin=items_origin, **common)",
        "the key is positioned at the list",
    ),
    Rule(
        _R,
        "    items = compile_expression(items_text, origin=items_origin, **common)",
        "    items = compile_expression(items_text, origin=None, **common)",
        "the list loses its origin",
    ),
    Rule(
        _R,
        "        language=language, limits=limits, functions=host[0], methods=host[1]\n",
        "        language=language, limits=limits, functions=None, methods=host[1]\n",
        "the repeater drops the host functions",
    ),
    Rule(
        _R,
        "        language=language, limits=limits, functions=host[0], methods=host[1]\n",
        "        language=language, limits=limits, functions=host[0], methods=None\n",
        "the repeater drops the host methods",
    ),
    Rule(
        _R,
        "        language=language, limits=limits, functions=host[0], methods=host[1]\n",
        "        language=language, functions=host[0], methods=host[1]\n",
        "the repeater drops the limits",
    ),
    Rule(
        _R,
        "    if len(names) > limits.max_source:",
        "    if False:",
        "names over the source limit are read",
    ),
    Rule(
        _R,
        "    if len(names) > limits.max_source:",
        "    if len(names) >= limits.max_source:",
        "names at the source limit are refused",
    ),
    Rule(
        _R,
        "    if not names.strip():\n        raise _syntax(names,",
        "    if False:\n        raise _syntax(names,",
        "empty names are accepted",
    ),
    Rule(
        _R,
        "    if _NAMES.fullmatch(names) is None:",
        "    if _NAMES.match(names) is None:",
        "names with something after them are accepted",
    ),
    Rule(
        _R,
        "    if _NAMES.fullmatch(names) is None:",
        "    if False:",
        "names that are not names are accepted",
    ),
    Rule(
        _R,
        "    return _check_targets(names, origin, names, 0)",
        "    return tuple(re.findall(_NAME, names))",
        "the parts names skip the keyword and name checks",
    ),
    Rule(
        _R,
        '    targets = _check_targets(header, origin, found.group("target"), found.start("target"))',
        '    targets = _check_targets(header, origin, found.group("target"), 0)',
        "a header name error is placed at the start of the header",
    ),
    Rule(
        _R,
        '    header = f"{names.strip()} in {items.strip()}"',
        '    header = f"{names} in {items}"',
        "the parts header keeps the space of its pieces",
    ),
    Rule(
        _R,
        '        raise AttributeError("a Repeater is immutable")\n\n    def __delattr__',
        "        pass\n\n    def __delattr__",
        "a repeater can be changed",
    ),
    Rule(
        _R,
        "        _need_state(state, self.name)\n        return self._reconcile",
        "        return self._reconcile",
        "a reconcile with no state is accepted",
    ),
    Rule(
        _R,
        "        _need_state(state, self.name)\n        reads: set[str] = set()",
        "        reads: set[str] = set()",
        "a tracked reconcile with no state is accepted",
    ),
    Rule(
        _R,
        "    if state._name is not None and state._name != name:",
        "    if False:",
        "a state of another repeater is accepted",
    ),
    Rule(
        _R,
        "    if state._name is not None and state._name != name:",
        "    if state._name != name:",
        "the empty state belongs to no repeater",
    ),
    Rule(
        _R,
        "numbers, number, self.name",
        'numbers, number, ""',
        "a new state forgets its repeater",
    ),
    Rule(
        _R, "    if not isinstance(state, RepeaterState):", "    if False:", "anything is a state"
    ),
    Rule(
        _R,
        "        number = state._next if state is not None else 0\n",
        "        number = 1 if state is not None else 0\n",
        "the numbers start again every call",
    ),
    Rule(
        _R,
        "            if have is None:\n                have, number = number, number + 1",
        "            if False:\n                have, number = number, number + 1",
        "a new key keeps no number",
    ),
    Rule(
        _R,
        "                have, number = number, number + 1",
        "                have, number = number, number",
        "a number is used twice",
    ),
    Rule(
        _R,
        "            numbers[made] = have\n",
        "            numbers[made] = number\n",
        "a kept key takes the next number",
    ),
    Rule(
        _R,
        'f"{name}_{have:04d}"',
        'f"{name}_{have:03d}"',
        "the number has three digits",
    ),
    Rule(
        _R,
        'f"{name}_{have:04d}"',
        'f"{name}{have:04d}"',
        "the name has no underscore",
    ),
    Rule(
        _R,
        '                status: Literal["new", "kept"] = "new"',
        '                status: Literal["new", "kept"] = "kept"',
        "new and kept are swapped",
    ),
    Rule(
        _R,
        '        kept = [entry for entry in entries if entry.status == "kept"]',
        "        kept = list(entries)",
        "a new key counts as moved",
    ),
    Rule(_R, "if place not in steady)", "if place in steady)", "moved is the steady ones"),
    Rule(
        _R,
        "        removed = tuple(key for key in state._keys if key not in numbers)",
        "        removed = tuple(key for key in state._keys if key in numbers)",
        "removed is what is kept",
    ),
    Rule(
        _R,
        "        removed = tuple(key for key in state._keys if key not in numbers)",
        "        removed = tuple(key for key in reversed(state._keys) if key not in numbers)",
        "removed is in the wrong order",
    ),
    Rule(
        _R,
        "numbers, number, self.name",
        "numbers, number - 1, self.name",
        "the next number is spent twice",
    ),
    Rule(
        _R,
        "tuple(entry.key for entry in entries), numbers, number, self.name",
        "tuple(sorted(numbers, key=repr)), numbers, number, self.name",
        "the state forgets the order",
    ),
    Rule(
        _R,
        "        before[at] = tail_at[k - 1] if k else -1",
        "        before[at] = -1",
        "a run is one entry long",
    ),
    Rule(_R, "    at = tail_at[-1] if tail_at else -1", "    at = -1", "no run is found"),
    Rule(
        _R,
        "        run.add(at)\n        at = before[at]",
        "        run.add(at)\n        at = -1",
        "a run stops after its last entry",
    ),
    Rule(
        _R,
        "            tails[k] = value\n            tail_at[k] = at",
        "            pass",
        "a smaller tail is not remembered",
    ),
    Rule(_R, "            run.paths = reads\n", "", "a tracked reconcile does not record paths"),
    Rule(
        _R,
        "            lookup = recorder(reads, scope)",
        "            pass",
        "a tracked reconcile does not record the list's names",
    ),
    Rule(
        _R,
        "layered.lookup if reads is None else recorder(reads, layered)",
        "layered.lookup",
        "a tracked reconcile does not record the key's names",
    ),
    Rule(
        _R,
        "            raise attach(error, reads) from None",
        "            raise",
        "a tracked reconcile error has no reads",
    ),
    Rule(
        _R,
        '        raise AttributeError("a RepeaterState is immutable")\n\n    def __delattr__',
        "        pass\n\n    def __delattr__",
        "a state can be changed",
    ),
    Rule(
        _R,
        '        raise AttributeError("a Reconciliation is immutable")\n\n    def __delattr__',
        "        pass\n\n    def __delattr__",
        "a result can be changed",
    ),
]


_F = "src/tel/_fill.py"

TESTS["fill"] = ["tests/test_fill.py"]

RULES["fill"] = [
    Rule(_F, '            text = "None"', '            text = "null"', "None is not None"),
    Rule(_F, '            text = "True"', '            text = "true"', "True is not True"),
    Rule(_F, "        elif value is False:", "        elif False:", "False is written as a number"),
    Rule(
        _F,
        "            if int.bit_length(value) > limits.max_int_bits:",
        "            if False:",
        "a number over the bits limit is written",
    ),
    Rule(
        _F,
        "            if int.bit_length(value) > limits.max_int_bits:",
        "            if int.bit_length(value) >= limits.max_int_bits:",
        "a number at the bits limit is refused",
    ),
    Rule(
        _F,
        "            text = _bracket(int.__repr__(value), top)",
        "            text = int.__repr__(value)",
        "a negative integer has no brackets",
    ),
    Rule(
        _F,
        "            text = _bracket(float.__repr__(value), top)",
        "            text = float.__repr__(value)",
        "a negative float has no brackets",
    ),
    Rule(
        _F,
        "            if not math.isfinite(value):",
        "            if False:",
        "nan and inf are written",
    ),
    Rule(
        _F,
        "        elif isinstance(value, list | tuple):",
        "        elif False:",
        "a list or tuple is refused",
    ),
    Rule(_F, "        elif isinstance(value, dict):", "        elif False:", "a dict is refused"),
    Rule(
        _F,
        '        else:\n            raise TypeError(\n                f"{self.where()}: a {type(value).__name__} cannot be written as a literal ({_WHAT})"\n            )',
        "        else:\n            text = repr(value)",
        "any value is written",
    ),
    Rule(
        _F,
        "            if str.__len__(value) > limits.max_source:",
        "            if False:",
        "a huge string is copied before it is refused",
    ),
    Rule(
        _F,
        "            if str.__len__(value) > limits.max_source:",
        "            if len(value) > limits.max_source:",
        "a str subclass's own length is asked",
    ),
    Rule(
        _F,
        "        if self.size > self.limits.max_source:",
        "        if False:",
        "the text is never too long",
    ),
    Rule(
        _F,
        "        if self.size > self.limits.max_source:",
        "        if self.size >= self.limits.max_source:",
        "a text at the size limit is refused",
    ),
    Rule(
        _F,
        "        if depth + 1 > self.limits.max_depth:",
        "        if False:",
        "a value is never too deep",
    ),
    Rule(
        _F,
        "        if depth + 1 > self.limits.max_depth:",
        "        if depth + 1 >= self.limits.max_depth:",
        "a value at the depth limit is refused",
    ),
    Rule(
        _F,
        "    except RecursionError:\n        raise _too_deep(limits) from None",
        "    except RecursionError:\n        raise",
        "a stack overflow is not a depth error",
    ),
    Rule(
        _F,
        "        items = list.__iter__(value) if is_list else tuple.__iter__(value)",
        "        items = iter(value)",
        "a list subclass is iterated by its own method",
    ),
    Rule(
        _F,
        '        out.append("]" if is_list else (",)" if count == 1 else ")"))',
        '        out.append("]" if is_list else ")")',
        "a one-item tuple has no comma",
    ),
    Rule(
        _F,
        '            if count > 1:\n                out.append(", ")\n                self.add(2)',
        '            if False:\n                out.append(", ")\n                self.add(2)',
        "items have no separator",
    ),
    Rule(
        _F,
        '            if count > 1:\n                out.append(", ")\n                self.add(2)',
        '            if count > 1:\n                out.append(", ")',
        "the separator is not counted",
    ),
    Rule(
        _F,
        "        for key, item in dict.items(value):",
        "        for key, item in value.items():",
        "a dict subclass is read by its own method",
    ),
    Rule(
        _F,
        "            if isinstance(key, bool) or not isinstance(key, str | int):",
        "            if not isinstance(key, str | int):",
        "a bool is a dict key",
    ),
    Rule(
        _F,
        "            if isinstance(key, bool) or not isinstance(key, str | int):",
        "            if False:",
        "any dict key is accepted",
    ),
    Rule(
        _F,
        '            if not first:\n                out.append(", ")\n                self.add(2)',
        '            if False:\n                out.append(", ")\n                self.add(2)',
        "dict items have no separator",
    ),
    Rule(_F, "            first = False\n", "", "every dict item has a separator before it"),
    Rule(
        _F,
        '            out.append(": ")\n            self.add(2)',
        '            out.append(":")\n            self.add(1)',
        "a dict is written without a space",
    ),
    Rule(
        _F,
        '    return f"({text})" if top and text.startswith("-") else text',
        '    return f"({text})" if text.startswith("-") else text',
        "a negative number in a container has brackets",
    ),
    Rule(
        _F,
        '    return f"({text})" if top and text.startswith("-") else text',
        "    return text",
        "no number has brackets",
    ),
    Rule(
        _F,
        "    if isinstance(key, str):\n        return str.__repr__(key)",
        "    if isinstance(key, str):\n        return repr(key)",
        "a message runs a str subclass's repr",
    ),
    Rule(
        _F,
        "    if isinstance(key, int):\n        return int.__repr__(key)",
        "    if isinstance(key, int):\n        return repr(key)",
        "a message runs an int subclass's repr",
    ),
    Rule(
        _F,
        '    return f"<{type(key).__name__}>"',
        "    return repr(key)",
        "a message shows a bad name's value",
    ),
    Rule(
        _F,
        '    return _render(value, check_limits(limits), "value")',
        '    return _render(value, limits, "value")',
        "literal does not check its limits",
    ),
    Rule(
        _F,
        '        if found.group("keep") is not None:\n            return found.group()',
        "        if False:\n            return found.group()",
        "a string is masked like a placeholder",
    ),
    Rule(
        _F,
        "    if not isinstance(values, Mapping):",
        "    if False:",
        "values need not be a mapping",
    ),
    Rule(
        _F,
        "        if not isinstance(name, str) or not _NAME.fullmatch(name):",
        "        if False:",
        "any placeholder name is accepted",
    ),
    Rule(
        _F,
        "        if not isinstance(name, str) or not _NAME.fullmatch(name):",
        "        if not isinstance(name, str) or not _NAME.match(name):",
        "a name may end in a bad character",
    ),
    Rule(
        _F,
        '            if found.group("keep") is not None:\n                continue',
        "            if False:\n                continue",
        "a dollar in a string is a placeholder",
    ),
    Rule(
        _F,
        "            if name is None:",
        "            if False:",
        "a dollar with no name is accepted",
    ),
    Rule(
        _F,
        "            out.append(self.text(text[pos : found.start()]))",
        "            pass",
        "the text before a placeholder is dropped",
    ),
    Rule(_F, "            pos = found.end()\n", "", "the text before a placeholder is repeated"),
    Rule(
        _F,
        "        out.append(self.text(text[pos:]))",
        "        pass",
        "the text after the last placeholder is dropped",
    ),
    Rule(_F, "        self.used.add(name)\n", "", "a placeholder is never used"),
    Rule(
        _F,
        "            if name not in self.missing:",
        "            if True:",
        "a missing name is listed every time",
    ),
    Rule(_F, "        if self.missing:", "        if False:", "a missing value is accepted"),
    Rule(
        _F,
        "        unused = sorted(set(self.values) - self.used)",
        "        unused = list(set(self.values) - self.used)",
        "unused names are not sorted",
    ),
    Rule(_F, "        if unused:", "        if False:", "an unused value is accepted"),
    Rule(
        _F,
        "        self.total += n\n        if self.total > self.limits.max_source:",
        "        self.total += n\n        if False:",
        "a filled text is never too long",
    ),
    Rule(
        _F,
        "        self.total += n\n        if self.total > self.limits.max_source:",
        "        self.total += n\n        if self.total >= self.limits.max_source:",
        "a filled text at the limit is refused",
    ),
    Rule(
        _F,
        '    text = as_text(text, "the text")\n    limits = check_limits(limits)\n    filler = _Filler(_need_values(values), limits)\n    result',
        "    limits = check_limits(limits)\n    filler = _Filler(_need_values(values), limits)\n    result",
        "fill does not check its text",
    ),
    Rule(
        _F,
        "    limits = check_limits(limits)\n    filler = _Filler(_need_values(values), limits)\n    result",
        "    filler = _Filler(_need_values(values), limits)\n    result",
        "fill does not check its limits",
    ),
    Rule(
        _F,
        "    filler.done()\n    return result",
        "    return result",
        "fill does not check the values against the placeholders",
    ),
    Rule(
        _F,
        '    text = as_text(text, "the text")\n    limits = check_limits(limits)\n    filler = _Filler(_need_values(values), limits)\n    out',
        "    limits = check_limits(limits)\n    filler = _Filler(_need_values(values), limits)\n    out",
        "fill_template does not check its text",
    ),
    Rule(
        _F,
        "    limits = check_limits(limits)\n    filler = _Filler(_need_values(values), limits)\n    out",
        "    filler = _Filler(_need_values(values), limits)\n    out",
        "fill_template does not check its limits",
    ),
    Rule(
        _F,
        '    filler.done()\n    return "".join(out)',
        '    return "".join(out)',
        "fill_template does not check the values against the placeholders",
    ),
    Rule(
        _F,
        "_split(text, None, lambda part: reads_as_expression(_mask(part)))",
        "_split(text, None)",
        "a part with a placeholder is split by Python's reading of it",
    ),
    Rule(
        _F,
        "        if index < 0:\n            out.append(filler.text(piece))",
        "        if True:\n            out.append(filler.text(piece))",
        "every piece of a template is text",
    ),
    Rule(
        _F,
        "            out.append(filler.fill(piece))",
        "            out.append(filler.text(piece))",
        "a part of a template is not filled",
    ),
    Rule(
        _F,
        '            out.append(filler.text("{{"))',
        "            pass",
        "a part loses its opening braces",
    ),
    Rule(
        _F,
        '            out.append(filler.text("}}"))',
        "            pass",
        "a part loses its closing braces",
    ),
    Rule(
        _F,
        "r\"\"\"(?P<keep>(?:'''(?:[^\\\\]|\\\\.)*?(?:'''|\\Z)|",
        'r"""(?P<keep>(?:',
        "a triple-single-quoted string is not skipped",
    ),
    Rule(
        _F,
        '|\\"\\"\\"(?:[^\\\\]|\\\\.)*?(?:\\"\\"\\"|\\Z)"""',
        '"""',
        "a triple-double-quoted string is not skipped",
    ),
    Rule(_F, "(?:'''|\\Z)", "(?:''')", "a triple-quoted string that is never closed ends early"),
    Rule(_F, "|'(?:[^'\\\\\\n]|\\\\.)*'?", "", "a single-quoted string is not skipped"),
    Rule(
        _F,
        '|"(?:[^"\\\\\\n]|\\\\.)*"?)|\\#[^\\n]*)',
        ")|\\#[^\\n]*)",
        "a double-quoted string is not skipped",
    ),
    Rule(_F, '|\\#[^\\n]*)"""', ')"""', "a comment is not skipped"),
    Rule(
        _F,
        "(?:[^'\\\\\\n]|\\\\.)*'?",
        "(?:[^'\\n]|\\\\.)*'?",
        "a backslash does not escape a quote",
    ),
    Rule(
        _F,
        "(?P<name>[A-Za-z_][A-Za-z0-9_]*)?",
        "(?P<name>[A-Za-z_][A-Za-z0-9_]?)?",
        "a placeholder name is one character",
    ),
    Rule(
        _F,
        "(?P<name>[A-Za-z_][A-Za-z0-9_]*)?",
        "(?P<name>[A-Za-z_][A-Za-z_]*)?",
        "a placeholder name has no digits",
    ),
    Rule(
        _F,
        '_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")',
        '_NAME = re.compile(r"[A-Za-z_][A-Za-z_]*")',
        "a value name has no digits",
    ),
]


TESTS["canonical"] = ["tests/test_canonical.py"]

RULES["canonical"] = [
    Rule(
        "src/tel/_parser.py",
        "    tree = _parse_quietly(text if pieces is None else _ternary.join(text, pieces))\n    return ast.unparse(tree.body)",
        "    tree = _parse_quietly(text)\n    return ast.unparse(tree.body)",
        "the question-mark spelling is not rewritten",
    ),
    Rule(
        "src/tel/_parser.py",
        "    return ast.unparse(tree.body)",
        "    return text",
        "the canonical text is the text as written",
    ),
    Rule(
        "src/tel/_parser.py",
        "    return ast.unparse(tree.body)",
        "    return ast.dump(tree.body)",
        "the canonical text is a dump, not code",
    ),
    Rule(
        "src/tel/expression.py",
        "            return canonical_text(self.text)",
        "            return canonical_text(self.source)",
        "the canonical text starts from the unstripped source",
    ),
    Rule(
        "src/tel/expression.py",
        "            return canonical_text(self.text)\n        except RecursionError:\n            raise self._too_deep() from None",
        "            return canonical_text(self.text)\n        except RecursionError:\n            raise",
        "a stack overflow in canonical is not a depth error",
    ),
    Rule(
        "src/tel/template.py",
        '            part if isinstance(part, str) else "{{ " + part.canonical + " }}"',
        '            part if isinstance(part, str) else "{{ " + part.text + " }}"',
        "a template part is written as it was spelt",
    ),
    Rule(
        "src/tel/template.py",
        '            part if isinstance(part, str) else "{{ " + part.canonical + " }}"',
        '            "" if isinstance(part, str) else "{{ " + part.canonical + " }}"',
        "the literal text of a template is dropped",
    ),
    Rule(
        "src/tel/template.py",
        '            part if isinstance(part, str) else "{{ " + part.canonical + " }}"',
        "            part if isinstance(part, str) else part.canonical",
        "a template part loses its braces",
    ),
    Rule(
        "src/tel/template.py",
        '            part if isinstance(part, str) else "{{ " + part.canonical + " }}"',
        '            part if isinstance(part, str) else "{{" + part.canonical + "}}"',
        "a template part has no spaces inside its braces",
    ),
]


TESTS["contents"] = ["tests/test_contents.py", "tests/test_escape_corpus.py"]

RULES["contents"] = [
    Rule(
        "src/tel/_compiler.py",
        "    if (kind is list or kind is tuple) and set(map(type, value)) <= SCALARS:",
        "    if (kind is list or kind is tuple) and True:",
        "any flat list is taken for plain scalars",
    ),
    Rule(
        "src/tel/_compiler.py",
        "    if found is not None:\n        raise not_plain(S, pos, found, use)",
        "    if False:\n        raise not_plain(S, pos, found, use)",
        "a host object inside a container is accepted",
    ),
    Rule(
        "src/tel/_compiler.py",
        "        found = foreign_inside(value, S.limits.max_steps)",
        "        found = foreign_inside(value, 10**12)",
        "the search of a container has no size limit",
    ),
    Rule(
        "src/tel/_compiler.py",
        "    except TooMany:\n        raise S.limit(",
        "    except TooMany:\n        raise ValueError() from None\n        raise S.limit(",
        "a container too big to search is a crash",
    ),
    Rule(
        "src/tel/_compiler.py",
        '_GUARDED = frozenset("min max sum sorted any all set dict str".split())',
        '_GUARDED = frozenset("min max sum sorted any all set dict".split())',
        "str of a list with a host object is allowed",
    ),
    Rule(
        "src/tel/_compiler.py",
        '_GUARDED = frozenset("min max sum sorted any all set dict str".split())',
        '_GUARDED = frozenset("min max sum sorted any all set str".split())',
        "dict of pairs with a host object is allowed",
    ),
    Rule(
        "src/tel/_compiler.py",
        '_GUARDED = frozenset("min max sum sorted any all set dict str".split())',
        '_GUARDED = frozenset("min max sum sorted set dict str".split())',
        "any and all over host objects are allowed",
    ),
    Rule(
        "src/tel/_compiler.py",
        '_GUARDED = frozenset("min max sum sorted any all set dict str".split())',
        'frozenset_ = frozenset("min max sum sorted any all set dict str".split())\n_GUARDED = frozenset()',
        "no built-in is guarded",
    ),
    Rule(
        "src/tel/_compiler.py",
        "    if name in _GUARDED:\n        for value in args:",
        "    if False:\n        for value in args:",
        "built-ins over host objects are not checked",
    ),
    Rule(
        "src/tel/_compiler.py",
        '    check_contents(S, pos, a, "inside a value in a comparison")\n',
        "",
        "the left side of a comparison is not searched",
    ),
    Rule(
        "src/tel/_compiler.py",
        '    check_contents(S, pos, b, "inside a value in a comparison")\n',
        "",
        "the right side of a comparison is not searched",
    ),
    Rule(
        "src/tel/_compiler.py",
        '    check_contents(S, pos, value, "inside a value in text")\n',
        "",
        "a value in text is not searched",
    ),
    Rule(
        "src/tel/_compiler.py",
        '    if name == "index" or name == "count":',
        "    if False:",
        ".index and .count over host objects are allowed",
    ),
    Rule(
        "src/tel/_values.py",
        "        if isinstance(item, _SEQUENCE_TYPES):\n            if id(item) in seen:\n                continue",
        "        if isinstance(item, _SEQUENCE_TYPES):\n            if False:\n                continue",
        "a container is searched again every time it is met",
    ),
    Rule(
        "src/tel/_values.py",
        "        elif isinstance(item, dict):\n            if id(item) in seen:\n                continue",
        "        elif isinstance(item, dict):\n            if False:\n                continue",
        "a dict is searched again every time it is met",
    ),
    Rule(
        "src/tel/_values.py",
        "                members = list(list.__iter__(item))",
        "                members = list(item)",
        "a list subclass is iterated by its own method",
    ),
    Rule(
        "src/tel/_values.py",
        "                members = list(tuple.__iter__(item))",
        "                members = list(item)",
        "a tuple subclass is iterated by its own method",
    ),
    Rule(
        "src/tel/_values.py",
        "                members = list(set.__iter__(item))",
        "                members = list(item)",
        "a set subclass is iterated by its own method",
    ),
    Rule(
        "src/tel/_values.py",
        "                members = list(frozenset.__iter__(item))",
        "                members = list(item)",
        "a frozenset subclass is iterated by its own method",
    ),
    Rule(
        "src/tel/_values.py",
        "            members = [*dict.keys(item), *dict.values(item)]",
        "            members = [*item.keys(), *item.values()]",
        "a dict subclass is read by its own methods",
    ),
    Rule(
        "src/tel/_values.py",
        "            members = [*dict.keys(item), *dict.values(item)]",
        "            members = [*dict.values(item)]",
        "dict keys are not searched",
    ),
    Rule(
        "src/tel/_values.py",
        "            members = [*dict.keys(item), *dict.values(item)]",
        "            members = [*dict.keys(item)]",
        "dict values are not searched",
    ),
    Rule(
        "src/tel/_values.py",
        "        elif not is_inert(item):\n            return item",
        "        elif False:\n            return item",
        "a host object is not returned",
    ),
    Rule(
        "src/tel/_values.py",
        "        looked += len(members)\n        if looked > allowed:",
        "        looked += 0\n        if looked > allowed:",
        "the elements looked at are not counted",
    ),
    Rule(
        "src/tel/_values.py",
        "        if looked > allowed:\n            raise TooMany",
        "        if looked >= allowed:\n            raise TooMany",
        "a container exactly at the allowance is refused",
    ),
    Rule(
        "src/tel/_values.py",
        "        if not set(map(type, members)) <= SCALARS:\n            stack.extend(m for m in members if type(m) not in SCALARS)",
        "        if False:\n            stack.extend(m for m in members if type(m) not in SCALARS)",
        "nested containers are not searched",
    ),
    Rule(
        "src/tel/_values.py",
        "            stack.extend(m for m in members if type(m) not in SCALARS)",
        "            stack.extend(m for m in members[:1] if type(m) not in SCALARS)",
        "only the first nested element is searched",
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
