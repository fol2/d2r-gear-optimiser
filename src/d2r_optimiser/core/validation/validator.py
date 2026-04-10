"""Validation engine — compare predicted stats against expected/actual measurements."""

from __future__ import annotations

from sqlmodel import Session, select

from d2r_optimiser.core.models.validation import ValidationRecord


def _compute_deviation_pct(predicted: float, actual: float) -> float:
    """Compute percentage deviation. Handles zero division."""
    if actual == 0.0 and predicted == 0.0:
        return 0.0
    if actual == 0.0:
        return 100.0
    return abs(predicted - actual) / actual * 100.0


def validate_against_reference(
    predicted_stats: dict[str, float],
    expected_stats: dict[str, float],
    tolerance_pct: float = 5.0,
) -> dict:
    """Compare predicted stats against expected reference stats.

    Returns a dict with:
    - ``pass``: True if every stat is within *tolerance_pct*.
    - ``deviations``: per-stat breakdown with predicted/expected/deviation_pct/within_tolerance.
    - ``max_deviation_pct``: the worst deviation across all stats.
    """
    deviations: dict[str, dict] = {}
    max_dev = 0.0

    for stat, expected in expected_stats.items():
        predicted = predicted_stats.get(stat, 0.0)
        dev_pct = _compute_deviation_pct(predicted, expected)
        within = dev_pct <= tolerance_pct
        deviations[stat] = {
            "predicted": predicted,
            "expected": expected,
            "deviation_pct": dev_pct,
            "within_tolerance": within,
        }
        if dev_pct > max_dev:
            max_dev = dev_pct

    all_within = all(d["within_tolerance"] for d in deviations.values())

    return {
        "pass": all_within,
        "deviations": deviations,
        "max_deviation_pct": max_dev,
    }


def record_live_measurement(
    session: Session,
    gear_set_id: str,
    build_def: str,
    predicted: dict[str, float],
    actual: dict[str, float],
    notes: str = "",
) -> ValidationRecord:
    """Record a live in-game measurement to the database.

    Computes deviation between *predicted* and *actual* for each stat pair
    present on :class:`ValidationRecord` (damage, mf, hp, fcr) and stores
    the worst deviation in ``deviation_max``.
    """
    stat_pairs = ["damage", "mf", "hp", "fcr"]
    max_dev = 0.0
    kwargs: dict[str, float | None] = {}

    for stat in stat_pairs:
        pred_val = predicted.get(stat)
        act_val = actual.get(stat)
        kwargs[f"predicted_{stat}"] = pred_val
        kwargs[f"actual_{stat}"] = act_val
        if pred_val is not None and act_val is not None:
            dev = _compute_deviation_pct(pred_val, act_val)
            if dev > max_dev:
                max_dev = dev

    record = ValidationRecord(
        gear_set_id=gear_set_id,
        build_def=build_def,
        deviation_max=max_dev,
        notes=notes or None,
        **kwargs,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def check_all_validations(
    session: Session,
    build_def: str | None = None,
) -> list[dict]:
    """Retrieve all validation records, optionally filtered by *build_def*.

    Returns a list of dicts with record data plus a ``pass`` field indicating
    whether ``deviation_max`` is within the default 5% tolerance.
    """
    stmt = select(ValidationRecord)
    if build_def is not None:
        stmt = stmt.where(ValidationRecord.build_def == build_def)

    records = session.exec(stmt).all()
    results: list[dict] = []
    for rec in records:
        results.append({
            "id": rec.id,
            "gear_set_id": rec.gear_set_id,
            "build_def": rec.build_def,
            "predicted_damage": rec.predicted_damage,
            "actual_damage": rec.actual_damage,
            "predicted_mf": rec.predicted_mf,
            "actual_mf": rec.actual_mf,
            "predicted_hp": rec.predicted_hp,
            "actual_hp": rec.actual_hp,
            "predicted_fcr": rec.predicted_fcr,
            "actual_fcr": rec.actual_fcr,
            "deviation_max": rec.deviation_max,
            "notes": rec.notes,
            "pass": (rec.deviation_max or 0.0) <= 5.0,
        })
    return results
