"""Loader for set item definitions and their bonus tables from YAML."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from d2r_optimiser.loader._errors import LoaderError


@dataclass(frozen=True)
class SetItemDefinition:
    """Static metadata for one set item entry."""

    name: str
    base: str | None
    slot: str
    item_partial_bonus: dict[int, dict[str, float]]


@dataclass(frozen=True)
class SetDefinition:
    """Static metadata for one set, including threshold bonuses."""

    set_name: str
    class_affinity: str
    items: tuple[SetItemDefinition, ...]
    partial_bonuses: dict[int, dict[str, float]]
    full_bonus: dict[str, float]


def _coerce_stat_map(raw: object, *, context: str) -> dict[str, float]:
    """Convert a YAML mapping into ``{stat: float}``."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        msg = f"{context} must be a mapping"
        raise LoaderError(msg)

    stats: dict[str, float] = {}
    for stat, value in raw.items():
        if isinstance(value, bool):
            stats[str(stat)] = 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            stats[str(stat)] = float(value)
        else:
            msg = f"{context}.{stat} must be numeric or boolean"
            raise LoaderError(msg)
    return stats


def _coerce_threshold_map(
    raw: object,
    *,
    context: str,
    full_threshold: int | None = None,
) -> dict[int, dict[str, float]]:
    """Convert a threshold bonus mapping into ``{count: {stat: value}}``."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        msg = f"{context} must be a mapping"
        raise LoaderError(msg)

    result: dict[int, dict[str, float]] = {}
    for threshold, stats in raw.items():
        if isinstance(threshold, str) and threshold.strip().lower() == "full":
            if full_threshold is None:
                msg = f"{context} uses 'full' but no set size is available"
                raise LoaderError(msg)
            threshold_int = full_threshold
        else:
            try:
                threshold_int = int(threshold)
            except (TypeError, ValueError) as exc:
                msg = f"{context} has non-numeric threshold: {threshold!r}"
                raise LoaderError(msg) from exc
        result[threshold_int] = _coerce_stat_map(
            stats,
            context=f"{context}.{threshold_int}",
        )
    return result


def load_sets(path: Path) -> list[SetDefinition]:
    """Load set definitions from ``data/sets.yaml``."""
    if not path.exists():
        msg = f"Sets file not found: {path}"
        raise FileNotFoundError(msg)

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"Cannot read sets file {path}: {exc}"
        raise LoaderError(msg) from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML in {path}: {exc}"
        raise LoaderError(msg) from exc

    if data is None:
        return []

    if not isinstance(data, dict) or "sets" not in data:
        msg = f"Expected top-level 'sets' key in {path}"
        raise LoaderError(msg)

    entries = data["sets"]
    if entries is None:
        return []
    if not isinstance(entries, list):
        msg = f"'sets' must be a list in {path}"
        raise LoaderError(msg)

    results: list[SetDefinition] = []
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            msg = f"Set entry {idx} is not a mapping in {path}"
            raise LoaderError(msg)

        set_name = entry.get("set_name")
        items_raw = entry.get("items")
        if not set_name or not isinstance(set_name, str):
            msg = f"Set entry {idx} missing string 'set_name'"
            raise LoaderError(msg)
        if not isinstance(items_raw, list) or not items_raw:
            msg = f"Set '{set_name}' must define a non-empty 'items' list"
            raise LoaderError(msg)
        set_size = len(items_raw)

        items: list[SetItemDefinition] = []
        for item_idx, item_entry in enumerate(items_raw):
            if not isinstance(item_entry, dict):
                msg = f"Set '{set_name}' item {item_idx} is not a mapping"
                raise LoaderError(msg)
            for field in ("name", "slot"):
                if field not in item_entry:
                    msg = f"Set '{set_name}' item {item_idx} missing required field: {field}"
                    raise LoaderError(msg)
            items.append(
                SetItemDefinition(
                    name=str(item_entry["name"]),
                    base=str(item_entry["base"]) if item_entry.get("base") is not None else None,
                    slot=str(item_entry["slot"]),
                    item_partial_bonus=_coerce_threshold_map(
                        item_entry.get("item_partial_bonus"),
                        context=f"{set_name}.items[{item_idx}].item_partial_bonus",
                        full_threshold=set_size,
                    ),
                )
            )

        results.append(
            SetDefinition(
                set_name=set_name,
                class_affinity=str(entry.get("class_affinity", "none")),
                items=tuple(items),
                partial_bonuses=_coerce_threshold_map(
                    entry.get("partial_bonuses"),
                    context=f"{set_name}.partial_bonuses",
                    full_threshold=set_size,
                ),
                full_bonus=_coerce_stat_map(
                    entry.get("full_bonus"),
                    context=f"{set_name}.full_bonus",
                ),
            )
        )

    return results
