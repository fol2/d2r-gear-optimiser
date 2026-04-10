"""Validation module — compare predicted stats against reference/live measurements."""

from d2r_optimiser.core.validation.validator import (
    check_all_validations,
    record_live_measurement,
    validate_against_reference,
)

__all__ = [
    "check_all_validations",
    "record_live_measurement",
    "validate_against_reference",
]
