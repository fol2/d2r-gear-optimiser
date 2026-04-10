"""Comprehensive tests for the formula engine — MF curve, breakpoints, constraints,
and the Warlock Echoing Strike formula implementation."""

from pathlib import Path

import pytest

from d2r_optimiser.core.formula import (
    BuildFormula,
    aggregate_stats,
    check_all_constraints,
    check_constraint,
    effective_mf,
    get_formula,
    lookup_breakpoint,
)
from d2r_optimiser.core.formula.warlock_echoing_strike import EchoingStrikeFormula
from d2r_optimiser.core.models import BuildDefinition, Constraint, ObjectiveWeights, ScoreBreakdown
from d2r_optimiser.loader import load_breakpoints, load_build

# ---------------------------------------------------------------------------
# Paths to real data files
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_BREAKPOINTS_PATH = _DATA_DIR / "breakpoints.yaml"
_BUILD_WARLOCK_PATH = _DATA_DIR / "builds" / "warlock_echoing_strike_mf.yaml"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def warlock_bp() -> dict:
    """Load real warlock breakpoint data."""
    bp = load_breakpoints(_BREAKPOINTS_PATH)
    return bp["warlock"]


@pytest.fixture()
def warlock_build() -> BuildDefinition:
    """Load real warlock build definition."""
    return load_build(_BUILD_WARLOCK_PATH)


@pytest.fixture()
def formula(warlock_bp: dict) -> EchoingStrikeFormula:
    """EchoingStrikeFormula initialised with real breakpoint data."""
    return EchoingStrikeFormula(breakpoints=warlock_bp)


def _make_build(**overrides) -> BuildDefinition:
    """Create a minimal BuildDefinition for tests."""
    defaults = {
        "name": "test_build",
        "display_name": "Test Build",
        "character_class": "warlock",
        "description": "Test build for formula unit tests.",
        "formula_module": "warlock_echoing_strike",
        "skill_points": {"echoing_strike": 20},
        "objectives": ObjectiveWeights(
            damage=0.35, magic_find=0.40, effective_hp=0.15, breakpoint_score=0.10,
        ),
        "constraints": [
            Constraint(stat="fcr", operator=">=", value=75),
            Constraint(stat="resistance_all", operator=">=", value=75),
        ],
        "presets": {},
    }
    defaults.update(overrides)
    return BuildDefinition(**defaults)


# ===========================================================================
# effective_mf curve
# ===========================================================================


class TestEffectiveMf:
    """D2R diminishing returns on Magic Find."""

    def test_mf_zero(self):
        result = effective_mf(0)
        assert result["unique"] == 0.0
        assert result["set"] == 0.0
        assert result["rare"] == 0.0

    def test_mf_100(self):
        result = effective_mf(100)
        assert result["unique"] == pytest.approx(71.4, abs=0.1)
        assert result["set"] == pytest.approx(83.3, abs=0.1)
        assert result["rare"] == pytest.approx(85.7, abs=0.1)

    def test_mf_300(self):
        result = effective_mf(300)
        assert result["unique"] == pytest.approx(136.4, abs=0.1)
        assert result["set"] == pytest.approx(187.5, abs=0.1)
        assert result["rare"] == pytest.approx(200.0, abs=0.1)

    def test_mf_1000(self):
        result = effective_mf(1000)
        assert result["unique"] == pytest.approx(200.0, abs=0.1)
        assert result["set"] == pytest.approx(333.3, abs=0.1)
        assert result["rare"] == pytest.approx(375.0, abs=0.1)

    def test_mf_negative_returns_zero(self):
        result = effective_mf(-50)
        assert result["unique"] == 0.0
        assert result["set"] == 0.0
        assert result["rare"] == 0.0

    def test_mf_monotonically_increasing(self):
        """Higher raw MF must always produce higher effective MF."""
        prev = effective_mf(0)
        for raw in [50, 100, 200, 400, 800, 1500]:
            current = effective_mf(raw)
            for key in ("unique", "set", "rare"):
                assert current[key] > prev[key], f"{key} not increasing at raw={raw}"
            prev = current


# ===========================================================================
# lookup_breakpoint
# ===========================================================================


