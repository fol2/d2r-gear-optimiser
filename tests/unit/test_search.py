"""Comprehensive tests for the search engine — pruning, exhaustive search,
and parallel execution."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from d2r_optimiser.core.formula.base import get_formula
from d2r_optimiser.core.models import BuildDefinition, Constraint, ObjectiveWeights
from d2r_optimiser.core.search.engine import search
from d2r_optimiser.core.search.parallel import parallel_search
from d2r_optimiser.core.search.pruning import check_hard_constraints, check_resource_conflicts
from d2r_optimiser.loader import load_breakpoints

# ---------------------------------------------------------------------------
# Paths & helpers
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_BREAKPOINTS_PATH = _DATA_DIR / "breakpoints.yaml"


def _make_build(**overrides) -> BuildDefinition:
    """Create a minimal BuildDefinition for tests."""
    defaults = {
        "name": "test_build",
        "display_name": "Test Build",
        "character_class": "warlock",
        "description": "Test build for search unit tests.",
        "formula_module": "warlock_echoing_strike",
        "skill_points": {"echoing_strike": 20},
        "objectives": ObjectiveWeights(
            damage=0.35,
            magic_find=0.40,
            effective_hp=0.15,
            breakpoint_score=0.10,
        ),
        "constraints": [],
        "presets": {},
    }
    defaults.update(overrides)
    return BuildDefinition(**defaults)


def make_candidate(
    uid: str,
    stats: dict | None = None,
    resource_cost: dict | None = None,
    socket_fillings: list[str] | None = None,
    set_meta: dict | None = None,
) -> dict:
    """Build a candidate dict matching the search engine interface."""
    return {
        "item_uid": uid,
        "stats": stats or {},
        "resource_cost": Counter(resource_cost or {}),
        "socket_fillings": socket_fillings,
        "set_meta": set_meta,
    }


def _build_single_candidate_per_slot() -> dict[str, list[dict]]:
    """One candidate per slot — the simplest valid inventory."""
    return {
        "weapon": [make_candidate("weapon_a", {"ed": 100, "all_skills": 2, "fcr": 50})],
        "shield": [make_candidate("shield_a", {"fcr": 35, "resistance_all": 30})],
        "helmet": [make_candidate("helmet_a", {"mf": 50, "all_skills": 2})],
        "body": [make_candidate("body_a", {"mf": 99, "all_skills": 2})],
        "gloves": [make_candidate("gloves_a", {"fcr": 20})],
        "belt": [make_candidate("belt_a", {"mf": 30})],
        "boots": [make_candidate("boots_a", {"mf": 40, "resistance_all": 20})],
        "amulet": [make_candidate("amulet_a", {"all_skills": 2, "resistance_all": 25})],
        "ring1": [make_candidate("ring1_a", {"all_skills": 1, "mf": 10})],
        "ring2": [make_candidate("ring2_a", {"all_skills": 1, "mf": 15})],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def formula():
    """EchoingStrikeFormula with real breakpoint data."""
    bp = load_breakpoints(_BREAKPOINTS_PATH)
    from d2r_optimiser.core.formula.warlock_echoing_strike import EchoingStrikeFormula

    return EchoingStrikeFormula(breakpoints=bp["warlock"])


@pytest.fixture()
def easy_build() -> BuildDefinition:
    """Build with trivially easy constraints (fcr >= 0, resistance_all >= 0)."""
    return _make_build(
        constraints=[
            Constraint(stat="fcr", operator=">=", value=0),
            Constraint(stat="resistance_all", operator=">=", value=0),
        ]
    )


@pytest.fixture()
def strict_build() -> BuildDefinition:
    """Build with strict FCR constraint that most loadouts fail."""
    return _make_build(
        constraints=[
            Constraint(stat="fcr", operator=">=", value=100),
            Constraint(stat="resistance_all", operator=">=", value=75),
        ]
    )


# ===========================================================================
# Pruning tests
# ===========================================================================


class TestCheckHardConstraints:
    """Tests for hard-constraint checking."""

    def test_constraint_violation_detected(self):
        """FCR constraint=75, loadout has FCR=50 -> violation."""
        build = _make_build(
            constraints=[Constraint(stat="fcr", operator=">=", value=75)]
        )
        violations = check_hard_constraints({"fcr": 50.0}, build)
        assert len(violations) == 1
        assert "fcr" in violations[0]

    def test_constraint_satisfied(self):
        """FCR=75 constraint, loadout has FCR=80 -> no violation."""
        build = _make_build(
            constraints=[Constraint(stat="fcr", operator=">=", value=75)]
        )
        violations = check_hard_constraints({"fcr": 80.0}, build)
        assert violations == []

    def test_constraint_exact_boundary(self):
        """FCR >= 75, loadout has exactly 75 -> passes."""
        build = _make_build(
            constraints=[Constraint(stat="fcr", operator=">=", value=75)]
        )
        violations = check_hard_constraints({"fcr": 75.0}, build)
        assert violations == []

    def test_multiple_constraints_all_fail(self):
        build = _make_build(
            constraints=[
                Constraint(stat="fcr", operator=">=", value=75),
                Constraint(stat="resistance_all", operator=">=", value=75),
            ]
        )
        violations = check_hard_constraints({}, build)
        assert len(violations) == 2

    def test_no_constraints(self):
        build = _make_build(constraints=[])
        violations = check_hard_constraints({"fcr": 10.0}, build)
        assert violations == []

    def test_lte_constraint_pass(self):
        build = _make_build(
            constraints=[Constraint(stat="strength", operator="<=", value=156)]
        )
        violations = check_hard_constraints({"strength": 100.0}, build)
        assert violations == []

    def test_lte_constraint_fail(self):
        build = _make_build(
            constraints=[Constraint(stat="strength", operator="<=", value=156)]
        )
        violations = check_hard_constraints({"strength": 200.0}, build)
        assert len(violations) == 1


class TestCheckResourceConflicts:
    """Tests for resource conflict detection."""

    def test_resource_conflict_detected(self):
        """Same Ist rune in two items -> conflict."""
        costs = [
            Counter({"rune:Ist": 1}),
            Counter({"rune:Ist": 1}),
        ]
        conflicts = check_resource_conflicts(costs)
        assert len(conflicts) == 1
        assert "rune:Ist" in conflicts[0]

    def test_no_resource_conflict(self):
        """Different runes -> no conflict."""
        costs = [
            Counter({"rune:Ist": 1}),
            Counter({"rune:Um": 1}),
        ]
        conflicts = check_resource_conflicts(costs)
        assert conflicts == []

    def test_jewel_conflict_detected(self):
        """Same jewel UID in two items -> conflict."""
        costs = [
            Counter({"jewel:uid-123": 1}),
            Counter({"jewel:uid-123": 1}),
        ]
        conflicts = check_resource_conflicts(costs)
        assert len(conflicts) == 1

    def test_empty_costs(self):
        conflicts = check_resource_conflicts([])
        assert conflicts == []

    def test_single_item_no_conflict(self):
        costs = [Counter({"rune:Ist": 1, "rune:Um": 1})]
        conflicts = check_resource_conflicts(costs)
        assert conflicts == []

    def test_triple_use_conflict(self):
        """Same rune in three items -> conflict (count=3)."""
        costs = [
            Counter({"rune:Ber": 1}),
            Counter({"rune:Ber": 1}),
            Counter({"rune:Ber": 1}),
        ]
        conflicts = check_resource_conflicts(costs)
        assert len(conflicts) == 1
        assert "3 times" in conflicts[0]

    def test_available_pool_allows_multiple_identical_runes(self):
        """Resource conflicts respect the actual available quantity when supplied."""
        costs = [
            Counter({"rune:Ist": 1}),
            Counter({"rune:Ist": 1}),
        ]
        conflicts = check_resource_conflicts(
            costs,
            available_pool=Counter({"rune:Ist": 2}),
        )
        assert conflicts == []


# ===========================================================================
# Search engine tests
# ===========================================================================


class TestSearchEngine:
    """Tests for the core search function."""

    def test_single_valid_loadout(self, formula, easy_build):
        """1 candidate per slot -> returns exactly that loadout."""
        candidates = _build_single_candidate_per_slot()
        results = search(candidates, easy_build, formula, top_k=5)

        assert len(results) == 1
        result = results[0]
        assert result["slots"]["weapon"] == "weapon_a"
        assert result["slots"]["helmet"] == "helmet_a"
        assert result["total_score"] > 0.0
        assert result["violations"] == []

    def test_top_k_ranking(self, formula, easy_build):
        """Multiple candidates — verify top-1 is genuinely the best."""
        candidates = _build_single_candidate_per_slot()
        # Add a weaker weapon and a stronger weapon
        candidates["weapon"].append(
            make_candidate("weapon_weak", {"ed": 10, "all_skills": 0, "fcr": 10})
        )
        candidates["weapon"].append(
            make_candidate("weapon_strong", {"ed": 300, "all_skills": 4, "fcr": 50, "mf": 30})
        )

        results = search(candidates, easy_build, formula, top_k=5)
        assert len(results) >= 2

        # Top result must have the highest total_score
        scores = [r["total_score"] for r in results]
        assert scores == sorted(scores, reverse=True)

        # The strongest weapon loadout must be top-1
        assert results[0]["slots"]["weapon"] == "weapon_strong"

    def test_constraint_pruning(self, formula):
        """Some candidates violate constraints -> excluded from results."""
        # Strict FCR >= 100 constraint
        build = _make_build(
            constraints=[Constraint(stat="fcr", operator=">=", value=100)]
        )
        candidates = _build_single_candidate_per_slot()
        # Total FCR from default set: 50 (weapon) + 35 (shield) + 20 (gloves) = 105
        # This passes the constraint.

        results = search(candidates, build, formula, top_k=5)
        assert len(results) == 1

        # Now add a weapon that lowers total FCR below 100
        candidates["weapon"].append(
            make_candidate("weapon_no_fcr", {"ed": 200})
        )
        results = search(candidates, build, formula, top_k=5)

        # Only the loadout with weapon_a (FCR=50) passes; weapon_no_fcr gives
        # total FCR = 0 + 35 + 20 = 55 < 100.
        for r in results:
            assert r["slots"]["weapon"] == "weapon_a"

    def test_resource_conflict_pruning(self, formula, easy_build):
        """Candidates sharing a rune -> only non-conflicting combos returned."""
        candidates = _build_single_candidate_per_slot()

        # Both weapon and shield consume the same rune
        candidates["weapon"] = [
            make_candidate("weapon_rw", {"ed": 100, "fcr": 50}, {"rune:Ist": 1})
        ]
        candidates["shield"] = [
            make_candidate("shield_rw", {"fcr": 35}, {"rune:Ist": 1})
        ]

        results = search(candidates, easy_build, formula, top_k=5)
        # Conflict: same rune:Ist used twice -> no valid loadout
        assert results == []

    def test_resource_conflict_allows_different_runes(self, formula, easy_build):
        """Different runes in weapon and shield -> no conflict."""
        candidates = _build_single_candidate_per_slot()

        candidates["weapon"] = [
            make_candidate("weapon_rw", {"ed": 100, "fcr": 50}, {"rune:Ist": 1})
        ]
        candidates["shield"] = [
            make_candidate("shield_rw", {"fcr": 35}, {"rune:Um": 1})
        ]

        results = search(candidates, easy_build, formula, top_k=5)
        assert len(results) == 1

    def test_empty_slot_candidates(self, formula, easy_build):
        """A slot with no candidates -> returns empty results."""
        candidates = _build_single_candidate_per_slot()
        candidates["helmet"] = []  # no helmet candidates

        results = search(candidates, easy_build, formula, top_k=5)
        assert results == []

    def test_ring_slots_different_items(self, formula, easy_build):
        """ring1 and ring2 must have different items."""
        candidates = _build_single_candidate_per_slot()

        # Set both ring slots to offer the same single candidate
        shared_ring = make_candidate("ring_shared", {"all_skills": 1, "mf": 20})
        candidates["ring1"] = [shared_ring]
        candidates["ring2"] = [shared_ring]

        results = search(candidates, easy_build, formula, top_k=5)
        # ring2 cannot use the same UID as ring1, so no valid loadout
        assert results == []

    def test_ring_slots_allow_different_items(self, formula, easy_build):
        """Two different rings can occupy ring1 and ring2."""
        candidates = _build_single_candidate_per_slot()
        candidates["ring1"] = [make_candidate("ring_soj", {"all_skills": 1})]
        candidates["ring2"] = [make_candidate("ring_bk", {"all_skills": 1, "life": 50})]

        results = search(candidates, easy_build, formula, top_k=5)
        assert len(results) == 1
        assert results[0]["slots"]["ring1"] == "ring_soj"
        assert results[0]["slots"]["ring2"] == "ring_bk"

    def test_top_k_limit(self, formula, easy_build):
        """With many valid combos, only top_k returned."""
        candidates = _build_single_candidate_per_slot()
        # Add multiple helmet options to create multiple valid combos
        candidates["helmet"] = [
            make_candidate(f"helmet_{i}", {"mf": i * 10, "all_skills": 1})
            for i in range(10)
        ]

        results = search(candidates, easy_build, formula, top_k=3)
        assert len(results) == 3
        # Results are sorted descending
        assert results[0]["total_score"] >= results[1]["total_score"]
        assert results[1]["total_score"] >= results[2]["total_score"]

    def test_progress_callback_called(self, formula, easy_build):
        """Progress callback is invoked during the search."""
        candidates = _build_single_candidate_per_slot()
        calls = []

        def on_progress(n: int) -> None:
            calls.append(n)

        search(candidates, easy_build, formula, top_k=5, progress_callback=on_progress)
        # With 1 candidate per slot there is exactly 1 leaf evaluation,
        # which the engine reports at the end.
        assert len(calls) >= 1

    def test_missing_slot_skipped(self, formula, easy_build):
        """Slots not in candidates_by_slot are simply skipped."""
        # Only provide weapon and helmet
        candidates = {
            "weapon": [make_candidate("weapon_a", {"ed": 100, "fcr": 50})],
            "helmet": [make_candidate("helmet_a", {"mf": 50})],
        }
        results = search(candidates, easy_build, formula, top_k=5)
        assert len(results) == 1
        assert set(results[0]["slots"].keys()) == {"weapon", "helmet"}

    def test_lte_constraint_pruning(self, formula):
        """<= constraint prunes partial assignments early."""
        build = _make_build(
            constraints=[Constraint(stat="strength", operator="<=", value=50)]
        )
        candidates = {
            "weapon": [make_candidate("w", {"strength": 30})],
            "shield": [make_candidate("s", {"strength": 30})],
            # total strength = 60 > 50 -> violation
        }
        results = search(candidates, build, formula, top_k=5)
        assert results == []

    def test_search_uses_available_pool(self, formula, easy_build):
        """Two slots may consume the same rune when the pool quantity allows it."""
        candidates = {
            "weapon": [make_candidate("weapon_ist", {"mf": 25}, {"rune:Ist": 1})],
            "shield": [make_candidate("shield_ist", {"mf": 25}, {"rune:Ist": 1})],
        }

        results = search(
            candidates,
            easy_build,
            formula,
            top_k=5,
            available_pool=Counter({"rune:Ist": 2}),
        )

        assert len(results) == 1
        assert results[0]["slots"] == {
            "weapon": "weapon_ist",
            "shield": "shield_ist",
        }

    def test_set_bonuses_are_applied_to_final_stats(self, formula, easy_build):
        """Active set bonuses are merged into the scored loadout stats."""
        common_set_meta = {
            "set_name": "Test Set",
            "set_size": 2,
            "partial_bonuses": {2: {"mf": 20}},
            "full_bonus": {"all_skills": 1},
        }
        candidates = {
            "weapon": [make_candidate(
                "set_weapon",
                {"mf": 10},
                set_meta={
                    **common_set_meta,
                    "item_name": "Test Weapon",
                    "item_partial_bonus": {2: {"fcr": 10}},
                },
            )],
            "belt": [make_candidate(
                "set_belt",
                {"mf": 5},
                set_meta={
                    **common_set_meta,
                    "item_name": "Test Belt",
                    "item_partial_bonus": {},
                },
            )],
        }

        results = search(candidates, easy_build, formula, top_k=1)

        assert len(results) == 1
        stats = results[0]["stats"]
        assert stats["mf"] == pytest.approx(35.0)
        assert stats["fcr"] == pytest.approx(10.0)
        assert stats["all_skills"] == pytest.approx(1.0)

    def test_explicit_beam_search_returns_same_best_result(self, formula):
        """Explicit beam search keeps the same top-1 for an easy monotonic case."""
        build = _make_build(
            objectives=ObjectiveWeights(
                damage=0.0,
                magic_find=1.0,
                effective_hp=0.0,
                breakpoint_score=0.0,
            ),
            constraints=[],
        )
        candidates = {
            "weapon": [
                make_candidate("weapon_low", {"mf": 10}),
                make_candidate("weapon_mid", {"mf": 20}),
                make_candidate("weapon_high", {"mf": 30}),
            ],
            "helmet": [
                make_candidate("helmet_low", {"mf": 1}),
                make_candidate("helmet_mid", {"mf": 2}),
                make_candidate("helmet_high", {"mf": 3}),
            ],
            "amulet": [
                make_candidate("amulet_low", {"mf": 100}),
                make_candidate("amulet_mid", {"mf": 200}),
                make_candidate("amulet_high", {"mf": 300}),
            ],
        }

        exhaustive = search(candidates, build, formula, top_k=1)
        beam = search(candidates, build, formula, top_k=1, beam_width=2)

        assert len(exhaustive) == 1
        assert len(beam) == 1
        assert beam[0]["slots"] == exhaustive[0]["slots"]
        assert beam[0]["total_score"] == pytest.approx(exhaustive[0]["total_score"])


# ===========================================================================
# Parallel search tests
# ===========================================================================


class TestParallelSearch:
    """Tests for parallel_search."""

    def test_parallel_same_results(self, easy_build):
        """parallel_search produces same top-1 as single-threaded."""
        candidates = _build_single_candidate_per_slot()

        formula = get_formula("warlock_echoing_strike")
        single = search(candidates, easy_build, formula, top_k=1)

        parallel = parallel_search(
            candidates,
            easy_build,
            "warlock_echoing_strike",
            top_k=1,
            workers=1,
        )

        assert len(single) == len(parallel)
        assert single[0]["slots"] == parallel[0]["slots"]
        assert single[0]["total_score"] == pytest.approx(parallel[0]["total_score"])

    def test_parallel_workers_1_fallback(self, easy_build):
        """workers=1 -> same as single-threaded."""
        candidates = _build_single_candidate_per_slot()

        results = parallel_search(
            candidates,
            easy_build,
            "warlock_echoing_strike",
            top_k=5,
            workers=1,
        )
        assert len(results) == 1
        assert results[0]["slots"]["weapon"] == "weapon_a"

    def test_parallel_small_inventory(self, easy_build):
        """Few weapon candidates -> still works correctly."""
        candidates = _build_single_candidate_per_slot()
        candidates["weapon"] = [
            make_candidate("weapon_a", {"ed": 100, "all_skills": 2, "fcr": 50}),
            make_candidate("weapon_b", {"ed": 200, "all_skills": 3, "fcr": 50, "mf": 20}),
        ]

        results = parallel_search(
            candidates,
            easy_build,
            "warlock_echoing_strike",
            top_k=2,
            workers=2,
        )

        assert len(results) == 2
        # Results should be sorted by score descending
        assert results[0]["total_score"] >= results[1]["total_score"]

    def test_parallel_with_constraints(self):
        """Parallel search respects hard constraints."""
        build = _make_build(
            constraints=[Constraint(stat="fcr", operator=">=", value=100)]
        )
        candidates = _build_single_candidate_per_slot()
        # weapon_a has fcr=50, shield has fcr=35, gloves has fcr=20 -> total=105 passes
        # weapon_weak has fcr=10 -> total=65 fails
        candidates["weapon"].append(
            make_candidate("weapon_weak", {"ed": 10, "fcr": 10})
        )

        results = parallel_search(
            candidates,
            build,
            "warlock_echoing_strike",
            top_k=5,
            workers=2,
        )

        # Only weapon_a loadout should pass
        for r in results:
            assert r["slots"]["weapon"] == "weapon_a"

    def test_parallel_progress_callback(self, easy_build):
        """Progress callback is invoked in parallel mode."""
        candidates = _build_single_candidate_per_slot()
        candidates["weapon"] = [
            make_candidate("weapon_a", {"ed": 100, "fcr": 50}),
            make_candidate("weapon_b", {"ed": 200, "fcr": 50}),
        ]
        calls = []

        def on_progress(n: int) -> None:
            calls.append(n)

        parallel_search(
            candidates,
            easy_build,
            "warlock_echoing_strike",
            top_k=5,
            workers=2,
            progress_callback=on_progress,
        )
        # With 2 weapons dispatched to workers, we get at least 2 progress calls
        assert len(calls) >= 2


# ===========================================================================
# Performance sanity check
# ===========================================================================


class TestSearchPerformance:
    """Smoke test for performance — should complete within reasonable time."""

    def test_moderate_inventory(self, formula, easy_build):
        """10 candidates per slot (10^10 combinations) must complete.

        With only 10 slots and 10 candidates each, the search space is 10
        billion — but the actual tree is pruned heavily by resource
        conflicts and constraints.  This test simply checks it terminates
        within pytest's default timeout.

        NOTE: 10 candidates per slot with no conflicts/constraints
        actually yields 10^10 leaves.  We reduce to 3 candidates per slot
        to keep the test fast (3^10 = 59,049 leaves).
        """
        candidates = {}
        for slot in [
            "weapon", "shield", "helmet", "body", "gloves",
            "belt", "boots", "amulet", "ring1", "ring2",
        ]:
            candidates[slot] = [
                make_candidate(
                    f"{slot}_{i}",
                    {"mf": i * 5, "fcr": i * 3, "ed": i * 10, "all_skills": 1},
                )
                for i in range(3)
            ]
        # Ensure ring1 and ring2 have distinct UIDs from each other
        candidates["ring2"] = [
            make_candidate(
                f"ring2_{i}",
                {"mf": i * 5, "fcr": i * 3, "all_skills": 1},
            )
            for i in range(3)
        ]

        results = search(candidates, easy_build, formula, top_k=3)
        assert len(results) == 3
        assert results[0]["total_score"] >= results[1]["total_score"]
