"""TEL, the Tesserae Expression Language."""

from tel.errors import (
    TelError,
    TelEvaluationError,
    TelLimitError,
    TelSyntaxError,
    TelVersionError,
)
from tel.language import LANGUAGE
from tel.limits import DEFAULT_LIMITS, Limits
from tel.origin import Origin

__version__ = "0.0.1"

__all__ = [
    "DEFAULT_LIMITS",
    "LANGUAGE",
    "Limits",
    "Origin",
    "TelError",
    "TelEvaluationError",
    "TelLimitError",
    "TelSyntaxError",
    "TelVersionError",
    "__version__",
]
