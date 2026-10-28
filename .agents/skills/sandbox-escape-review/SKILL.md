---
name: sandbox-escape-review
description: 'Use when adding or changing anything in the TEL parser, evaluator, whitelist, built-ins, scope protocol or Limits, or when asked to review TEL''s safety (T2). Every allowed node, name, attribute and call needs a refusal test and a removal check, and every limit needs a test that it fails fast. Keeps the escape corpus and the fuzzer current.'
---

# Sandbox escape review

TEL evaluates untrusted text from YAML files. Requirement T2: no file, process, network or system access, no `eval`, no attribute escape, and a bad expression is an error, never a hang. The method is a whitelist: anything not listed is refused.

## When a rule is added or changed

1. **Name the rule** in one line (for example "attributes starting with `_` are refused").
2. **Refusal test:** an expression that breaks the rule is refused with a positioned error (file, line, column). Test the error type and that the position is right.
3. **Removal check:** add a `Rule` for it to `tools/removal_check.py` (the breakage: a check made `False`, a branch dropped, a limit off by one) and run `python tools/removal_check.py --group <group> --only "<words from its description>"`. It must report `caught`. A `SURVIVED` rule means the test is missing, or the rule is redundant: then remove the rule, as was done three times in step 3. The full run (about 170 rules) is `python tools/removal_check.py`.
4. **Corpus entry:** add the breaking expression to `tests/escape_corpus/` (one expression per line, with a `#` comment naming the rule). The corpus test asserts every line is refused.
5. **Whitelist entry:** a new allowed node, built-in or method needs a reason in a comment and a test of what it may and may not reach (`type`, `__class__`, `__globals__`, frames, `format`/`format_map`, modules, classes and functions as values).

## Seed corpus

Start from the cases the brief lists, then extend: `().__class__.__bases__`, `__import__('os')`, format-string attribute escapes, lambda tricks, generator frame access, unicode-identifier tricks (NFKC folding to `_`), deep nesting, huge `range`, repeated sequences, `**` with a large exponent, very large integers and strings. Compare with what `expr.py` and the Jinja2 sandbox CVE history refused or missed.

## Limits

Each limit (source length, depth, node count, steps, `range`, repeat, exponent, integer bits, string length) has a named error and a test that the expression **fails promptly**: assert on the error and put a wall-clock ceiling on the test (a hang must fail the test, not freeze CI).

## Fuzzing

Use Hypothesis (see `property-based-testing`): generate expressions from the allowed node set plus mutations that insert forbidden names and attributes. Properties: it never hangs past the limit, never raises anything but TEL's own error type, and never reaches a name outside the scope.

## Review questions (see `sharp-edges`)

- What does `0`, `-1`, empty or `None` mean for each limit? Can a caller switch a limit off by accident?
- Can a scope hand TEL a value whose methods reach the system? The scope is the caller's trust boundary: document it, and refuse modules, classes and functions as values.
- Does an error message leak a value from the scope?

## Report

The rule, the test, the removal result, the corpus line added, and anything that looks reachable but is not yet covered.
