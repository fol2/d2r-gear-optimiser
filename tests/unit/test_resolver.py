"""Tests for the resource resolver (runewords + sockets)."""

import json
from collections import Counter

from d2r_optimiser.core.models import Item, Jewel, Rune, RunewordRecipe
from d2r_optimiser.core.resolver import (
    enumerate_craftable_runewords,
    enumerate_socket_options,
)

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _rune(rune_type: str, quantity: int = 1) -> Rune:
    return Rune(rune_type=rune_type, quantity=quantity)


def _base(
    uid: str,
    slot: str,
    socket_count: int,
    *,
    item_type: str = "normal",
    base: str | None = None,
    name: str = "",
) -> Item:
    return Item(
        uid=uid,
        slot=slot,
        item_type=item_type,
        name=name or uid,
        base=base,
        socket_count=socket_count,
    )


def _recipe(
    name: str,
    rune_sequence: str,
    base_types: list[str],
    socket_count: int,
) -> RunewordRecipe:
    return RunewordRecipe(
        name=name,
        rune_sequence=rune_sequence,
        base_types=json.dumps(base_types),
        socket_count=socket_count,
        stats_json=json.dumps({}),
    )


def _jewel(uid: str) -> Jewel:
    return Jewel(uid=uid, quality="rare")


# ===========================================================================
# Runeword resolver tests
# ===========================================================================


