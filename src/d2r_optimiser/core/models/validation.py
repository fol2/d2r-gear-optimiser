"""Validation models — predicted vs actual measurements for formula calibration."""

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(UTC)


class ValidationRecord(SQLModel, table=True):
    """A live measurement from in-game for formula calibration."""

    __tablename__ = "validationrecord"

    id: int | None = Field(default=None, primary_key=True)
    gear_set_id: str  # user-defined label
    build_def: str
    predicted_damage: float | None = None
    actual_damage: float | None = None
    predicted_mf: float | None = None
    actual_mf: float | None = None
    predicted_hp: float | None = None
    actual_hp: float | None = None
    predicted_fcr: float | None = None
    actual_fcr: float | None = None
    deviation_max: float | None = None  # worst deviation across all stats
    notes: str | None = None
    created_at: datetime | None = Field(default_factory=_utcnow)
