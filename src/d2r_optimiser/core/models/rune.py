"""Rune, gem, jewel, and runeword recipe models."""

from sqlmodel import Field, SQLModel


class Rune(SQLModel, table=True):
    """Player's rune pool (fungible — tracked by type + quantity)."""

    id: int | None = Field(default=None, primary_key=True)
    rune_type: str = Field(unique=True)  # "El" / "Eld" / ... / "Zod"
    quantity: int = 0


class Gem(SQLModel, table=True):
    """Player's gem pool (fungible — tracked by name + quantity)."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True)  # "Perfect Topaz" / "Perfect Diamond"
    gem_type: str  # "Topaz" / "Diamond" / ...
    grade: str  # "Perfect" / "Flawless" / ...
    quantity: int = 0


class Jewel(SQLModel, table=True):
    """Individual jewel with unique affix rolls."""

    id: int | None = Field(default=None, primary_key=True)
    uid: str = Field(unique=True)
    quality: str  # magic/rare/crafted
    notes: str | None = None


class JewelAffix(SQLModel, table=True):
    """Affix on a jewel."""

    __tablename__ = "jewelaffix"

    id: int | None = Field(default=None, primary_key=True)
    jewel_id: int = Field(foreign_key="jewel.id", index=True)
    stat: str
    value: float


class RunewordRecipe(SQLModel, table=True):
    """Static runeword recipe (reference data, not player-owned)."""

    __tablename__ = "runewordrecipe"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True)  # "Spirit" / "Enigma" / "Pride"
    rune_sequence: str  # "Tal-Thul-Ort-Amn" (order matters)
    base_types: str  # JSON list of valid base types e.g. '["sword","shield"]'
    socket_count: int
    stats_json: str  # JSON of bonus stats granted by the runeword