class TestEnumerateCraftableRunewords:
    """Tests for enumerate_craftable_runewords."""

    # -- happy path --

    def test_enigma_craftable(self):
        """Pool [Jah, Ith, Ber] + Mage Plate (3os body_armour) -> Enigma."""
        pool = [_rune("Jah"), _rune("Ith"), _rune("Ber")]
        bases = [_base("mp_001", "body_armour", 3, base="Mage Plate")]
        recipes = [_recipe("Enigma", "Jah-Ith-Ber", ["body_armour"], 3)]

        results = enumerate_craftable_runewords(pool, bases, recipes)

        assert len(results) == 1
        assert results[0]["recipe"].name == "Enigma"
        assert results[0]["base"].uid == "mp_001"

    def test_multiple_bases(self):
        """Same recipe, multiple valid bases -> one result per base."""
        pool = [_rune("Jah"), _rune("Ith"), _rune("Ber")]
        bases = [
            _base("mp_001", "body_armour", 3, base="Mage Plate"),
            _base("ap_001", "body_armour", 3, base="Archon Plate"),
        ]
        recipes = [_recipe("Enigma", "Jah-Ith-Ber", ["body_armour"], 3)]

        results = enumerate_craftable_runewords(pool, bases, recipes)

        assert len(results) == 2
        uids = {r["base"].uid for r in results}
        assert uids == {"mp_001", "ap_001"}

    def test_rune_cost_tracking(self):
        """Verify rune_cost counter in output is correct."""
        pool = [_rune("Jah"), _rune("Ith"), _rune("Ber")]
        bases = [_base("mp_001", "body_armour", 3)]
        recipes = [_recipe("Enigma", "Jah-Ith-Ber", ["body_armour"], 3)]

        results = enumerate_craftable_runewords(pool, bases, recipes)

        assert len(results) == 1
        cost = results[0]["rune_cost"]
        assert isinstance(cost, Counter)
        assert cost == Counter({"Jah": 1, "Ith": 1, "Ber": 1})

    # -- rejection cases --

    def test_enigma_missing_rune(self):
        """Pool [Jah, Ith] (no Ber) -> Enigma not craftable."""
        pool = [_rune("Jah"), _rune("Ith")]
        bases = [_base("mp_001", "body_armour", 3)]
        recipes = [_recipe("Enigma", "Jah-Ith-Ber", ["body_armour"], 3)]

        results = enumerate_craftable_runewords(pool, bases, recipes)

        assert len(results) == 0

    def test_wrong_base_type(self):
        """Pool has runes but base is wrong type -> empty."""
        pool = [_rune("Jah"), _rune("Ith"), _rune("Ber")]
        bases = [_base("mon_001", "shield", 3, base="Monarch")]
        recipes = [_recipe("Enigma", "Jah-Ith-Ber", ["body_armour"], 3)]

        results = enumerate_craftable_runewords(pool, bases, recipes)

        assert len(results) == 0

    def test_insufficient_sockets(self):
        """Base has fewer sockets than recipe needs -> empty."""
        pool = [_rune("Jah"), _rune("Ith"), _rune("Ber")]
        bases = [_base("mp_001", "body_armour", 2)]  # only 2 sockets
        recipes = [_recipe("Enigma", "Jah-Ith-Ber", ["body_armour"], 3)]

        results = enumerate_craftable_runewords(pool, bases, recipes)

        assert len(results) == 0

    def test_base_already_runeword(self):
        """Base with item_type='runeword' is excluded."""
        pool = [_rune("Tal"), _rune("Thul"), _rune("Ort"), _rune("Amn")]
        bases = [_base("spirit_001", "shield", 4, item_type="runeword", name="Spirit")]
        recipes = [_recipe("Spirit", "Tal-Thul-Ort-Amn", ["shield"], 4)]

        results = enumerate_craftable_runewords(pool, bases, recipes)

        assert len(results) == 0

    def test_duplicate_rune_requirement(self):
        """Recipe needing 2x same rune, pool has only 1 -> fails."""
        pool = [_rune("Cham", quantity=1), _rune("Shael")]
        bases = [_base("helm_001", "helmet", 2)]
        # Splendor needs two runes; let's use a hypothetical 2x-Cham recipe
        recipes = [_recipe("TestDouble", "Cham-Cham", ["helmet"], 2)]

        results = enumerate_craftable_runewords(pool, bases, recipes)

        assert len(results) == 0

    def test_duplicate_rune_requirement_sufficient(self):
        """Recipe needing 2x same rune, pool has 2 -> succeeds."""
        pool = [_rune("Cham", quantity=2)]
        bases = [_base("helm_001", "helmet", 2)]
        recipes = [_recipe("TestDouble", "Cham-Cham", ["helmet"], 2)]

        results = enumerate_craftable_runewords(pool, bases, recipes)

        assert len(results) == 1
        assert results[0]["rune_cost"] == Counter({"Cham": 2})

    # -- edge cases --

    def test_empty_rune_pool(self):
        """Empty rune pool -> empty results."""
        bases = [_base("mp_001", "body_armour", 3)]
        recipes = [_recipe("Enigma", "Jah-Ith-Ber", ["body_armour"], 3)]

        results = enumerate_craftable_runewords([], bases, recipes)

        assert len(results) == 0

    def test_empty_bases(self):
        """Empty bases -> empty results."""
        pool = [_rune("Jah"), _rune("Ith"), _rune("Ber")]
        recipes = [_recipe("Enigma", "Jah-Ith-Ber", ["body_armour"], 3)]

        results = enumerate_craftable_runewords(pool, [], recipes)

        assert len(results) == 0

    def test_empty_recipes(self):
        """Empty recipes list -> empty results."""
        pool = [_rune("Jah"), _rune("Ith"), _rune("Ber")]
        bases = [_base("mp_001", "body_armour", 3)]

        results = enumerate_craftable_runewords(pool, bases, [])

        assert len(results) == 0

    def test_case_insensitive_base_type_matching(self):
        """Base type matching is case-insensitive."""
        pool = [_rune("Jah"), _rune("Ith"), _rune("Ber")]
        bases = [_base("mp_001", "Body_Armour", 3)]
        recipes = [_recipe("Enigma", "Jah-Ith-Ber", ["body_armour"], 3)]

        results = enumerate_craftable_runewords(pool, bases, recipes)

        assert len(results) == 1

    def test_multiple_recipes_mixed(self):
        """Multiple recipes where some are craftable and some are not."""
        pool = [_rune("Jah"), _rune("Ith"), _rune("Ber")]
        bases = [_base("mp_001", "body_armour", 3)]
        recipes = [
            _recipe("Enigma", "Jah-Ith-Ber", ["body_armour"], 3),
            _recipe("Spirit", "Tal-Thul-Ort-Amn", ["shield"], 4),
        ]

        results = enumerate_craftable_runewords(pool, bases, recipes)

        assert len(results) == 1
        assert results[0]["recipe"].name == "Enigma"


# ===========================================================================
# Socket filler resolver tests
# ===========================================================================


