"""Exhaustive search engine with hard-constraint pruning.

Performs a recursive slot-by-slot assignment over all candidate items,
pruning only on hard constraints and resource conflicts (no score-based
pruning).  Maintains a min-heap of the top-K results.
"""

from __future__ import annotations

import heapq
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING

from d2r_optimiser.core.search.pruning import check_hard_constraints, check_resource_conflicts

if TYPE_CHECKING:
    from d2r_optimiser.core.formula.base import BuildFormula
    from d2r_optimiser.core.models import BuildDefinition

# Slot ordering for the search (weapon first — used for sharding in parallel mode).
SLOT_ORDER = [
    "weapon",
    "shield",
    "helmet",
    "body",
    "gloves",
    "belt",
    "boots",
    "amulet",
    "ring1",
    "ring2",
]

# How often to call the progress callback (every N leaf evaluations).
_PROGRESS_INTERVAL = 500


def _compute_total_score(
    breakdown,
    build: BuildDefinition,
) -> float:
    """Compute the weighted composite score from a ScoreBreakdown."""
    w = build.objectives
    return (
        breakdown.damage * w.damage
        + breakdown.magic_find * w.magic_find
        + breakdown.effective_hp * w.effective_hp
        + breakdown.breakpoint_score * w.breakpoint_score
    )


def search(
    candidates_by_slot: dict[str, list[dict]],
    build: BuildDefinition,
    formula: BuildFormula,
    *,
    top_k: int = 5,
    progress_callback: Callable[[int], None] | None = None,
) -> list[dict]:
    """Exhaustive search with hard-constraint pruning.

    Parameters
    ----------
    candidates_by_slot:
        ``{slot_name: [candidate_dict, ...]}`` where each candidate_dict
        contains:

        - ``"item_uid"`` : str
        - ``"stats"``    : dict[str, float] — pre-aggregated stats for this
          item including its socket fillings.
        - ``"resource_cost"`` : Counter — runes/jewels consumed.
        - ``"socket_fillings"`` : list[str] | None — optional filling IDs.

    build:
        The :class:`BuildDefinition` containing constraints and objective
        weights.

    formula:
        A :class:`BuildFormula` instance used for scoring complete loadouts.

    top_k:
        Number of top results to return.

    progress_callback:
        Optional callable invoked periodically with the number of complete
        loadouts evaluated so far.

    Returns
    -------
    list[dict]
        Top-K results sorted by score descending.  Each dict contains:

        - ``"slots"``           : {slot: item_uid}
        - ``"socket_fillings"`` : {slot: [filling_ids]}
        - ``"stats"``           : aggregated stats dict
        - ``"score"``           : ScoreBreakdown
        - ``"total_score"``     : float (weighted composite)
        - ``"violations"``      : [] (empty for valid results)
    """
    # Determine which slots to search — only those present in candidates_by_slot
    # and in the canonical SLOT_ORDER.
    active_slots = [s for s in SLOT_ORDER if s in candidates_by_slot]

    # If any active slot has zero candidates the search space is empty.
    for slot in active_slots:
        if not candidates_by_slot[slot]:
            return []

    # Min-heap of (total_score, counter, result_dict).
    # We use a counter to break ties and keep heap ordering stable.
    heap: list[tuple[float, int, dict]] = []
    counter = 0
    evaluated = 0

    def _recurse(
        slot_idx: int,
        assigned_uids: dict[str, str],
        assigned_fillings: dict[str, list[str] | None],
        running_stats: dict[str, float],
        running_costs: list[Counter],
    ) -> None:
        nonlocal counter, evaluated

        # ── Base case: all slots assigned → score and push to heap ──
        if slot_idx == len(active_slots):
            evaluated += 1
            breakdown = formula.score(running_stats, build)
            total = _compute_total_score(breakdown, build)

            # Final hard-constraint check on the complete loadout
            violations = check_hard_constraints(running_stats, build)
            if violations:
                return

            result = {
                "slots": dict(assigned_uids),
                "socket_fillings": dict(assigned_fillings),
                "stats": dict(running_stats),
                "score": breakdown,
                "total_score": total,
                "violations": [],
            }

            if len(heap) < top_k:
                heapq.heappush(heap, (total, counter, result))
                counter += 1
            elif total > heap[0][0]:
                heapq.heapreplace(heap, (total, counter, result))
                counter += 1

            if progress_callback and evaluated % _PROGRESS_INTERVAL == 0:
                progress_callback(evaluated)
            return

        slot = active_slots[slot_idx]
        candidates = candidates_by_slot[slot]

        for candidate in candidates:
            uid = candidate["item_uid"]

            # ── Ring constraint: ring1 and ring2 must differ ──
            if slot == "ring2" and uid == assigned_uids.get("ring1"):
                continue

            cost: Counter = candidate.get("resource_cost", Counter())

            # ── Resource conflict check ──
            new_costs = [*running_costs, cost]
            resource_conflicts = check_resource_conflicts(new_costs)
            if resource_conflicts:
                continue

            # ── Accumulate stats ──
            new_stats = dict(running_stats)
            for stat, value in candidate["stats"].items():
                new_stats[stat] = new_stats.get(stat, 0.0) + value

            # ── Hard-constraint check (partial) ──
            # Only prune on >= constraints if remaining slots cannot possibly
            # help.  For <= constraints, an early violation is definitive.
            # For simplicity in V1 we check all constraints but only prune
            # on "<=" / "==" violations immediately (adding more items cannot
            # reduce a stat total).  ">=" violations are deferred to the
            # complete loadout check.
            if _has_unprunable_violation(new_stats, build):
                continue

            # ── Recurse ──
            assigned_uids[slot] = uid
            assigned_fillings[slot] = candidate.get("socket_fillings")
            _recurse(
                slot_idx + 1,
                assigned_uids,
                assigned_fillings,
                new_stats,
                new_costs,
            )
            del assigned_uids[slot]
            del assigned_fillings[slot]

    _recurse(0, {}, {}, {}, [])

    # Final progress report
    if progress_callback and evaluated > 0:
        progress_callback(evaluated)

    # Return top-K sorted descending by total_score
    results = [entry[2] for entry in sorted(heap, key=lambda x: x[0], reverse=True)]
    return results


def _has_unprunable_violation(
    stats: dict[str, float],
    build: BuildDefinition,
) -> bool:
    """Return True if the partial stats already violate a constraint that
    adding more items cannot fix.

    - ``<=`` constraints: adding items only increases stat totals, so if
      already exceeded, it is a definitive violation.
    - ``==`` constraints: if already exceeded, cannot be reduced.
    - ``>=`` constraints: deferred — remaining slots may add enough.
    """
    for c in build.constraints:
        actual = stats.get(c.stat, 0.0)
        if c.operator == "<=" and actual > c.value:
            return True
        if c.operator == "==" and actual > c.value:
            return True
    return False
