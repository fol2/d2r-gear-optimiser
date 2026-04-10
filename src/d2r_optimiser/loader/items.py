"""Loader for base item type reference data from YAML."""

from pathlib import Path

import yaml

from d2r_optimiser.loader._errors import LoaderError


def load_base_items(path: Path) -> list[dict]:
    """Load base item type data from a YAML file.

    Returns a list of dicts (not ``Item`` models -- base items are
    reference data, not player inventory).
    Raises ``FileNotFoundError`` if *path* does not exist.
    Raises ``LoaderError`` on malformed entries.
    """
    if not path.exists():
        msg = f"Items file not found: {path}"
        raise FileNotFoundError(msg)

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"Cannot read items file {path}: {exc}"
        raise LoaderError(msg) from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML in {path}: {exc}"
        raise LoaderError(msg) from exc

    if data is None:
        return []

    if not isinstance(data, dict) or "items" not in data:
        msg = f"Expected top-level 'items' key in {path}"
        raise LoaderError(msg)

    entries = data["items"]
    if entries is None:
        return []

    if not isinstance(entries, list):
        msg = f"'items' must be a list in {path}"
        raise LoaderError(msg)

    required = {"name", "slot"}
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            msg = f"Item entry {idx} is not a mapping in {path}"
            raise LoaderError(msg)
        missing = required - entry.keys()
        if missing:
            label = entry.get("name", f"#{idx}")
            msg = f"Item '{label}' missing required fields {missing} in {path}"
            raise LoaderError(msg)

    return entries
