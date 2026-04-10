"""Loader for breakpoint table data from YAML."""

from pathlib import Path

import yaml

from d2r_optimiser.loader._errors import LoaderError


def _validate_threshold_list(entries: list, label: str) -> None:
    """Validate that *entries* is a list of {threshold, frames} dicts."""
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            msg = f"Breakpoint entry {idx} for '{label}' is not a mapping"
            raise LoaderError(msg)
        if "threshold" not in entry or "frames" not in entry:
            msg = f"Breakpoint entry {idx} for '{label}' missing 'threshold' or 'frames'"
            raise LoaderError(msg)


def load_breakpoints(path: Path) -> dict:
    """Load breakpoint tables from a YAML file.

    Returns a nested dict. Most classes use the flat layout::

        {class_name: {stat: [{threshold, frames}, ...]}}

    Some classes (e.g. Druid) have form-specific sub-tables::

        {druid: {fcr: {human: [...], werewolf: [...], werebear: [...]}}}

    Both layouts are accepted. The loader validates that every leaf list
    contains ``{threshold, frames}`` entries.

    Raises ``FileNotFoundError`` if *path* does not exist.
    Raises ``LoaderError`` on malformed data.
    """
    if not path.exists():
        msg = f"Breakpoints file not found: {path}"
        raise FileNotFoundError(msg)

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"Cannot read breakpoints file {path}: {exc}"
        raise LoaderError(msg) from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML in {path}: {exc}"
        raise LoaderError(msg) from exc

    if data is None or not isinstance(data, dict) or "breakpoints" not in data:
        msg = f"Expected top-level 'breakpoints' key in {path}"
        raise LoaderError(msg)

    bp_data = data["breakpoints"]
    if not isinstance(bp_data, dict):
        msg = f"'breakpoints' must be a mapping in {path}"
        raise LoaderError(msg)

    # Validate structure: class -> stat -> (list | form -> list)
    for class_name, stat_tables in bp_data.items():
        if not isinstance(stat_tables, dict):
            msg = (
                f"Breakpoints for class '{class_name}' must be a mapping "
                f"of stat -> list, got {type(stat_tables).__name__}"
            )
            raise LoaderError(msg)

        for stat_name, value in stat_tables.items():
            label = f"{class_name}.{stat_name}"

            if isinstance(value, list):
                # Flat layout: stat -> [{threshold, frames}, ...]
                _validate_threshold_list(value, label)

            elif isinstance(value, dict):
                # Form-specific layout: stat -> {form: [{threshold, frames}, ...]}
                for form_name, form_entries in value.items():
                    form_label = f"{class_name}.{stat_name}.{form_name}"
                    if not isinstance(form_entries, list):
                        msg = (
                            f"Breakpoints for '{form_label}' must be a list, "
                            f"got {type(form_entries).__name__}"
                        )
                        raise LoaderError(msg)
                    _validate_threshold_list(form_entries, form_label)

            else:
                msg = (
                    f"Breakpoints for '{label}' must be a list or mapping, "
                    f"got {type(value).__name__}"
                )
                raise LoaderError(msg)

    return bp_data
