"""Import all table models to ensure they are registered with SQLModel metadata.

This module must be imported before calling ``create_all_tables()`` so that
SQLModel.metadata contains every table definition.
"""

from d2r_optimiser.core.models.item import Affix, Item, Socket  # noqa: F401
from d2r_optimiser.core.models.loadout import Loadout, LoadoutItem  # noqa: F401
from d2r_optimiser.core.models.rune import (  # noqa: F401
    Gem,
    Jewel,
    JewelAffix,
    Rune,
    RunewordRecipe,
)
from d2r_optimiser.core.models.validation import ValidationRecord  # noqa: F401
