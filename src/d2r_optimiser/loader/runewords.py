"""Loader for runeword recipe data from YAML."""

import json
from pathlib import Path

import yaml

from d2r_optimiser.core.models import RunewordRecipe
from d2r_optimiser.loader._errors import LoaderError


def load_runewords(path: Path) -> list[RunewordRecipe]:
    """Load runeword recipes from a YAML file.

    Returns a list of ``RunewordRecipe`` models (not DB-persisted).
    Raises ``LoaderError`` with context on malformed entries.
    Raises ``FileNotFoundError`` if *path* does not exist.
    """
    if not path.exists():
        msg = f"Runewords file not found: {path}"
        raise FileNotFoundError(msg)

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"Cannot read runewords file {path}: {exc}"
        raise LoaderError(msg) from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML in {path}: {exc}"
        raise LoaderError(msg) from exc

    if data is None:
        return []

    if not isinstance(data, dict) or "runewords" not in data:
        msg = f"Expected top-level 'runewords' key in {path}"
        raise LoaderError(msg)

    entries = data["runewords"]
    if entries is None:
        return []

    if not isinstance(entries, list):
        msg = f"'runewords' must be a list in {path}"
        raise LoaderError(msg)

    required_fields = {"name", "rune_sequence", "socket_count", "base_types", "stats"}
    recipes: list[RunewordRecipe] = []

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            msg = f"Runeword entry {idx} is not a mapping in {path}"
            raise LoaderError(msg)

        missing = required_fields - entry.keys()
        if missing:
            entry_name = entry.get("name", f"<index {idx}>")
            msg = f"Runeword '{entry_name}' missing required fields: {sorted(missing)}"
            raise LoaderError(msg)

        rune_seq = entry["rune_sequence"]
        if not isinstance(rune_seq, list) or not rune_seq:
            entry_name = entry.get("name", f"<index {idx}>")
            msg = f"Runeword '{entry_name}': rune_sequence must be a non-empty list"
            raise LoaderError(msg)

        recipe = RunewordRecipe(
            name=entry["name"],
            rune_sequence="-".join(str(r) for r in rune_seq),
            base_types=json.dumps(entry["base_types"]),
            socket_count=int(entry["socket_count"]),
            stats_json=json.dumps(entry["stats"]),
        )
        recipes.append(recipe)

    return recipes