class TestLookupBreakpoint:
    """Breakpoint threshold lookup logic."""

    # Warlock FCR table: 0/15, 9/14, 20/13, 37/12, 63/11, 105/10, 200/9
    _FCR_TABLE = [
        {"threshold": 0, "frames": 15},
        {"threshold": 9, "frames": 14},
        {"threshold": 20, "frames": 13},
        {"threshold": 37, "frames": 12},
        {"threshold": 63, "frames": 11},
        {"threshold": 105, "frames": 10},
        {"threshold": 200, "frames": 9},
    ]

    def test_exact_threshold(self):
        result = lookup_breakpoint(self._FCR_TABLE, 75)
        # 75 >= 63 but < 105, so matches the 63 threshold
        assert result["threshold"] == 63
        assert result["frames"] == 11

    def test_exact_match_on_threshold(self):
        result = lookup_breakpoint(self._FCR_TABLE, 105)
        assert result["threshold"] == 105
        assert result["frames"] == 10

    def test_between_thresholds(self):
        result = lookup_breakpoint(self._FCR_TABLE, 80)
        assert result["threshold"] == 63
        assert result["frames"] == 11

    def test_zero_value(self):
        result = lookup_breakpoint(self._FCR_TABLE, 0)
        assert result["threshold"] == 0
        assert result["frames"] == 15

    def test_above_max(self):
        result = lookup_breakpoint(self._FCR_TABLE, 250)
        assert result["threshold"] == 200
        assert result["frames"] == 9

    def test_below_first_threshold(self):
        # If the first threshold is > 0 this would matter; with 0-start it hits 0
        table = [{"threshold": 10, "frames": 12}, {"threshold": 20, "frames": 10}]
        result = lookup_breakpoint(table, 5)
        assert result["threshold"] == 10
        assert result["frames"] == 12

    def test_empty_table_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            lookup_breakpoint([], 50)


# ===========================================================================
# aggregate_stats
# ===========================================================================


class TestAggregateStats:
    """Stat aggregation across equipped items."""

    def test_single_item(self):
        items = {"helmet": [{"mf": 50, "all_skills": 2}]}
        result = aggregate_stats(items)
        assert result["mf"] == 50.0
        assert result["all_skills"] == 2.0

    def test_multiple_items(self):
        items = {
            "helmet": [{"mf": 50, "all_skills": 2}],
            "body": [{"mf": 99, "all_skills": 2, "strength": 15}],
        }
        result = aggregate_stats(items)
        assert result["mf"] == 149.0
        assert result["all_skills"] == 4.0
        assert result["strength"] == 15.0

    def test_empty(self):
        result = aggregate_stats({})
        assert result == {}

    def test_multiple_items_in_same_slot(self):
        """Socket fillings can add extra stat dicts to the same slot."""
        items = {
            "helmet": [
                {"mf": 50, "all_skills": 2},
                {"mf": 25},  # e.g. a socketed Perfect Topaz
            ],
        }
        result = aggregate_stats(items)
        assert result["mf"] == 75.0
        assert result["all_skills"] == 2.0


# ===========================================================================
# check_constraint
# ===========================================================================


class TestCheckConstraint:
    """Individual constraint checking."""

    def test_gte_pass(self):
        c = Constraint(stat="fcr", operator=">=", value=75)
        assert check_constraint({"fcr": 105.0}, c) is True

    def test_gte_fail(self):
        c = Constraint(stat="fcr", operator=">=", value=75)
        assert check_constraint({"fcr": 50.0}, c) is False

    def test_gte_exact(self):
        c = Constraint(stat="fcr", operator=">=", value=75)
        assert check_constraint({"fcr": 75.0}, c) is True

    def test_equals_pass(self):
        c = Constraint(stat="socket_count", operator="==", value=4)
        assert check_constraint({"socket_count": 4.0}, c) is True

    def test_equals_fail(self):
        c = Constraint(stat="socket_count", operator="==", value=4)
        assert check_constraint({"socket_count": 3.0}, c) is False

    def test_lte_pass(self):
        c = Constraint(stat="strength", operator="<=", value=156)
        assert check_constraint({"strength": 100.0}, c) is True

    def test_missing_stat_defaults_to_zero(self):
        c = Constraint(stat="fcr", operator=">=", value=75)
        assert check_constraint({}, c) is False

    def test_unsupported_operator_raises(self):
        c = Constraint(stat="fcr", operator="!=", value=75)
        with pytest.raises(ValueError, match="Unsupported constraint operator"):
            check_constraint({"fcr": 50.0}, c)


class TestCheckAllConstraints:
    """Batch constraint checking."""

    def test_all_pass(self):
        constraints = [
            Constraint(stat="fcr", operator=">=", value=75),
            Constraint(stat="resistance_all", operator=">=", value=75),
        ]
        stats = {"fcr": 105.0, "resistance_all": 80.0}
        violations = check_all_constraints(stats, constraints)
        assert violations == []

    def test_one_fails(self):
        constraints = [
            Constraint(stat="fcr", operator=">=", value=75),
            Constraint(stat="resistance_all", operator=">=", value=75),
        ]
        stats = {"fcr": 105.0, "resistance_all": 50.0}
        violations = check_all_constraints(stats, constraints)
        assert len(violations) == 1
        assert "resistance_all" in violations[0]

    def test_all_fail(self):
        constraints = [
            Constraint(stat="fcr", operator=">=", value=75),
            Constraint(stat="resistance_all", operator=">=", value=75),
        ]
        violations = check_all_constraints({}, constraints)
        assert len(violations) == 2

    def test_empty_constraints(self):
        violations = check_all_constraints({"fcr": 100.0}, [])
        assert violations == []


