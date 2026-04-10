"""Domain models — re-export all public models for convenient imports."""

from d2r_optimiser.core.models.build import (
    BuildDefinition,
    Constraint,
    ObjectiveWeights,
)
from d2r_optimiser.core.models.item import Affix, Item, Socket
from d2r_optimiser.core.models.loadout import (
    Loadout,
    LoadoutItem,
    LoadoutSlot,
    ScoreBreakdown,
)
from d2r_optimiser.core.models.rune import Jewel, JewelAffix, Rune, RunewordRecipe
from d2r_optimiser.core.models.validation import ValidationRecord

__all__ = [
    # item.py
    "Item",
    "Affix",
    "Socket",
    # rune.py
    "Rune",
    "Jewel",
    "JewelAffix",
    "RunewordRecipe",
    # build.py
    "BuildDefinition",
    "Constraint",
    "ObjectiveWeights",
    # loadout.py
    "Loadout",
    "LoadoutItem",
    "LoadoutSlot",
    "ScoreBreakdown",
    # validation.py
    "ValidationRecord",
]
