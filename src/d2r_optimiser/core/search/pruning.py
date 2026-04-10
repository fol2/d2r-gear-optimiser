"""Hard-constraint pruning and resource-conflict detection for the search engine."""

from __future__ import annotations

from collections import Counter

from d2r_optimiser.core.formula.common import check_all_constraints
from d2r_optimiser.core.models import BuildDefinition


def check_hard_constraints(
    assigned_stats: dict[str, float],
    build: BuildDefinition,
) -> list[str]:
    """Check if current stats violate any hard constraint.

    Returns list of violation descriptions (empty = all pass).
    Delegates to :func:`check_all_constraints` from ``formula.common``.
    """
    return check_all_constraints(assigned_stats, build.constraints)


def check_resource_conflicts(
    resource_costs: list[Counter],
    available_pool: Counter | None = None,
) -> list[str]:
    """Check if resource usage across assigned slots exceeds available supply.

    *resource_costs* is a list of :class:`Counter` objects, one per assigned
    slot.  Each Counter maps resource identifiers (e.g. ``"rune:Ist"`` or
    ``"jewel:uid-123"``) to the quantity consumed by that slot.

    *available_pool* is a Counter of available resources. If provided, usage
    is compared against it. If ``None``, jewels default to 1 available each,
    and runes default to 1 (backward-compatible fallback).

    Returns a list of conflict descriptions (empty = no conflicts).
    """
    merged: Counter = Counter()
    for cost in resource_costs:
        merged.update(cost)

    conflicts: list[str] = []
    for resource_id, count in merged.items():
        if available_pool is not None:
            avail = available_pool.get(resource_id, 1)
        else:
            # Fallback: jewels always 1, runes default 1
            avail = 1
        if count > avail:
            conflicts.append(
                f"Resource {resource_id!r} used {count} times (only {avail} available)"
            )
    return conflicts
