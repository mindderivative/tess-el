---
name: release-checklist
description: 'Use only when the user asks for a TEL release or a PyPI publish (plan step 9): version, changelog, build, TestPyPI, tag, PyPI.'
---

# Release checklist

**Every step that publishes (push, tag, TestPyPI/PyPI upload, GitHub release) waits for the user.** The hook blocks `git push`, `uv publish`, `twine upload` and `gh release create`; the user runs or explicitly approves each.

1. **Ready?** Open the board: nothing In progress or In review for this release. `python3 tools/board.py status`.
2. **Version:** bump `version` in `pyproject.toml` and `__version__` in `src/tel/__init__.py` (SemVer; see `docs/versioning.md`). Both must match.
3. **Changelog and docs:** a `CHANGELOG.md` section for the version, README and docs current, the language version noted if it changed.
4. **Checks:** `python tools/check.py` passes on Python 3.14; CI is green on `main` (`gh run list -R mindderivative/tess-el`).
5. **Build:** `uv build --out-dir /tmp/tel-dist`; inspect the wheel and sdist contents (`unzip -l`, `tar tf`): `src/tel`, `py.typed`, `LICENSE`; nothing from `.agents`, `.claude`, `tools` or `docs` that should not ship.
6. **Clean install smoke test:** a new venv, install the wheel, `python -I -c "import tel; print(tel.__version__)"`, and confirm that nothing from Tesserae, tre or the Shell gets imported (T1).
7. **TestPyPI** first (user runs or approves), then install from it into a clean venv.
8. **Tag** `vX.Y.Z` (user approves), push the tag, **PyPI** upload (user approves), GitHub release notes.
9. **After:** tell the Shell side the version to pin (via the user), move the cards to Done with `--approved`, update memory.
