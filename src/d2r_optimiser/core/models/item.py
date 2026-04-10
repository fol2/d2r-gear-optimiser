"""Core inventory models — Items, Affixes, and Sockets."""

from datetime import datetime

from sqlmodel import Field, SQLModel

from d2r_optimiser.core.models._common import utcnow


class Item(SQLModel, table=True):
    """A physical item in the player's inventory."""

    id: int | None = Field(default=None, primary_key=True)
    uid: str = Field(unique=True, index=True)  # user-friendly ID e.g. "shako_001"
    slot: str = Field(index=True)  # helmet/body/shield/weapon/gloves/belt/boots/amulet/ring/charm
    item_type: str  # unique/set/runeword/rare/magic/crafted
    name: str  # "Harlequin Crest" / "Spirit"
    base: str | None = None  # "Shako" / "Monarch" / "Thunder Maul"
    item_level: int | None = None
    ethereal: bool = False
    socket_count: int = 0
    location: str | None = None  # stash/equipped/mule1/...
    notes: str | None = None
    created_at: datetime | None = Field(default_factory=utcnow)
    updated_at: datetime | None = Field(default_factory=utcnow)


class Affix(SQLModel, table=True):
    """A single stat on an item (EAV pattern — D2R has 200+ possible affixes)."""

    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", index=True)
    stat: str = Field(index=True)  # "mf" / "fcr" / "all_skills" / "ed" / "damage_max" etc.
    value: float
    is_implicit: bool = False  # base-item implicit vs explicit affix


class Socket(SQLModel, table=True):
    """A socket slot in an item, optionally filled with a rune/jewel/gem."""

    id: int | None = Field(default=None, primary_key=True)
    item_id: int = Field(foreign_key="item.id", index=True)
    socket_index: int  # 0, 1, 2, ...
    filled_with: str | None = None  # "Ist" / "Perfect Topaz" / jewel uid
