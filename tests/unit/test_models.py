"""Tests for domain models and DB layer."""

import json

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from d2r_optimiser.core.models import (
    Affix,
    BuildDefinition,
    Constraint,
    Gem,
    Item,
    Jewel,
    JewelAffix,
    Loadout,
    LoadoutItem,
    ObjectiveWeights,
    Rune,
    RunewordRecipe,
    Socket,
    ValidationRecord,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine():
    """In-memory SQLite engine with all tables created."""
    eng = create_engine("sqlite://", echo=False)
    # Importing schema module ensures all table models are registered
    import d2r_optimiser.core.db.schema  # noqa: F401

    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine):
    """Yield a fresh session bound to the in-memory engine."""
    with Session(engine) as sess:
        yield sess


# ---------------------------------------------------------------------------
# 1. Item can be created with all fields
# ---------------------------------------------------------------------------


class TestItemModel:
    def test_create_item_all_fields(self):
        item = Item(
            uid="shako_001",
            slot="helmet",
            item_type="unique",
            name="Harlequin Crest",
            base="Shako",
            item_level=87,
            ethereal=False,
            socket_count=1,
            location="stash",
            notes="Perfect roll",
        )
        assert item.uid == "shako_001"
        assert item.slot == "helmet"
        assert item.item_type == "unique"
        assert item.name == "Harlequin Crest"
        assert item.base == "Shako"
        assert item.item_level == 87
        assert item.ethereal is False
        assert item.socket_count == 1
        assert item.location == "stash"
        assert item.notes == "Perfect roll"
        assert item.created_at is not None
        assert item.updated_at is not None

    def test_item_defaults(self):
        item = Item(uid="spirit_001", slot="shield", item_type="runeword", name="Spirit")
        assert item.base is None
        assert item.item_level is None
        assert item.ethereal is False
        assert item.socket_count == 0
        assert item.location is None
        assert item.notes is None


# ---------------------------------------------------------------------------
# 2. Affix links to Item via item_id
# ---------------------------------------------------------------------------


class TestAffixModel:
    def test_affix_creation(self):
        affix = Affix(item_id=1, stat="mf", value=50.0, is_implicit=False)
        assert affix.item_id == 1
        assert affix.stat == "mf"
        assert affix.value == 50.0
        assert affix.is_implicit is False

    def test_affix_implicit_flag(self):
        affix = Affix(item_id=1, stat="defence", value=141.0, is_implicit=True)
        assert affix.is_implicit is True


# ---------------------------------------------------------------------------
# 3. Socket links to Item via item_id
# ---------------------------------------------------------------------------


class TestSocketModel:
    def test_socket_creation(self):
        sock = Socket(item_id=1, socket_index=0, filled_with="Ist")
        assert sock.item_id == 1
        assert sock.socket_index == 0
        assert sock.filled_with == "Ist"

    def test_socket_empty(self):
        sock = Socket(item_id=1, socket_index=1)
        assert sock.filled_with is None


# ---------------------------------------------------------------------------
# 4. Rune tracks quantity
# ---------------------------------------------------------------------------


class TestRuneModel:
    def test_rune_quantity(self):
        rune = Rune(rune_type="Ist", quantity=3)
        assert rune.rune_type == "Ist"
        assert rune.quantity == 3

    def test_rune_default_quantity(self):
        rune = Rune(rune_type="Zod")
        assert rune.quantity == 0


# ---------------------------------------------------------------------------
# 5. Gem pool
# ---------------------------------------------------------------------------


class TestGemModel:
    def test_gem_quantity(self):
        gem = Gem(name="Perfect Topaz", gem_type="Topaz", grade="Perfect", quantity=4)
        assert gem.name == "Perfect Topaz"
        assert gem.gem_type == "Topaz"
        assert gem.grade == "Perfect"
        assert gem.quantity == 4

    def test_gem_default_quantity(self):
        gem = Gem(name="Perfect Diamond", gem_type="Diamond", grade="Perfect")
        assert gem.quantity == 0

    def test_gem_pool_in_db(self, session):
        session.add(Gem(name="Perfect Skull", gem_type="Skull", grade="Perfect", quantity=3))
        session.commit()

        skull = session.exec(select(Gem).where(Gem.name == "Perfect Skull")).one()
        assert skull.quantity == 3


