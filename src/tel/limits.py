"""The caps that keep a bad expression an error and never a hang."""

from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True, kw_only=True)
class Limits:
    """Every cap on an expression. Each exceeded cap is a `TelLimitError` with its own `code`.

    Every field is a positive `int`; there is no value that turns a limit off, so `0`, a negative
    number, `None` and `inf` are refused when the object is made.
    """

    max_source: int = 2_000  # characters of expression text
    max_depth: int = 40  # nesting of the syntax tree
    max_nodes: int = 1_000  # nodes in the syntax tree
    max_steps: int = 200_000  # steps in one evaluation
    max_range: int = 100_000  # length of a `range`
    max_sequence: int = 1_000_000  # items in a repeated or joined sequence
    max_pow_exponent: int = 64  # exponent of `**`
    max_int_bits: int = 4_096  # bits in an integer result
    max_string: int = 1_000_000  # characters in a string result

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field.name} must be an int, not {type(value).__name__}")
            if value < 1:
                raise ValueError(
                    f"{field.name} must be at least 1 (a limit cannot be off), not {value}"
                )


DEFAULT_LIMITS = Limits()


def limit_code(field: str) -> str:
    """The `TelLimitError.code` for a limit: `max_pow_exponent` -> `limit-pow-exponent`."""
    if field not in {f.name for f in fields(Limits)}:
        raise ValueError(f"{field!r} is not a limit")
    return "limit-" + field.removeprefix("max_").replace("_", "-")
