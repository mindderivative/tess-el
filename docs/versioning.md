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