# ---------------------------------------------------------------------------
# 6. Jewel + JewelAffix relationship
# ---------------------------------------------------------------------------


class TestJewelModels:
    def test_jewel_creation(self):
        jewel = Jewel(uid="jewel_001", quality="rare", notes="15 IAS / 40 ED")
        assert jewel.uid == "jewel_001"
        assert jewel.quality == "rare"
        assert jewel.notes == "15 IAS / 40 ED"

    def test_jewel_affix_creation(self):
        affix = JewelAffix(jewel_id=1, stat="ias", value=15.0)
        assert affix.jewel_id == 1
        assert affix.stat == "ias"
        assert affix.value == 15.0

    def test_jewel_affix_in_db(self, session):
        jewel = Jewel(uid="jewel_db_001", quality="magic")
        session.add(jewel)
        session.commit()
        session.refresh(jewel)

        ja1 = JewelAffix(jewel_id=jewel.id, stat="ed", value=40.0)
        ja2 = JewelAffix(jewel_id=jewel.id, stat="ias", value=15.0)
        session.add_all([ja1, ja2])
        session.commit()

        affixes = session.exec(
            select(JewelAffix).where(JewelAffix.jewel_id == jewel.id)
        ).all()
        assert len(affixes) == 2
        stats = {a.stat for a in affixes}
        assert stats == {"ed", "ias"}


# ---------------------------------------------------------------------------
# 7. RunewordRecipe stores/retrieves JSON fields correctly
# ---------------------------------------------------------------------------


class TestRunewordRecipe:
    def test_json_fields(self):
        recipe = RunewordRecipe(
            name="Spirit",
            rune_sequence="Tal-Thul-Ort-Amn",
            base_types=json.dumps(["sword", "shield"]),
            socket_count=4,
            stats_json=json.dumps({"fcr": 35, "all_resist": 35, "vitality": 22}),
        )
        assert recipe.name == "Spirit"
        bases = json.loads(recipe.base_types)
        assert bases == ["sword", "shield"]
        stats = json.loads(recipe.stats_json)
        assert stats["fcr"] == 35

    def test_runeword_recipe_in_db(self, session):
        recipe = RunewordRecipe(
            name="Enigma",
            rune_sequence="Jah-Ith-Ber",
            base_types=json.dumps(["body armour"]),
            socket_count=3,
            stats_json=json.dumps({"teleport": 1, "strength": 0.75}),
        )
        session.add(recipe)
        session.commit()
        session.refresh(recipe)

        fetched = session.exec(
            select(RunewordRecipe).where(RunewordRecipe.name == "Enigma")
        ).one()
        assert json.loads(fetched.stats_json)["teleport"] == 1


# ---------------------------------------------------------------------------
# 8. BuildDefinition validates from a sample dict (Pydantic validation)
# ---------------------------------------------------------------------------


_SAMPLE_BUILD = {
    "name": "warlock_echoing_strike",
    "display_name": "Warlock — Echoing Strike",
    "character_class": "warlock",
    "description": "MF-focused echoing-strike warlock build.",
    "formula_module": "warlock_echoing_strike",
    "skill_points": {"echoing_strike": 20, "fire_mastery": 20},
    "objectives": {
        "damage": 0.4, "magic_find": 0.4, "effective_hp": 0.15, "breakpoint_score": 0.05,
    },
    "constraints": [
        {"stat": "fcr", "operator": ">=", "value": 105},
        {"stat": "resistance_all", "operator": ">=", "value": 75},
    ],
    "presets": {
        "mf": {"damage": 0.2, "magic_find": 0.6, "effective_hp": 0.15, "breakpoint_score": 0.05},
        "dps": {"damage": 0.7, "magic_find": 0.1, "effective_hp": 0.15, "breakpoint_score": 0.05},
    },
}