# ===========================================================================
# EchoingStrikeFormula
# ===========================================================================


class TestEchoingStrikeProtocol:
    """Protocol compliance and basic interface tests."""

    def test_protocol_compliance(self, formula: EchoingStrikeFormula):
        assert isinstance(formula, BuildFormula)

    def test_protocol_compliance_without_breakpoints(self):
        f = EchoingStrikeFormula()
        assert isinstance(f, BuildFormula)


class TestEchoingStrikeDamage:
    """Damage computation tests."""

    def test_zero_gear_scores_low(
        self, formula: EchoingStrikeFormula, warlock_build: BuildDefinition
    ):
        score = formula.compute_damage({}, warlock_build)
        # With no gear, damage comes only from base values, so it is low
        assert 0.0 < score < 0.2

    def test_high_ed_increases_damage(
        self, formula: EchoingStrikeFormula, warlock_build: BuildDefinition
    ):
        low = formula.compute_damage({"ed": 50}, warlock_build)
        high = formula.compute_damage({"ed": 300}, warlock_build)
        assert high > low

    def test_skills_increase_damage(
        self, formula: EchoingStrikeFormula, warlock_build: BuildDefinition
    ):
        low = formula.compute_damage({"all_skills": 2}, warlock_build)
        high = formula.compute_damage({"all_skills": 14}, warlock_build)
        assert high > low

    def test_fcr_breakpoint_affects_damage(
        self, formula: EchoingStrikeFormula, warlock_build: BuildDefinition
    ):
        """Higher FCR hitting a better breakpoint must produce higher damage."""
        # 37 FCR = 12 frames; 105 FCR = 10 frames
        low = formula.compute_damage({"fcr": 37}, warlock_build)
        high = formula.compute_damage({"fcr": 105}, warlock_build)
        assert high > low

    def test_damage_capped_at_one(
        self, formula: EchoingStrikeFormula, warlock_build: BuildDefinition
    ):
        """Extreme stats should cap at 1.0."""
        extreme = formula.compute_damage(
            {"ed": 500, "all_skills": 20, "damage_min": 200, "damage_max": 500, "fcr": 200},
            warlock_build,
        )
        assert extreme <= 1.0


class TestEchoingStrikeMf:
    """Magic Find computation tests."""

    def test_zero_mf(self, formula: EchoingStrikeFormula, warlock_build: BuildDefinition):
        score = formula.compute_mf({}, warlock_build)
        assert score == 0.0

    def test_high_mf_gear(self, formula: EchoingStrikeFormula, warlock_build: BuildDefinition):
        score = formula.compute_mf({"mf": 300}, warlock_build)
        # 300 raw MF -> effective unique ~136.4 -> 136.4/250 ~ 0.546
        assert score == pytest.approx(0.546, abs=0.01)

    def test_mf_increases_with_raw(
        self, formula: EchoingStrikeFormula, warlock_build: BuildDefinition
    ):
        low = formula.compute_mf({"mf": 100}, warlock_build)
        high = formula.compute_mf({"mf": 400}, warlock_build)
        assert high > low

    def test_mf_never_exceeds_one(
        self, formula: EchoingStrikeFormula, warlock_build: BuildDefinition
    ):
        score = formula.compute_mf({"mf": 10000}, warlock_build)
        assert score < 1.0  # asymptote at 250/250 = 1.0 but never reaches it


class TestEchoingStrikeEhp:
    """Effective HP computation tests."""

    def test_zero_gear_has_base_ehp(
        self, formula: EchoingStrikeFormula, warlock_build: BuildDefinition
    ):
        score = formula.compute_ehp({}, warlock_build)
        # Even with no gear there's base life, so EHP > 0
        assert score > 0.0

    def test_vitality_increases_ehp(
        self, formula: EchoingStrikeFormula, warlock_build: BuildDefinition
    ):
        low = formula.compute_ehp({"vitality": 20}, warlock_build)
        high = formula.compute_ehp({"vitality": 100}, warlock_build)
        assert high > low

    def test_dr_increases_ehp(
        self, formula: EchoingStrikeFormula, warlock_build: BuildDefinition
    ):
        low = formula.compute_ehp({"dr": 0}, warlock_build)
        high = formula.compute_ehp({"dr": 30}, warlock_build)
        assert high > low

    def test_resistance_increases_ehp(
        self, formula: EchoingStrikeFormula, warlock_build: BuildDefinition
    ):
        low = formula.compute_ehp({}, warlock_build)
        high = formula.compute_ehp({"resistance_all": 75}, warlock_build)
        assert high > low