class TestEnumerateSocketOptions:
    """Tests for enumerate_socket_options."""

    def test_no_empty_sockets(self):
        """Item with 0 sockets -> returns [[]]."""
        item = _base("shako_001", "helmet", 0)

        result = enumerate_socket_options(item, [], [])

        assert result == [[]]

    def test_single_socket_two_runes(self):
        """1 empty socket, pool [Ist, Um] -> returns [["Ist"], ["Um"]]."""
        item = _base("helm_001", "helmet", 1)
        pool = [_rune("Ist"), _rune("Um")]

        result = enumerate_socket_options(item, pool, [])

        assert len(result) == 2
        assert ["Ist"] in result
        assert ["Um"] in result

    def test_multi_socket(self):
        """2 empty sockets, pool [Ist x2, Um] -> multiple combos."""
        item = _base("helm_001", "helmet", 2)
        pool = [_rune("Ist", quantity=2), _rune("Um")]

        result = enumerate_socket_options(item, pool, [])

        # Combinations with replacement from {Ist, Um}, size 2:
        # (Ist, Ist) - valid, we have 2 Ist
        # (Ist, Um)  - valid
        # (Um, Um)   - invalid, only 1 Um
        assert len(result) == 2
        assert ["Ist", "Ist"] in result
        assert ["Ist", "Um"] in result

    def test_jewel_in_pool(self):
        """Jewels are included as candidates."""
        item = _base("helm_001", "helmet", 1)
        jewels = [_jewel("jewel_40ed_15ias")]

        result = enumerate_socket_options(item, [], jewels)

        assert len(result) == 1
        assert result[0] == ["jewel_40ed_15ias"]

    def test_mixed_runes_and_jewels(self):
        """Both runes and jewels in the pool."""
        item = _base("helm_001", "helmet", 1)
        pool = [_rune("Ist")]
        jewels = [_jewel("jewel_001")]

        result = enumerate_socket_options(item, pool, jewels)

        assert len(result) == 2
        labels = [r[0] for r in result]
        assert "Ist" in labels
        assert "jewel_001" in labels

    def test_pool_exhaustion(self):
        """Cannot use more runes than available."""
        item = _base("helm_001", "helmet", 2)
        pool = [_rune("Ist", quantity=1)]  # only 1 Ist

        result = enumerate_socket_options(item, pool, [])

        # (Ist, Ist) is invalid -- only 1 available.
        # No single-rune can fill 2 sockets alone -> empty
        assert result == []

    def test_pool_exhaustion_jewels(self):
        """Cannot use same jewel twice (each jewel is unique)."""
        item = _base("helm_001", "helmet", 2)
        jewels = [_jewel("jewel_001")]

        result = enumerate_socket_options(item, [], jewels)

        # (jewel_001, jewel_001) invalid, only 1 copy -> empty
        assert result == []

    def test_max_combinations_cap(self):
        """Large pool capped at max_combinations."""
        item = _base("helm_001", "helmet", 3)
        # 10 runes with qty=3 each -> large combination space
        pool = [_rune(f"Rune{i}", quantity=3) for i in range(10)]

        result = enumerate_socket_options(item, pool, [], max_combinations=20)

        assert len(result) == 20

    def test_empty_pool(self):
        """No runes or jewels available but item has sockets -> returns [[]]."""
        item = _base("helm_001", "helmet", 2)

        result = enumerate_socket_options(item, [], [])

        assert result == [[]]

    def test_zero_quantity_runes_ignored(self):
        """Runes with quantity=0 are not included as candidates."""
        item = _base("helm_001", "helmet", 1)
        pool = [_rune("Ist", quantity=0)]

        result = enumerate_socket_options(item, pool, [])

        assert result == [[]]

    def test_three_sockets_varied_pool(self):
        """3 sockets, pool [Ist x3, Um x1] -> verify correct filtering."""
        item = _base("shield_001", "shield", 3)
        pool = [_rune("Ist", quantity=3), _rune("Um", quantity=1)]

        result = enumerate_socket_options(item, pool, [])

        # Combinations with replacement from {Ist, Um}, size 3:
        # (Ist, Ist, Ist) - valid, 3 Ist available
        # (Ist, Ist, Um)  - valid
        # (Ist, Um, Um)   - invalid, only 1 Um
        # (Um, Um, Um)    - invalid, only 1 Um
        assert len(result) == 2
        assert ["Ist", "Ist", "Ist"] in result
        assert ["Ist", "Ist", "Um"] in result

    def test_single_socket_max_cap_one(self):
        """max_combinations=1 returns at most 1 result."""
        item = _base("helm_001", "helmet", 1)
        pool = [_rune("Ist"), _rune("Um"), _rune("Mal")]

        result = enumerate_socket_options(item, pool, [], max_combinations=1)

        assert len(result) == 1
