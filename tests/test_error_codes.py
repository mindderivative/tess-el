"""Every error code TEL can raise is documented, and every documented code can be raised."""

import ast
import dataclasses
import re
from pathlib import Path

from tel.limits import Limits, limit_code

ROOT = Path(__file__).resolve().parent.parent


def codes_in_source() -> set[str]:
    found = {limit_code(f.name) for f in dataclasses.fields(Limits)}
    for path in (ROOT / "src" / "tel").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.keyword) and node.arg == "code":
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    found.add(node.value.value)
            # the checker raises through `self.fail(node, "the-code", "message")`
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "fail"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                found.add(node.args[1].value)
    return found


def codes_in_docs() -> set[str]:
    text = (ROOT / "docs" / "error-codes.md").read_text()
    return set(re.findall(r"^\| `([a-z][a-z0-9-]+)` \|", text, re.MULTILINE))


def test_every_code_in_the_source_is_documented():
    assert codes_in_source() - codes_in_docs() == set()


def test_every_documented_code_is_in_the_source():
    assert codes_in_docs() - codes_in_source() == set()
