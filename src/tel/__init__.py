"""TEL, the Tesserae Expression Language."""

from tel.errors import (
    TelError,
    TelEvaluationError,
    TelLimitError,
    TelSyntaxError,
    TelVersionError,
)
from tel.expression import Expression, compile_expression
from tel.language import LANGUAGE
from tel.limits import DEFAULT_LIMITS, Limits
from tel.origin import Origin
from tel.scope import MapScope, Scope

__version__ = "0.0.1"

__all__ = [
    "DEFAULT_LIMITS",
    "LANGUAGE",
    "Expression",
    "Limits",
    "MapScope",
    "Origin",
    "Scope",
    "TelError",
    "TelEvaluationError",
    "TelLimitError",
    "TelSyntaxError",
    "TelVersionError",
    "__version__",
    "compile_expression",
]
