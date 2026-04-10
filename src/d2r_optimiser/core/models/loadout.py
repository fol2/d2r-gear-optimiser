"""Optimisation result models — Loadout and scoring."""

from datetime import UTC, datetime

from pydantic import BaseModel
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(UTC)


class ScoreBreakdown(BaseModel):
    """Per-dimension score breakdown."""

    damage: float
    magic_find: float
    effective_hp: float
    breakpoint_score: float


class LoadoutSlot(BaseModel):
    """One slot in a loadout."""

    slot: str
    item_uid: str
    socket_fillings: list[str] | None = None  # what goes in each socket


class Loadout(SQLModel, table=True):
    """A saved optimisation result."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    build_def: str  # which build YAML was targeted
    created_at: datetime | None = Field(default_factory=_utcnow)
    score: float | None = None
    damage: float | None = None
    magic_find: float | None = None
    effective_hp: float | None = None
    notes: str | None = None


class LoadoutItem(SQLModel, table=True):
    """Which items are in each loadout."""

    __tablename__ = "loadoutitem"

    loadout_id: int = Field(foreign_key="loadout.id", primary_key=True)
    item_id: int = Field(foreign_key="item.id")
    slot: str = Field(primary_key=True)
