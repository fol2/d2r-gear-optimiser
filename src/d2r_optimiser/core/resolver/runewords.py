"""Resolve craftable runewords from a player's rune pool and socket bases."""

import json
from collections import Counter

from d2r_optimiser.core.models import Item, Rune, RunewordRecipe


def enumerate_craftable_runewords(
    rune_pool: list[Rune],
    bases: list[Item],
    recipes: list[RunewordRecipe],
) -> list[dict]:
    """Enumerate all runewords that can be crafted from available runes and bases.

    Returns list of dicts, each containing:
    - ``recipe``: the :class:`RunewordRecipe`
    - ``base``: the :class:`Item` used as base
    - ``rune_cost``: :class:`~collections.Counter` of runes consumed
      (e.g. ``Counter({"Jah": 1, "Ith": 1, "Ber": 1})``)

    Does **not** check cross-runeword resource conflicts (that is the search
    engine's job).  Each result is independently valid -- it simply checks
    whether the runes and a compatible base exist in the pool.
    """
    # Build a Counter {rune_type: quantity} from the pool.
    pool: Counter[str] = Counter()
    for rune in rune_pool:
        pool[rune.rune_type] += rune.quantity

    results: list[dict] = []

    for recipe in recipes:
        # --- rune availability --------------------------------------------------
        required = Counter(recipe.rune_sequence.split("-"))
        if not all(pool[rune] >= count for rune, count in required.items()):
            continue

        # --- compatible bases ---------------------------------------------------
        base_types: list[str] = json.loads(recipe.base_types)

        for base in bases:
            # Skip items that are already completed runewords.
            if base.item_type == "runeword":
                continue

            # Check socket count.
            if base.socket_count < recipe.socket_count:
                continue

            # Match: the item's slot or its base name (lowered) against the
            # recipe's accepted base_types list (also lowered).
            base_types_lower = [bt.lower() for bt in base_types]
            slot_matches = base.slot.lower() in base_types_lower
            base_name_matches = (
                base.base is not None and base.base.lower() in base_types_lower
            )
            if not slot_matches and not base_name_matches:
                continue

            results.append(
                {
                    "recipe": recipe,
                    "base": base,
                    "rune_cost": Counter(required),
                }
            )

    return results
