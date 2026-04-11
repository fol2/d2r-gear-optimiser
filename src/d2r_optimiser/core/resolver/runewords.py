"""Resolve craftable runewords from a player's rune pool and socket bases."""

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

from d2r_optimiser.core.models import Item, Rune, RunewordRecipe
from d2r_optimiser.loader import load_base_items

_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
_MELEE_WEAPON_CATEGORIES = {
    "axe",
    "club",
    "claw",
    "dagger",
    "hammer",
    "javelin",
    "mace",
    "melee_weapon",
    "polearm",
    "scepter",
    "spear",
    "staff",
    "sword",
    "wand",
}
_MISSILE_WEAPON_CATEGORIES = {
    "amazon_bow",
    "bow",
    "crossbow",
    "missile_weapon",
}


@lru_cache(maxsize=1)
def _base_category_lookup() -> dict[str, str]:
    """Load ``data/items.yaml`` into a lowercase ``name -> item_category`` lookup."""
    items_path = _DATA_DIR / "items.yaml"
    try:
        entries = load_base_items(items_path)
    except FileNotFoundError:
        return {}

    lookup: dict[str, str] = {}
    for entry in entries:
        name = str(entry.get("name", "")).strip().lower()
        category = str(entry.get("item_category", "")).strip().lower()
        if name and category:
            lookup[name] = category
    return lookup


def _candidate_base_types(base: Item) -> set[str]:
    """Return all runeword-matching type labels that could apply to *base*."""
    candidates: set[str] = set()

    slot = (base.slot or "").strip().lower()
    if slot:
        candidates.add(slot)

    aliases = {
        "body": "body_armour",
        "helmet": "helm",
    }
    alias = aliases.get(slot)
    if alias:
        candidates.add(alias)

    base_name = (base.base or base.name or "").strip().lower()
    if base_name:
        candidates.add(base_name)

    category = _base_category_lookup().get(base_name)
    if category:
        candidates.add(category)

        if category in {"paladin_shield", "necromancer_shield"}:
            candidates.add("shield")

        if category in _MELEE_WEAPON_CATEGORIES:
            candidates.add("weapon")
            candidates.add("melee_weapon")

        if category in _MISSILE_WEAPON_CATEGORIES:
            candidates.add("weapon")
            candidates.add("missile_weapon")

    if slot == "weapon":
        candidates.add("weapon")
    if slot == "shield":
        candidates.add("shield")

    return candidates


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

            # Match against canonical base categories, slot aliases, and the
            # literal base name so inventory entries do not need to use
            # runeword YAML taxonomy terms verbatim.
            base_types_lower = [bt.lower() for bt in base_types]
            candidate_types = _candidate_base_types(base)
            if not any(candidate in base_types_lower for candidate in candidate_types):
                continue

            results.append(
                {
                    "recipe": recipe,
                    "base": base,
                    "rune_cost": Counter(required),
                }
            )

    return results
