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
from d2r_optimiser.core.stats import merge_stats

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
_AUTO_BEAM_SPACE_THRESHOLD = 5_000_000
_AUTO_BEAM_WIDTH = 512


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
    available_pool: Counter | None = None,
    progress_callback: Callable[[int], None] | None = None,
    beam_width: int | None = None,
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

    available_pool:
        Optional resource availability keyed the same way as candidate
        ``resource_cost`` entries, e.g. ``{"rune:Ist": 2, "jewel:ias_001": 1}``.
        When omitted, each distinct resource defaults to a single use.

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

    search_space = estimate_search_space(candidates_by_slot)
    effective_beam_width = beam_width
    if effective_beam_width is None and search_space > _AUTO_BEAM_SPACE_THRESHOLD:
        effective_beam_width = _AUTO_BEAM_WIDTH
    if effective_beam_width:
        return _beam_search(
            candidates_by_slot,
            build,
            formula,
            top_k=top_k,
            available_pool=available_pool,
            progress_callback=progress_callback,
            beam_width=effective_beam_width,
        )

    # Min-heap of (total_score, counter, result_dict).
    # We use a counter to break ties and keep heap ordering stable.
    heap: list[tuple[float, int, dict]] = []
    counter = 0
    evaluated = 0

    def _recurse(
        slot_idx: int,
        assigned_uids: dict[str, str],
        assigned_fillings: dict[str, list[str] | None],
        assigned_candidates: dict[str, dict],
        running_item_stats: dict[str, float],
        running_costs: list[Counter],
    ) -> None:
        nonlocal counter, evaluated

        # ── Base case: all slots assigned → score and push to heap ──
        if slot_idx == len(active_slots):
            evaluated += 1
            effective_stats = _effective_stats(running_item_stats, assigned_candidates)
            breakdown = formula.score(effective_stats, build)
            total = _compute_total_score(breakdown, build)

            # Final hard-constraint check on the complete loadout
            violations = check_hard_constraints(effective_stats, build)
            if violations:
                return

            result = {
                "slots": dict(assigned_uids),
                "socket_fillings": dict(assigned_fillings),
                "stats": dict(effective_stats),
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
            resource_conflicts = check_resource_conflicts(
                new_costs,
                available_pool=available_pool,
            )
            if resource_conflicts:
                continue

            # ── Accumulate stats ──
            new_item_stats = dict(running_item_stats)
            merge_stats(new_item_stats, candidate["stats"])
            assigned_candidates[slot] = candidate
            effective_stats = _effective_stats(new_item_stats, assigned_candidates)

            # ── Hard-constraint check (partial) ──
            # Only prune on >= constraints if remaining slots cannot possibly
            # help.  For <= constraints, an early violation is definitive.
            # For simplicity in V1 we check all constraints but only prune
            # on "<=" / "==" violations immediately (adding more items cannot
            # reduce a stat total).  ">=" violations are deferred to the
            # complete loadout check.
            if _has_unprunable_violation(effective_stats, build):
                del assigned_candidates[slot]
                continue

            # ── Recurse ──
            assigned_uids[slot] = uid
            assigned_fillings[slot] = candidate.get("socket_fillings")
            _recurse(
                slot_idx + 1,
                assigned_uids,
                assigned_fillings,
                assigned_candidates,
                new_item_stats,
                new_costs,
            )
            del assigned_uids[slot]
            del assigned_fillings[slot]
            del assigned_candidates[slot]

    _recurse(0, {}, {}, {}, {}, [])

    # Final progress report
    if progress_callback and evaluated > 0:
        progress_callback(evaluated)

    # Return top-K sorted descending by total_score
    results = [entry[2] for entry in sorted(heap, key=lambda x: x[0], reverse=True)]
    return results


def estimate_search_space(candidates_by_slot: dict[str, list[dict]]) -> int:
    """Return a rough upper bound on the search space size."""
    active_slots = [s for s in SLOT_ORDER if s in candidates_by_slot]
    if not active_slots:
        return 0

    estimate = 1
    for slot in active_slots:
        count = len(candidates_by_slot.get(slot, []))
        if count <= 0:
            return 0
        estimate *= count
    return estimate


def _beam_search(
    candidates_by_slot: dict[str, list[dict]],
    build: BuildDefinition,
    formula: BuildFormula,
    *,
    top_k: int,
    available_pool: Counter | None,
    progress_callback: Callable[[int], None] | None,
    beam_width: int,
) -> list[dict]:
    """Approximate search for large inventories using beam pruning."""
    active_slots = [s for s in SLOT_ORDER if s in candidates_by_slot]
    beam = [{
        "assigned_uids": {},
        "assigned_fillings": {},
        "assigned_candidates": {},
        "item_stats": {},
        "running_costs": [],
        "heuristic": 0.0,
    }]

    expanded = 0
    for slot in active_slots:
        next_beam: list[dict] = []
        for state in beam:
            for candidate in candidates_by_slot[slot]:
                uid = candidate["item_uid"]
                if slot == "ring2" and uid == state["assigned_uids"].get("ring1"):
                    continue

                new_costs = [*state["running_costs"], candidate.get("resource_cost", Counter())]
                if check_resource_conflicts(new_costs, available_pool=available_pool):
                    continue

                new_item_stats = dict(state["item_stats"])
                merge_stats(new_item_stats, candidate["stats"])

                new_assigned_candidates = dict(state["assigned_candidates"])
                new_assigned_candidates[slot] = candidate
                effective_stats = _effective_stats(new_item_stats, new_assigned_candidates)
                if _has_unprunable_violation(effective_stats, build):
                    continue

                heuristic = _compute_total_score(formula.score(effective_stats, build), build)
                next_beam.append({
                    "assigned_uids": {**state["assigned_uids"], slot: uid},
                    "assigned_fillings": {
                        **state["assigned_fillings"],
                        slot: candidate.get("socket_fillings"),
                    },
                    "assigned_candidates": new_assigned_candidates,
                    "item_stats": new_item_stats,
                    "running_costs": new_costs,
                    "heuristic": heuristic,
                })
                expanded += 1

        if not next_beam:
            return []

        next_beam.sort(key=lambda s: s["heuristic"], reverse=True)
        beam = next_beam[:beam_width]
        if progress_callback:
            progress_callback(expanded)

    results: list[dict] = []
    for state in beam:
        effective_stats = _effective_stats(state["item_stats"], state["assigned_candidates"])
        violations = check_hard_constraints(effective_stats, build)
        if violations:
            continue
        breakdown = formula.score(effective_stats, build)
        results.append({
            "slots": dict(state["assigned_uids"]),
            "socket_fillings": dict(state["assigned_fillings"]),
            "stats": dict(effective_stats),
            "score": breakdown,
            "total_score": _compute_total_score(breakdown, build),
            "violations": [],
        })

    results.sort(key=lambda r: r["total_score"], reverse=True)
    return results[:top_k]


def _effective_stats(
    item_stats: dict[str, float],
    assigned_candidates: dict[str, dict],
) -> dict[str, float]:
    """Return effective stats after applying active set bonuses."""
    effective = dict(item_stats)
    merge_stats(effective, _compute_set_bonus_stats(assigned_candidates))
    return effective


def _compute_set_bonus_stats(assigned_candidates: dict[str, dict]) -> dict[str, float]:
    """Compute total active set bonuses for the currently assigned items."""
    grouped: dict[str, list[dict]] = {}
    for candidate in assigned_candidates.values():
        set_meta = candidate.get("set_meta")
        if not set_meta:
            continue
        grouped.setdefault(set_meta["set_name"], []).append(set_meta)

    bonus_stats: dict[str, float] = {}
    for metas in grouped.values():
        count = len(metas)
        root_meta = metas[0]

        for meta in metas:
            for threshold, stats in meta.get("item_partial_bonus", {}).items():
                if count >= int(threshold):
                    merge_stats(bonus_stats, stats)

        for threshold, stats in root_meta.get("partial_bonuses", {}).items():
            if count >= int(threshold):
                merge_stats(bonus_stats, stats)

        if count >= int(root_meta.get("set_size", 0)):
            merge_stats(bonus_stats, root_meta.get("full_bonus", {}))

    return bonus_stats


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
