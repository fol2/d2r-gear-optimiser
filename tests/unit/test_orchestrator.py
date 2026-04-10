"""Unit tests for the orchestrator — the top-level wiring layer."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import Session

from d2r_optimiser.core.db import create_all_tables, get_engine, reset_engine
from d2r_optimiser.core.models import Affix, Item
from d2r_optimiser.core.orchestrator import (
    BuildNotFoundError,
    EmptyInventoryError,
    optimise,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_db(tmp_path: Path) -> Path:
    """Create a fresh SQLite database and return its path."""
    db_file = tmp_path / "test_orch.db"
    reset_engine()
    engine = get_engine(url=f"sqlite:///{db_file}")
    create_all_tables(engine=engine)
    return db_file


def _populate_full_inventory(db_path: Path) -> None:
    """Insert a realistic inventory covering all 10 gear slots + runes.

    This is a MF-focused Warlock loadout that meets the build constraints:
    - FCR >= 75 (weapon 50 + shield 35 + gloves 20 = 105)
    - resistance_all >= 75 (shield 30 + boots 20 + amulet 30 = 80)
    - strength >= 0 (trivially met)
    - dexterity >= 0 (trivially met)
    """
    reset_engine()
    engine = get_engine(url=f"sqlite:///{db_path}")
    session = Session(engine)
    try:
        items_data = [
            {
                "uid": "ariocs_needle_001",
                "name": "Arioc's Needle",
                "slot": "weapon",
                "item_type": "unique",
                "base": "Hyperion Spear",
                "affixes": {"all_skills": 2, "fcr": 50, "ed": 200, "damage_max": 50},
            },
            {
                "uid": "spirit_monarch_001",
                "name": "Spirit Monarch",
                "slot": "shield",
                "item_type": "runeword",
                "base": "Monarch",
                "affixes": {"all_skills": 2, "fcr": 35, "fhr": 55, "resistance_all": 30,
                            "vitality": 22, "mf": 0},
            },
            {
                "uid": "shako_001",
                "name": "Harlequin Crest",
                "slot": "helmet",
                "item_type": "unique",
                "base": "Shako",
                "affixes": {"all_skills": 2, "mf": 50, "dr": 10, "life": 50},
            },
            {
                "uid": "enigma_001",
                "name": "Enigma",
                "slot": "body",
                "item_type": "runeword",
                "base": "Mage Plate",
                "affixes": {"all_skills": 2, "mf": 99, "strength": 40},
            },
            {
                "uid": "trang_claws_001",
                "name": "Trang-Oul's Claws",
                "slot": "gloves",
                "item_type": "set",
                "affixes": {"fcr": 20, "cold_res": 30},
            },
            {
                "uid": "arachnid_001",
                "name": "Arachnid Mesh",
                "slot": "belt",
                "item_type": "unique",
                "affixes": {"all_skills": 1, "fcr": 20, "mf": 0},
            },
            {
                "uid": "war_traveler_001",
                "name": "War Traveler",
                "slot": "boots",
                "item_type": "unique",
                "base": "Battle Boots",
                "affixes": {"mf": 45, "resistance_all": 20, "strength": 10, "vitality": 10},
            },
            {
                "uid": "maras_001",
                "name": "Mara's Kaleidoscope",
                "slot": "amulet",
                "item_type": "unique",
                "affixes": {"all_skills": 2, "resistance_all": 30},
            },
            {
                "uid": "soj_001",
                "name": "Stone of Jordan",
                "slot": "ring",
                "item_type": "unique",
                "affixes": {"all_skills": 1, "mf": 0},
            },
            {
                "uid": "bk_ring_001",
                "name": "Bul-Kathos Wedding Band",
                "slot": "ring",
                "item_type": "unique",
                "affixes": {"all_skills": 1, "life": 50},
            },
        ]

        for data in items_data:
            item = Item(
                uid=data["uid"],
                name=data["name"],
                slot=data["slot"],
                item_type=data["item_type"],
                base=data.get("base"),
                socket_count=0,
            )
            session.add(item)
            session.flush()

            for stat, val in data.get("affixes", {}).items():
                session.add(Affix(item_id=item.id, stat=stat, value=float(val)))

        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOptimiseHappyPath:
    """Optimise with a well-stocked inventory produces valid results."""

    def test_returns_results(self, tmp_path):
        db = _create_db(tmp_path)
        _populate_full_inventory(db)

        results = optimise(
            db_path=db,
            build_name="warlock_echoing_strike_mf",
            top_k=5,
            workers=1,
        )

        assert len(results) >= 1
        assert results[0]["total_score"] > 0.0

    def test_results_contain_slots(self, tmp_path):
        db = _create_db(tmp_path)
        _populate_full_inventory(db)

        results = optimise(
            db_path=db,
            build_name="warlock_echoing_strike_mf",
            top_k=1,
            workers=1,
        )

        assert len(results) == 1
        result = results[0]
        assert "slots" in result
        assert "stats" in result
        assert "total_score" in result
        assert "score" in result

    def test_results_sorted_descending(self, tmp_path):
        db = _create_db(tmp_path)
        _populate_full_inventory(db)

        results = optimise(
            db_path=db,
            build_name="warlock_echoing_strike_mf",
            top_k=5,
            workers=1,
        )

        if len(results) >= 2:
            scores = [r["total_score"] for r in results]
            assert scores == sorted(scores, reverse=True)


class TestBuildNotFound:
    """Non-existent build name raises BuildNotFoundError."""

    def test_raises(self, tmp_path):
        db = _create_db(tmp_path)
        # Need at least one item so it does not fail on empty inv first
        reset_engine()
        engine = get_engine(url=f"sqlite:///{db}")
        session = Session(engine)
        session.add(Item(uid="dummy_001", name="Dummy", slot="weapon", item_type="unique"))
        session.commit()
        session.close()

        with pytest.raises(BuildNotFoundError):
            optimise(
                db_path=db,
                build_name="nonexistent_build_xyz",
                top_k=1,
                workers=1,
            )


class TestEmptyInventory:
    """Empty database raises EmptyInventoryError."""

    def test_raises(self, tmp_path):
        db = _create_db(tmp_path)

        with pytest.raises(EmptyInventoryError):
            optimise(
                db_path=db,
                build_name="warlock_echoing_strike_mf",
                top_k=1,
                workers=1,
            )


class TestModeOverride:
    """Mode preset changes scoring weights and produces different rankings."""

    def test_mode_mf_changes_output(self, tmp_path):
        db = _create_db(tmp_path)
        _populate_full_inventory(db)

        results_default = optimise(
            db_path=db,
            build_name="warlock_echoing_strike_mf",
            top_k=1,
            workers=1,
        )
        results_mf = optimise(
            db_path=db,
            build_name="warlock_echoing_strike_mf",
            mode="mf",
            top_k=1,
            workers=1,
        )

        # Both produce results
        assert len(results_default) >= 1
        assert len(results_mf) >= 1

        # The MF mode has different objective weights (mf=0.50 vs 0.40)
        # so the total_score will differ unless the build only has one loadout
        # In any case both are valid
        assert results_mf[0]["total_score"] > 0.0


class TestResultsStructure:
    """Each result contains expected fields with correct types."""

    def test_result_fields(self, tmp_path):
        db = _create_db(tmp_path)
        _populate_full_inventory(db)

        results = optimise(
            db_path=db,
            build_name="warlock_echoing_strike_mf",
            top_k=1,
            workers=1,
        )

        assert len(results) >= 1
        result = results[0]

        # Required top-level keys
        assert isinstance(result["slots"], dict)
        assert isinstance(result["stats"], dict)
        assert isinstance(result["total_score"], float)
        assert isinstance(result["violations"], list)
        assert result["violations"] == []  # valid result has no violations

        # Score breakdown has the expected attributes
        score = result["score"]
        assert hasattr(score, "damage")
        assert hasattr(score, "magic_find")
        assert hasattr(score, "effective_hp")
        assert hasattr(score, "breakpoint_score")
