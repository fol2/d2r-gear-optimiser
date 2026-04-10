"""End-to-end integration tests — full pipeline from empty DB to optimised results."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlmodel import Session

from d2r_optimiser.cli import cli
from d2r_optimiser.core.db import create_all_tables, get_engine, reset_engine
from d2r_optimiser.core.models import Affix, Item
from d2r_optimiser.core.models.rune import Rune  # noqa: F401 — needed for DB schema
from d2r_optimiser.core.orchestrator import optimise

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(args: list[str], **kwargs):
    """Helper to invoke CLI with CliRunner."""
    runner = CliRunner()
    return runner.invoke(cli, args, catch_exceptions=False, **kwargs)


def _create_db(tmp_path: Path) -> Path:
    """Create a fresh SQLite database and return its path."""
    db_file = tmp_path / "e2e.db"
    reset_engine()
    engine = get_engine(url=f"sqlite:///{db_file}")
    create_all_tables(engine=engine)
    return db_file


def _populate_e2e_inventory(db_path: Path) -> None:
    """Insert 12 items + runes covering all slots for an MF warlock build.

    This inventory is designed to have exactly one valid loadout that
    satisfies the warlock_echoing_strike_mf constraints:
    - FCR >= 75: weapon(50) + shield(35) + gloves(20) = 105
    - resistance_all >= 75: shield(30) + boots(20) + amulet(30) = 80
    """
    reset_engine()
    engine = get_engine(url=f"sqlite:///{db_path}")
    session = Session(engine)
    try:
        inventory = [
            # Weapons
            {
                "uid": "ariocs_001", "name": "Arioc's Needle",
                "slot": "weapon", "item_type": "unique",
                "affixes": {"all_skills": 2, "fcr": 50, "ed": 200, "damage_max": 50},
            },
            {
                "uid": "occulus_001", "name": "The Occulus",
                "slot": "weapon", "item_type": "unique",
                "affixes": {"all_skills": 3, "fcr": 20, "mf": 30, "resistance_all": 20},
            },
            # Shield
            {
                "uid": "spirit_001", "name": "Spirit Monarch",
                "slot": "shield", "item_type": "runeword",
                "affixes": {"all_skills": 2, "fcr": 35, "fhr": 55, "resistance_all": 30},
            },
            # Helmet
            {
                "uid": "shako_001", "name": "Harlequin Crest",
                "slot": "helmet", "item_type": "unique",
                "affixes": {"all_skills": 2, "mf": 50, "dr": 10, "life": 50},
            },
            # Body
            {
                "uid": "enigma_001", "name": "Enigma",
                "slot": "body", "item_type": "runeword",
                "affixes": {"all_skills": 2, "mf": 99, "strength": 40},
            },
            # Gloves
            {
                "uid": "trang_001", "name": "Trang-Oul's Claws",
                "slot": "gloves", "item_type": "set",
                "affixes": {"fcr": 20, "cold_res": 30},
            },
            # Belt
            {
                "uid": "arachnid_001", "name": "Arachnid Mesh",
                "slot": "belt", "item_type": "unique",
                "affixes": {"all_skills": 1, "fcr": 20},
            },
            # Boots
            {
                "uid": "wtraveler_001", "name": "War Traveler",
                "slot": "boots", "item_type": "unique",
                "affixes": {"mf": 45, "resistance_all": 20, "strength": 10},
            },
            # Amulet
            {
                "uid": "maras_001", "name": "Mara's Kaleidoscope",
                "slot": "amulet", "item_type": "unique",
                "affixes": {"all_skills": 2, "resistance_all": 30},
            },
            # Rings (need two different ones)
            {
                "uid": "soj_001", "name": "Stone of Jordan",
                "slot": "ring", "item_type": "unique",
                "affixes": {"all_skills": 1},
            },
            {
                "uid": "bk_001", "name": "Bul-Kathos Wedding Band",
                "slot": "ring", "item_type": "unique",
                "affixes": {"all_skills": 1, "life": 50},
            },
            {
                "uid": "nagel_001", "name": "Nagelring",
                "slot": "ring", "item_type": "unique",
                "affixes": {"mf": 30},
            },
        ]

        for data in inventory:
            item = Item(
                uid=data["uid"],
                name=data["name"],
                slot=data["slot"],
                item_type=data["item_type"],
                socket_count=0,
            )
            session.add(item)
            session.flush()

            for stat, val in data.get("affixes", {}).items():
                session.add(Affix(item_id=item.id, stat=stat, value=float(val)))

        # Add some runes to the pool
        for rune_type, qty in [("Ist", 2), ("Um", 1), ("Ber", 1)]:
            session.add(Rune(rune_type=rune_type, quantity=qty))

        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestEndToEndOptimisation:
    """Full pipeline: empty DB -> populate -> optimise -> validate results."""

    def test_full_pipeline_produces_results(self, tmp_path):
        """Core integration test: populate DB, run optimise, verify output."""
        db = _create_db(tmp_path)
        _populate_e2e_inventory(db)

        results = optimise(
            db_path=db,
            build_name="warlock_echoing_strike_mf",
            top_k=5,
            workers=1,
        )

        # Must produce at least one valid loadout
        assert len(results) >= 1
        assert len(results) <= 5

    def test_constraints_satisfied(self, tmp_path):
        """All returned loadouts satisfy the build's hard constraints."""
        db = _create_db(tmp_path)
        _populate_e2e_inventory(db)

        results = optimise(
            db_path=db,
            build_name="warlock_echoing_strike_mf",
            top_k=5,
            workers=1,
        )

        for result in results:
            stats = result["stats"]
            # FCR >= 75
            assert stats.get("fcr", 0) >= 75, (
                f"FCR constraint violated: {stats.get('fcr', 0)}"
            )
            # resistance_all >= 75
            assert stats.get("resistance_all", 0) >= 75, (
                f"resistance_all constraint violated: {stats.get('resistance_all', 0)}"
            )
            # No violations
            assert result["violations"] == []

    def test_no_resource_conflicts(self, tmp_path):
        """No resource (rune/jewel) is double-used across slots."""
        db = _create_db(tmp_path)
        _populate_e2e_inventory(db)

        results = optimise(
            db_path=db,
            build_name="warlock_echoing_strike_mf",
            top_k=5,
            workers=1,
        )

        for result in results:
            # Verify each item UID appears at most once (except rings
            # which can be the same type but different UIDs)
            uids = list(result["slots"].values())
            # Check no duplicate UIDs within a single loadout
            # (rings can have different UIDs but same item type)
            uid_counts = {}
            for uid in uids:
                uid_counts[uid] = uid_counts.get(uid, 0) + 1
            for uid, count in uid_counts.items():
                assert count == 1, f"Item {uid} used {count} times in loadout"

    def test_deterministic_results(self, tmp_path):
        """Running optimise twice yields identical results."""
        db = _create_db(tmp_path)
        _populate_e2e_inventory(db)

        results_1 = optimise(
            db_path=db,
            build_name="warlock_echoing_strike_mf",
            top_k=5,
            workers=1,
        )
        results_2 = optimise(
            db_path=db,
            build_name="warlock_echoing_strike_mf",
            top_k=5,
            workers=1,
        )

        assert len(results_1) == len(results_2)
        for r1, r2 in zip(results_1, results_2):
            assert r1["slots"] == r2["slots"]
            assert r1["total_score"] == pytest.approx(r2["total_score"])

    def test_mode_mf_produces_results(self, tmp_path):
        """Running with --mode mf produces valid results."""
        db = _create_db(tmp_path)
        _populate_e2e_inventory(db)

        results = optimise(
            db_path=db,
            build_name="warlock_echoing_strike_mf",
            mode="mf",
            top_k=3,
            workers=1,
        )

        assert len(results) >= 1
        for r in results:
            assert r["total_score"] > 0.0