class TestBuildDefinition:
    def test_from_dict(self):
        build = BuildDefinition(**_SAMPLE_BUILD)
        assert build.name == "warlock_echoing_strike"
        assert build.character_class == "warlock"
        assert len(build.constraints) == 2
        assert build.constraints[0].stat == "fcr"
        assert build.constraints[0].operator == ">="
        assert build.constraints[0].value == 105
        assert build.presets["mf"].magic_find == 0.6

    def test_validation_rejects_missing_field(self):
        incomplete = {k: v for k, v in _SAMPLE_BUILD.items() if k != "name"}
        with pytest.raises(Exception):
            BuildDefinition(**incomplete)

    def test_constraint_model(self):
        c = Constraint(stat="strength", operator=">=", value=156)
        assert c.stat == "strength"

    def test_reference_loadouts_optional(self):
        build = BuildDefinition(**_SAMPLE_BUILD)
        assert build.reference_loadouts is None


# ---------------------------------------------------------------------------
# 9. ObjectiveWeights defaults sum to ~1.0
# ---------------------------------------------------------------------------


class TestObjectiveWeights:
    def test_defaults_sum_to_one(self):
        w = ObjectiveWeights()
        total = w.damage + w.magic_find + w.effective_hp + w.breakpoint_score
        assert abs(total - 1.0) < 1e-9

    def test_custom_weights(self):
        w = ObjectiveWeights(damage=0.7, magic_find=0.1, effective_hp=0.15, breakpoint_score=0.05)
        assert w.damage == 0.7

    def test_rejects_weights_not_summing_to_one(self):
        with pytest.raises(ValueError, match="must sum to 1.0"):
            ObjectiveWeights(damage=0.9, magic_find=0.9, effective_hp=0.9, breakpoint_score=0.9)


# ---------------------------------------------------------------------------
# 10. Loadout + LoadoutItem relationship
# ---------------------------------------------------------------------------


class TestLoadoutModels:
    def test_loadout_creation(self):
        lo = Loadout(name="mf_run_v1", build_def="warlock_echoing_strike", score=92.5)
        assert lo.name == "mf_run_v1"
        assert lo.score == 92.5

    def test_loadout_item_creation(self):
        li = LoadoutItem(loadout_id=1, item_id=42, slot="helmet")
        assert li.loadout_id == 1
        assert li.slot == "helmet"

    def test_loadout_in_db(self, session):
        item = Item(uid="test_lo_item", slot="helmet", item_type="unique", name="Shako")
        session.add(item)
        session.commit()
        session.refresh(item)

        lo = Loadout(name="test_lo", build_def="test_build")
        session.add(lo)
        session.commit()
        session.refresh(lo)

        li = LoadoutItem(loadout_id=lo.id, item_id=item.id, slot="helmet")
        session.add(li)
        session.commit()

        fetched = session.exec(
            select(LoadoutItem).where(LoadoutItem.loadout_id == lo.id)
        ).all()
        assert len(fetched) == 1
        assert fetched[0].slot == "helmet"


# ---------------------------------------------------------------------------
# 11. ValidationRecord stores predicted vs actual
# ---------------------------------------------------------------------------


class TestValidationRecord:
    def test_validation_record(self):
        vr = ValidationRecord(
            gear_set_id="set_a",
            build_def="warlock_echoing_strike",
            predicted_damage=5000.0,
            actual_damage=4800.0,
            predicted_mf=350.0,
            actual_mf=348.0,
            deviation_max=4.0,
        )
        assert vr.gear_set_id == "set_a"
        assert vr.predicted_damage == 5000.0
        assert vr.actual_damage == 4800.0

    def test_validation_record_in_db(self, session):
        vr = ValidationRecord(
            gear_set_id="db_set",
            build_def="test_build",
            predicted_damage=1000.0,
            actual_damage=980.0,
        )
        session.add(vr)
        session.commit()
        session.refresh(vr)

        fetched = session.exec(
            select(ValidationRecord).where(ValidationRecord.gear_set_id == "db_set")
        ).one()
        assert fetched.predicted_damage == 1000.0
        assert fetched.actual_damage == 980.0
        assert fetched.created_at is not None


# ---------------------------------------------------------------------------
# 12. Create in-memory SQLite DB, create tables, insert Item + Affixes, query back
# ---------------------------------------------------------------------------


