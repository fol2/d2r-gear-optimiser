"""Loader for build definition YAML files."""

from pathlib import Path

import yaml

from d2r_optimiser.core.models import BuildDefinition
from d2r_optimiser.loader._errors import LoaderError


def load_build(path: Path) -> BuildDefinition:
    """Load a single build definition from a YAML file.

    Returns a validated ``BuildDefinition`` Pydantic model.
    Raises ``FileNotFoundError`` if *path* does not exist.
    Raises ``LoaderError`` on YAML parse failures.
    Raises ``pydantic.ValidationError`` on schema/constraint violations
    (e.g. weights not summing to 1.0, missing required fields).
    """
    if not path.exists():
        msg = f"Build file not found: {path}"
        raise FileNotFoundError(msg)

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"Cannot read build file {path}: {exc}"
        raise LoaderError(msg) from exc

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML in {path}: {exc}"
        raise LoaderError(msg) from exc

    if data is None or not isinstance(data, dict):
        msg = f"Build file {path} must contain a YAML mapping"
        raise LoaderError(msg)

    # Pydantic handles field validation and raises ValidationError on problems
    return BuildDefinition(**data)


def list_builds(directory: Path) -> list[str]:
    """List available build names from YAML files in *directory*.

    Returns a sorted list of build names (stem of each ``.yaml`` file).
    Raises ``FileNotFoundError`` if *directory* does not exist.
    """
    if not directory.exists():
        msg = f"Builds directory not found: {directory}"
        raise FileNotFoundError(msg)

    if not directory.is_dir():
        msg = f"Path is not a directory: {directory}"
        raise LoaderError(msg)

    # Project convention: build files use .yaml extension (not .yml)
    return sorted(p.stem for p in directory.glob("*.yaml"))
