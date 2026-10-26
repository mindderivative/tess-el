"""The language version a host declares."""

from tel.errors import TelVersionError

LANGUAGE = "0.1"
"""The newest language version this release supports (major.minor only)."""

SUPPORTED: tuple[str, ...] = ("0.1",)


def check_language(language: object) -> None:
    """Raise `TelVersionError` unless `language` is a supported version, as text."""
    if not isinstance(language, str):
        raise TelVersionError(
            f"the language version must be text such as '{LANGUAGE}', not "
            f"{type(language).__name__}; YAML reads an unquoted 0.1 as a number (and 0.10 as 0.1), "
            "so quote it",
            code="language-not-text",
        )
    if language not in SUPPORTED:
        raise TelVersionError(
            f"language version {language!r} is not supported; this release supports "
            f"{', '.join(repr(v) for v in SUPPORTED)} (declare only major and minor)",
            code="unsupported-language",
        )