class TestDBOperations:
    def test_insert_and_query_item_with_affixes(self, session):
        item = Item(
            uid="monarch_001",
            slot="shield",
            item_type="runeword",
            name="Spirit",
            base="Monarch",
            socket_count=4,
        )
        session.add(item)
        session.commit()
        session.refresh(item)

        affixes = [
            Affix(item_id=item.id, stat="fcr", value=35.0),
            Affix(item_id=item.id, stat="all_resist", value=35.0),
            Affix(item_id=item.id, stat="vitality", value=22.0),
            Affix(item_id=item.id, stat="mana", value=89.0),
        ]
        session.add_all(affixes)
        session.commit()

        # Query back
        fetched_item = session.exec(select(Item).where(Item.uid == "monarch_001")).one()
        assert fetched_item.name == "Spirit"

        fetched_affixes = session.exec(
            select(Affix).where(Affix.item_id == fetched_item.id)
        ).all()
        assert len(fetched_affixes) == 4
        stat_map = {a.stat: a.value for a in fetched_affixes}
        assert stat_map["fcr"] == 35.0
        assert stat_map["mana"] == 89.0

    def test_insert_item_with_sockets(self, session):
        item = Item(
            uid="monarch_002",
            slot="shield",
            item_type="runeword",
            name="Spirit",
            base="Monarch",
            socket_count=4,
        )
        session.add(item)
        session.commit()
        session.refresh(item)

        sockets = [
            Socket(item_id=item.id, socket_index=0, filled_with="Tal"),
            Socket(item_id=item.id, socket_index=1, filled_with="Thul"),
            Socket(item_id=item.id, socket_index=2, filled_with="Ort"),
            Socket(item_id=item.id, socket_index=3, filled_with="Amn"),
        ]
        session.add_all(sockets)
        session.commit()

        fetched = session.exec(
            select(Socket).where(Socket.item_id == item.id)
        ).all()
        assert len(fetched) == 4
        runes = [s.filled_with for s in sorted(fetched, key=lambda s: s.socket_index)]
        assert runes == ["Tal", "Thul", "Ort", "Amn"]

    def test_rune_pool_in_db(self, session):
        session.add(Rune(rune_type="Ist", quantity=5))
        session.add(Rune(rune_type="Ber", quantity=2))
        session.commit()

        ists = session.exec(select(Rune).where(Rune.rune_type == "Ist")).one()
        assert ists.quantity == 5


# ---------------------------------------------------------------------------
# 13. Verify cascade-style delete (delete Item → Affixes cleaned up manually)
#     Note: SQLModel/SQLite does not auto-cascade by default without explicit
#     relationship config. We verify the pattern that consumers must follow.
# ---------------------------------------------------------------------------


class TestDeleteBehaviour:
    def test_delete_item_then_affixes(self, session):
        """Demonstrate that deleting an item and its related affixes works."""
        item = Item(uid="del_001", slot="helmet", item_type="unique", name="Shako")
        session.add(item)
        session.commit()
        session.refresh(item)

        session.add(Affix(item_id=item.id, stat="mf", value=50.0))
        session.add(Affix(item_id=item.id, stat="damage_reduce", value=10.0))
        session.commit()

        # Delete affixes first, then the item
        affixes = session.exec(select(Affix).where(Affix.item_id == item.id)).all()
        assert len(affixes) == 2

        for a in affixes:
            session.delete(a)
        session.delete(item)
        session.commit()

        remaining_items = session.exec(select(Item).where(Item.uid == "del_001")).all()
        remaining_affixes = session.exec(
            select(Affix).where(Affix.item_id == item.id)
        ).all()

        assert len(remaining_items) == 0
        assert len(remaining_affixes) == 0

    def test_sqlite_foreign_key_enforcement(self, engine):
        """Verify FK enforcement is available (SQLite requires PRAGMA)."""
        from sqlalchemy import text

        with Session(engine) as sess:
            # Enable FK enforcement for this connection
            sess.exec(text("PRAGMA foreign_keys = ON"))  # type: ignore[arg-type]

            item = Item(uid="fk_test_001", slot="helmet", item_type="unique", name="Shako")
            sess.add(item)
            sess.commit()
            sess.refresh(item)

            # Add an affix pointing to the item
            sess.add(Affix(item_id=item.id, stat="mf", value=50.0))
            sess.commit()

            # Deleting the item should fail because of FK constraint
            sess.delete(item)
            with pytest.raises(Exception):
                sess.commit()
