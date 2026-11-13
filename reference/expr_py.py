"""Load Tesserae UI's `expr.py` by file path, for reference and measurement only.

TEL does not import `expr.py`, and nothing under `src/` imports this module. `expr.py` imports
`tess_ui.reactive` only to tell a `Signal` or `Computed` from a plain value, so a stub package with
two empty classes stands in and the real Tesserae (and its GUI dependencies) is never imported.

The clone is read, never written: the file is compiled in memory and no bytecode is cached.
Set `TESSERAE_SRC` to the clone's `src` directory if it is not in the default place.
"""

import importlib.util
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

DEFAULT_SRC = Path.home() / "Projects/pyDev/projects/tesserae/src"
SRC = Path(os.environ.get("TESSERAE_SRC", DEFAULT_SRC))
PATH = SRC / "tess_ui" / "expr.py"


def available() -> bool:
    return PATH.is_file()


def clone_commit() -> str:
    """The Tesserae clone's HEAD, so a result says which `expr.py` it measured."""
    done = subprocess.run(
        ["git", "-C", str(SRC), "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    )
    return done.stdout.strip() or "unknown"


def load() -> types.ModuleType:
    """The `expr.py` module, loaded once per process."""
    if "tess_ui.expr" in sys.modules:
        return sys.modules["tess_ui.expr"]
    sys.dont_write_bytecode = True
    package = types.ModuleType("tess_ui")
    package.__path__ = []  # a package, so `tess_ui.reactive` can be a submodule
    reactive = types.ModuleType("tess_ui.reactive")
    for name in ("Signal", "Computed"):
        setattr(reactive, name, type(name, (), {"get": lambda self: None}))
    package.reactive = reactive  # type: ignore[attr-defined]
    sys.modules["tess_ui"] = package
    sys.modules["tess_ui.reactive"] = reactive
    spec = importlib.util.spec_from_file_location("tess_ui.expr", PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["tess_ui.expr"] = module
    spec.loader.exec_module(module)
    return module


def namespace() -> Any:
    return load()
