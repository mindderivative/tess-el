# Versioning

Two version numbers, kept apart:

- **Package version** (`tel.__version__`, `pyproject.toml`): [Semantic Versioning](https://semver.org).
  Below 1.0, a minor bump may break the API.
- **Language version** (starts at `0.1.0`, decision D8): what a file declares so later language
  changes do not break old files (requirement T10). A file declares only major and minor: in the
  Shell, `shell: 0.1`. TEL has no key of its own (it is an expression language, not a file format):
  the host declares the version and passes it to TEL's API, whose form is designed in step 3. The
  patch number never changes the language. Until 1.0 a minor bump may change the language.

The two numbers are independent: package `0.0.1` and language `0.1.0` are both correct today.

The PyPI name is `tess-el` (free on 2026-11-02; `tel` there is another project, and
`tesserae-expression-language` was free too: the maintainer's first choice, not taken). The import name
is `tel`. Every release is described in `CHANGELOG.md`; the steps to make one are in the
`release-checklist` skill, and everything in it that publishes waits for the maintainer.

Releases are git tags `vX.Y.Z`. Consumers such as Tesserae Shell pin an exact TEL version.

## Setting up PyPI

`.github/workflows/release.yml` publishes with PyPI's Trusted Publishing, so no token is stored. The
one-time setup, by the maintainer:

1. **PyPI:** sign in, then *Your account → Publishing → Add a new pending publisher* (a "pending"
   publisher creates the project `tess-el` on its first upload). Owner `mindderivative`, repository
   `tess-el`, workflow `release.yml`, environment `pypi`.
2. **TestPyPI** (optional, for a rehearsal): the same on test.pypi.org with environment `testpypi`.
3. **GitHub:** *Settings → Environments*: create `pypi` and `testpypi`. For `pypi`, add yourself as a
   required reviewer so that a tag never publishes without a click.
4. **Rehearse:** *Actions → Release → Run workflow* on `main` builds, tests and uploads to TestPyPI.
   Install it in a clean environment with
   `uv pip install --index-url https://test.pypi.org/simple/ tess-el`.
5. **Release:** with `pyproject.toml`, `tel.__version__` and a `CHANGELOG.md` section agreeing, push
   the tag: `git tag v0.1.0 && git push origin v0.1.0`. The workflow checks that the three agree and
   that the tag is `v` plus the version, runs the checks, builds, publishes to PyPI after the
   `pypi` environment is approved, and then creates the GitHub release from the changelog section.

A version cannot be uploaded to PyPI twice: a mistake means the next version number.
