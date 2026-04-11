"""Common formula helpers — MF curve, breakpoint lookup, stat aggregation, constraints."""

from __future__ import annotations

from d2r_optimiser.core.stats import merge_stats


def effective_mf(raw_mf: float) -> dict[str, float]:
    """Apply D2R diminishing returns to raw MF.

    Returns ``{"unique": x, "set": y, "rare": z}`` effective MF values.

    Official D2R formulas:
    - Unique: raw_mf * 250 / (raw_mf + 250)
    - Set:    raw_mf * 500 / (raw_mf + 500)
    - Rare:   raw_mf * 600 / (raw_mf + 600)

    At raw_mf=0 all values are 0.  The curves asymptote at 250/500/600.
    """
    if raw_mf <= 0:
        return {"unique": 0.0, "set": 0.0, "rare": 0.0}

    return {
        "unique": raw_mf * 250.0 / (raw_mf + 250.0),
        "set": raw_mf * 500.0 / (raw_mf + 500.0),
        "rare": raw_mf * 600.0 / (raw_mf + 600.0),
    }


def lookup_breakpoint(thresholds: list[dict], stat_value: float) -> dict:
    """Find the highest breakpoint threshold met.

    *thresholds* must be a list of ``{threshold: int, frames: int}`` sorted
    ascending by threshold.  Returns the entry whose threshold is the highest
    that does not exceed *stat_value*.

    If *stat_value* is below the first threshold, returns the first entry
    (the slowest animation).
    """
    if not thresholds:
        msg = "thresholds list must not be empty"
        raise ValueError(msg)

    matched = thresholds[0]
    for entry in thresholds:
        if stat_value >= entry["threshold"]:
            matched = entry
        else:
            break
    return matched


def aggregate_stats(items_by_slot: dict[str, list[dict]]) -> dict[str, float]:
    """Sum all stats across all equipped items and their socket contents.

    *items_by_slot* maps slot names to lists of stat dicts, e.g.::

        {"helmet": [{"mf": 50, "all_skills": 2}],
         "body":   [{"mf": 99, "all_skills": 2, "strength": 15}]}

    Returns a flat ``{stat_name: total_value}`` dict.
    """
    totals: dict[str, float] = {}
    for slot_items in items_by_slot.values():
        for stat_dict in slot_items:
            merge_stats(totals, stat_dict)
    return totals


_OPERATORS: dict[str, callable] = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}


def check_constraint(stats: dict[str, float], constraint) -> bool:
    """Check if aggregated stats meet a single constraint.

    *constraint* must expose ``.stat``, ``.operator``, and ``.value`` attributes
    (i.e. a ``Constraint`` model instance).

    Returns ``True`` if the constraint is satisfied.
    """
    actual = stats.get(constraint.stat, 0.0)
    op_fn = _OPERATORS.get(constraint.operator)
    if op_fn is None:
        msg = f"Unsupported constraint operator: {constraint.operator!r}"
        raise ValueError(msg)
    return op_fn(actual, constraint.value)


def check_all_constraints(stats: dict[str, float], constraints: list) -> list[str]:
    """Check all constraints against aggregated stats.

    Returns a list of violation description strings.  An empty list means
    all constraints are satisfied.
    """
    violations: list[str] = []
    for c in constraints:
        if not check_constraint(stats, c):
            actual = stats.get(c.stat, 0.0)
            violations.append(
                f"{c.stat} {c.operator} {c.value} not met (actual: {actual})"
            )
    return violations
