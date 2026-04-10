"""BuildFormula protocol and factory function."""

import importlib
import inspect
from typing import Protocol, runtime_checkable

from d2r_optimiser.core.models import BuildDefinition, ScoreBreakdown


@runtime_checkable
class BuildFormula(Protocol):
    """Protocol for build-specific scoring. Each build implements this."""

    def compute_damage(self, stats: dict[str, float], build: BuildDefinition) -> float:
        """Compute damage score. stats is {stat_name: value} aggregated across all gear."""
        ...

    def compute_mf(self, stats: dict[str, float], build: BuildDefinition) -> float:
        """Compute magic find score (after diminishing returns)."""
        ...

    def compute_ehp(self, stats: dict[str, float], build: BuildDefinition) -> float:
        """Compute effective HP score."""
        ...

    def compute_breakpoint_score(self, stats: dict[str, float], build: BuildDefinition) -> float:
        """Compute breakpoint attainment score (0-1)."""
        ...

    def score(self, stats: dict[str, float], build: BuildDefinition) -> ScoreBreakdown:
        """Compute full score breakdown."""
        ...


def get_formula(module_name: str) -> BuildFormula:
    """Factory: resolve a formula module name to its implementation.

    Imports ``d2r_optimiser.core.formula.<module_name>`` and looks for a class
    whose name ends with ``Formula`` (convention). Returns an instance.

    Raises ``ImportError`` if the module does not exist.
    Raises ``ValueError`` if no *Formula class is found in the module.
    """
    full_module = f"d2r_optimiser.core.formula.{module_name}"
    try:
        mod = importlib.import_module(full_module)
    except ModuleNotFoundError as exc:
        msg = f"Formula module not found: {full_module}"
        raise ImportError(msg) from exc

    # Find the first class whose name ends with "Formula"
    for _name, obj in inspect.getmembers(mod, inspect.isclass):
        if _name.endswith("Formula") and obj.__module__ == mod.__name__:
            return obj()

    msg = f"No *Formula class found in {full_module}"
    raise ValueError(msg)
