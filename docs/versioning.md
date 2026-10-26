# Versioning

Two version numbers, kept apart:

- **Package version** (`tel.__version__`, `pyproject.toml`): [Semantic Versioning](https://semver.org).
  Below 1.0, a minor bump may break the API.
- **Language version**: what a file declares so later language changes do not break old files
  (requirement T10). The declaration syntax is not decided yet.

Releases are git tags `vX.Y.Z`. Consumers such as Tesserae Shell pin an exact TEL version.