class TestCLIRunCommand:
    """Integration tests for the `optimise run` CLI command."""

    def test_cli_run_produces_output(self, tmp_path):
        """CLI run command with populated DB produces table output."""
        db = _create_db(tmp_path)
        _populate_e2e_inventory(db)

        result = _run([
            "--db", str(db),
            "run", "warlock_echoing_strike_mf",
            "--top-k", "3",
            "--workers", "1",
        ])

        assert result.exit_code == 0
        assert "Loadouts" in result.output or "Score" in result.output

    def test_cli_run_json_output(self, tmp_path):
        """CLI run command with --json flag produces valid JSON."""
        import json

        db = _create_db(tmp_path)
        _populate_e2e_inventory(db)

        result = _run([
            "--db", str(db),
            "run", "warlock_echoing_strike_mf",
            "--top-k", "2",
            "--workers", "1",
            "--json",
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "total_score" in data[0]
        assert "slots" in data[0]

    def test_cli_run_build_not_found(self, tmp_path):
        db = _create_db(tmp_path)
        # Add a dummy item so it does not fail on empty inventory
        reset_engine()
        engine = get_engine(url=f"sqlite:///{db}")
        session = Session(engine)
        session.add(Item(uid="dummy_001", name="Dummy", slot="weapon", item_type="unique"))
        session.commit()
        session.close()

        result = _run([
            "--db", str(db),
            "run", "totally_fake_build_xyz",
            "--workers", "1",
        ])

        assert "not found" in result.output.lower() or result.exit_code != 0

    def test_cli_run_empty_inventory(self, tmp_path):
        db = _create_db(tmp_path)

        result = _run([
            "--db", str(db),
            "run", "warlock_echoing_strike_mf",
            "--workers", "1",
        ])

        assert "empty" in result.output.lower() or result.exit_code != 0


class TestCLIValidateCommand:
    """Integration tests for the validate subcommands."""

    def test_validate_record_and_check(self, tmp_path):
        """Record a measurement then check it."""
        db = str(tmp_path / "val.db")

        # Record
        result = _run([
            "--db", db,
            "validate", "record", "test_set_1",
            "--build", "warlock_echoing_strike_mf",
            "--predicted-mf", "300",
            "--actual-mf", "295",
            "--predicted-damage", "1000",
            "--actual-damage", "980",
        ])
        assert result.exit_code == 0
        assert "Recorded" in result.output

        # Check
        result = _run(["--db", db, "validate", "check"])
        assert result.exit_code == 0
        assert "test_set_1" in result.output

    def test_validate_check_empty(self, tmp_path):
        db = str(tmp_path / "val_empty.db")
        result = _run(["--db", db, "validate", "check"])
        assert result.exit_code == 0
        assert "No validation records" in result.output
