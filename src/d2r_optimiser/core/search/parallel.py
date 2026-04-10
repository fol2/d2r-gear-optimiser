"""Parallel search — shard by weapon slot across worker processes."""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING

from d2r_optimiser.core.search.engine import search

if TYPE_CHECKING:
    from d2r_optimiser.core.models import BuildDefinition


def _worker_search(
    weapon_candidate: dict,
    remaining_candidates: dict[str, list[dict]],
    build: BuildDefinition,
    formula_module: str,
    top_k: int,
    breakpoints: dict | None = None,
) -> list[dict]:
    """Worker function executed in a child process.

    Each worker receives a single fixed weapon candidate and searches
    all remaining slots.  The formula instance is created fresh inside
    the worker because Protocol instances cannot be pickled across
    process boundaries.  Breakpoint data is passed explicitly and
    injected into the formula to ensure parity with single-threaded mode.
    """
    from d2r_optimiser.core.formula.base import get_formula

    formula = get_formula(formula_module)
    if breakpoints and hasattr(formula, "_breakpoints"):
        formula._breakpoints = breakpoints

    # Build the candidate dict for this worker: the weapon slot has exactly
    # one candidate (the assigned weapon), all other slots are the full set.
    candidates_by_slot = dict(remaining_candidates)
    candidates_by_slot["weapon"] = [weapon_candidate]

    return search(
        candidates_by_slot,
        build,
        formula,
        top_k=top_k,
    )


def _serialise_candidate(candidate: dict) -> dict:
    """Ensure candidate dict is picklable for cross-process transport.

    Converts Counter objects to plain dicts for serialisation, then the
    worker will wrap them back.  (Counter is picklable in CPython, but
    being explicit avoids edge cases.)
    """
    result = dict(candidate)
    cost = result.get("resource_cost")
    if isinstance(cost, Counter):
        result["resource_cost"] = dict(cost)
    return result


def parallel_search(
    candidates_by_slot: dict[str, list[dict]],
    build: BuildDefinition,
    formula_module: str,
    *,
    top_k: int = 5,
    workers: int | None = None,
    progress_callback: Callable[[int], None] | None = None,
    breakpoints: dict | None = None,
) -> list[dict]:
    """Parallel search sharded by weapon slot.

    Each worker gets one weapon candidate and searches all remaining
    slots.  Results are merged and re-sorted for the global top-K.

    Falls back to single-threaded search if ``workers=1`` or there are
    very few weapon candidates.

    Parameters
    ----------
    candidates_by_slot:
        Full candidate dict as expected by :func:`search`.

    build:
        The :class:`BuildDefinition` for constraint checking and scoring.

    formula_module:
        Module name string (e.g. ``"warlock_echoing_strike"``).  Each
        worker creates its own formula instance via :func:`get_formula`.

    top_k:
        Number of top results to return.

    workers:
        Number of parallel workers.  Defaults to ``min(cpu_count, len(weapon_candidates))``.

    progress_callback:
        Optional callable.  In parallel mode, called once per completed
        worker with the cumulative result count.
    """
    weapon_candidates = candidates_by_slot.get("weapon", [])

    # Determine effective worker count
    if workers is None:
        cpu_count = os.cpu_count() or 1
        effective_workers = min(cpu_count, max(len(weapon_candidates), 1))
    else:
        effective_workers = workers

    # Fall back to single-threaded search when it makes sense
    if effective_workers <= 1 or len(weapon_candidates) <= 1:
        from d2r_optimiser.core.formula.base import get_formula

        formula = get_formula(formula_module)
        if breakpoints and hasattr(formula, "_breakpoints"):
            formula._breakpoints = breakpoints
        return search(
            candidates_by_slot,
            build,
            formula,
            top_k=top_k,
            progress_callback=progress_callback,
        )

    # Prepare remaining slots (everything except weapon)
    remaining = {
        slot: [_serialise_candidate(c) for c in cands]
        for slot, cands in candidates_by_slot.items()
        if slot != "weapon"
    }

    serialised_weapons = [_serialise_candidate(w) for w in weapon_candidates]

    # Dispatch workers
    all_results: list[dict] = []
    completed_workers = 0

    with ProcessPoolExecutor(max_workers=effective_workers) as executor:
        futures = [
            executor.submit(
                _worker_search,
                weapon,
                remaining,
                build,
                formula_module,
                top_k,
                breakpoints,
            )
            for weapon in serialised_weapons
        ]

        for idx, future in enumerate(futures):
            try:
                worker_results = future.result()
            except Exception as exc:
                weapon_uid = weapon_candidates[idx].get("item_uid", "unknown")
                raise RuntimeError(
                    f"Search worker {idx} (weapon={weapon_uid}) failed: {exc}"
                ) from exc
            all_results.extend(worker_results)
            completed_workers += 1
            if progress_callback:
                progress_callback(completed_workers)

    # Merge and re-sort for global top-K
    all_results.sort(key=lambda r: r["total_score"], reverse=True)
    return all_results[:top_k]
