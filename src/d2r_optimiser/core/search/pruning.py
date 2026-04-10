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
) -> list[str]:
    """Check if any rune or jewel is double-used across assigned slots.

    *resource_costs* is a list of :class:`Counter` objects, one per assigned
    slot.  Each Counter maps resource identifiers (e.g. ``"rune:Ist"`` or
    ``"jewel:uid-123"``) to the quantity consumed by that slot.

    The function merges all counters and compares against a global pool of
    available resources.  For jewels, each unique UID may only appear once.
    For runes, total usage must not exceed total count across all Counters
    provided — i.e. the same physical rune cannot be placed in two items.

    Returns a list of conflict descriptions (empty = no conflicts).
    """
    merged: Counter = Counter()
    for cost in resource_costs:
        merged.update(cost)

    conflicts: list[str] = []
    for resource_id, count in merged.items():
        if count > 1:
            conflicts.append(
                f"Resource {resource_id!r} used {count} times (only 1 available)"
            )
    return conflicts
