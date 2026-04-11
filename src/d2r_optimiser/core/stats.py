"""Shared stat normalisation and merging helpers."""

from __future__ import annotations

from collections.abc import Mapping

_STAT_ALIASES = {
    "resist_all": "resistance_all",
    "resist_fire": "fire_res",
    "resist_cold": "cold_res",
    "resist_lightning": "light_res",
    "lightning_res": "light_res",
    "resist_poison": "poison_res",
    "ll": "life_leech",
    "ml": "mana_leech",
    "mdr": "magic_damage_reduced",
}


def canonical_stat_name(stat: str) -> str:
    """Return the canonical internal name for a stat key."""
    return _STAT_ALIASES.get(stat, stat)


def merge_stats(target: dict[str, float], source: Mapping[str, float]) -> dict[str, float]:
    """Add *source* stats into *target* using canonical stat names."""
    for stat, value in source.items():
        canonical = canonical_stat_name(stat)
        target[canonical] = target.get(canonical, 0.0) + float(value)
    return target


def normalise_stats(stats: Mapping[str, float]) -> dict[str, float]:
    """Return a new stat mapping with canonical names and merged aliases."""
    result: dict[str, float] = {}
    return merge_stats(result, stats)
