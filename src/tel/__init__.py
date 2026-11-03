"""TEL, the Tesserae Expression Language."""

from tel._fill import fill, fill_template, literal
from tel.condition import Condition, compile_condition, select, select_tracked
from tel.errors import (
    TelError,
    TelEvaluationError,
    TelLimitError,
    TelSyntaxError,
    TelVersionError,
)
from tel.expression import Expression, Tracked, compile_expression
from tel.language import LANGUAGE
from tel.limits import DEFAULT_LIMITS, Limits
from tel.origin import Origin
from tel.repeater import (
    Entry,
    Item,
    Reconciliation,
    Repeater,
    RepeaterState,
    compile_repeater,
    compile_repeater_parts,
)
from tel.scope import MapScope, Scope
from tel.template import Template, compile_template

__version__ = "0.1.1"

__all__ = [
    "Condition",
    "DEFAULT_LIMITS",
    "LANGUAGE",
    "Entry",
    "Expression",
    "Item",
    "Limits",
    "MapScope",
    "Origin",
    "Reconciliation",
    "Repeater",
    "RepeaterState",
    "Scope",
    "Template",
    "Tracked",
    "TelError",
    "TelEvaluationError",
    "TelLimitError",
    "TelSyntaxError",
    "TelVersionError",
    "__version__",
    "compile_condition",
    "compile_expression",
    "compile_repeater",
    "compile_repeater_parts",
    "compile_template",
    "fill",
    "fill_template",
    "literal",
    "select",
    "select_tracked",
]
