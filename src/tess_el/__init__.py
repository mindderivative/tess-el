"""TEL, the Tesserae Expression Language."""

from tess_el._fill import fill, fill_template, literal
from tess_el.condition import Condition, compile_condition, select, select_tracked
from tess_el.errors import (
    TelError,
    TelEvaluationError,
    TelLimitError,
    TelSyntaxError,
    TelVersionError,
)
from tess_el.expression import Expression, Tracked, compile_expression
from tess_el.language import LANGUAGE
from tess_el.limits import DEFAULT_LIMITS, Limits
from tess_el.origin import Origin
from tess_el.repeater import (
    Entry,
    Item,
    Reconciliation,
    Repeater,
    RepeaterState,
    compile_repeater,
    compile_repeater_parts,
)
from tess_el.scope import MapScope, Scope
from tess_el.template import Template, compile_template

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