class TestEchoingStrikeBreakpointScore:
    """Breakpoint scoring tests."""

    def test_zero_stats_scores_low(
        self, formula: EchoingStrikeFormula, warlock_build: BuildDefinition
    ):
        score = formula.compute_breakpoint_score({}, warlock_build)
        assert score < 0.2

    def test_meeting_all_constraints_scores_high(
        self, formula: EchoingStrikeFormula, warlock_build: BuildDefinition
    ):
        stats = {"fcr": 105, "fhr": 86, "resistance_all": 75}
        score = formula.compute_breakpoint_score(stats, warlock_build)
        assert score > 0.8

    def test_partial_fcr_gets_partial_credit(
        self, formula: EchoingStrikeFormula, warlock_build: BuildDefinition
    ):
        half = formula.compute_breakpoint_score({"fcr": 37}, warlock_build)
        full = formula.compute_breakpoint_score({"fcr": 75}, warlock_build)
        assert full > half > 0.0


class TestEchoingStrikeScore:
    """Full score() integration tests."""

    def test_score_returns_breakdown(
        self, formula: EchoingStrikeFormula, warlock_build: BuildDefinition
    ):
        result = formula.score({}, warlock_build)
        assert isinstance(result, ScoreBreakdown)
        assert hasattr(result, "damage")
        assert hasattr(result, "magic_find")
        assert hasattr(result, "effective_hp")
        assert hasattr(result, "breakpoint_score")

    def test_score_all_dimensions_populated(
        self, formula: EchoingStrikeFormula, warlock_build: BuildDefinition
    ):
        stats = {
            "mf": 200, "ed": 100, "all_skills": 8, "fcr": 75,
            "fhr": 42, "vitality": 50, "life": 100, "resistance_all": 75,
        }
        result = formula.score(stats, warlock_build)
        assert result.damage > 0.0
        assert result.magic_find > 0.0
        assert result.effective_hp > 0.0
        assert result.breakpoint_score > 0.0

    def test_better_gear_scores_higher(
        self, formula: EchoingStrikeFormula, warlock_build: BuildDefinition
    ):
        """A loadout with better stats across the board must score higher
        in every dimension."""
        weak = {"mf": 50, "ed": 20, "all_skills": 2, "fcr": 20}
        strong = {
            "mf": 300, "ed": 200, "all_skills": 12, "fcr": 105,
            "fhr": 60, "vitality": 80, "life": 200, "resistance_all": 75,
            "ds": 30,
        }
        weak_score = formula.score(weak, warlock_build)
        strong_score = formula.score(strong, warlock_build)
        assert strong_score.damage > weak_score.damage
        assert strong_score.magic_find > weak_score.magic_find
        assert strong_score.effective_hp > weak_score.effective_hp
        assert strong_score.breakpoint_score > weak_score.breakpoint_score


# ===========================================================================
# EchoingStrikeFormula — fallback without breakpoints
# ===========================================================================


class TestEchoingStrikeNoBreakpoints:
    """Formula should work (with linear fallback) when no breakpoint data is loaded."""

    def test_damage_without_breakpoints(self, warlock_build: BuildDefinition):
        f = EchoingStrikeFormula()  # no breakpoints
        score = f.compute_damage({"fcr": 105, "ed": 100}, warlock_build)
        assert score > 0.0

    def test_breakpoint_score_without_bp_data(self, warlock_build: BuildDefinition):
        f = EchoingStrikeFormula()
        score = f.compute_breakpoint_score({"fcr": 105, "fhr": 60}, warlock_build)
        assert score > 0.0


# ===========================================================================
# get_formula factory
# ===========================================================================


class TestGetFormula:
    """Factory function for resolving formula modules."""

    def test_resolve_echoing_strike(self):
        f = get_formula("warlock_echoing_strike")
        assert isinstance(f, EchoingStrikeFormula)
        assert isinstance(f, BuildFormula)

    def test_unknown_formula_raises(self):
        with pytest.raises(ImportError, match="Formula module not found"):
            get_formula("nonexistent_formula_xyz")

    def test_module_without_formula_class_raises(self):
        # common.py exists but has no *Formula class
        with pytest.raises(ValueError, match="No \\*Formula class found"):
            get_formula("common")
