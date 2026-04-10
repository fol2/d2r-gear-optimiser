"""Tests for the validation module — reference comparison, live measurement recording,
and the Maxroll Echoing Strike fixture."""

import pytest
from sqlmodel import Session, SQLModel, create_engine

from d2r_optimiser.core.formula.common import aggregate_stats
from d2r_optimiser.core.validation.validator import (
    _compute_deviation_pct,
    check_all_validations,
    record_live_measurement,
    validate_against_reference,
)
from tests.fixtures.maxroll_echoing_strike import (
    EXPECTED_AGGREGATE,
    MAXROLL_STANDARD_GEAR,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session():
    """Yield an in-memory SQLite session with tables created."""
    engine = create_engine("sqlite://", echo=False)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# ===========================================================================
# _compute_deviation_pct
# ===========================================================================


class TestComputeDeviationPct:
    """Edge cases for the deviation helper."""

    def test_both_zero(self):
        assert _compute_deviation_pct(0.0, 0.0) == 0.0

    def test_actual_zero_predicted_nonzero(self):
        assert _compute_deviation_pct(42.0, 0.0) == 100.0

    def test_exact_match(self):
        assert _compute_deviation_pct(100.0, 100.0) == 0.0

    def test_positive_deviation(self):
        # predicted=110, actual=100 → 10% off
        assert _compute_deviation_pct(110.0, 100.0) == pytest.approx(10.0)

    def test_negative_deviation_is_absolute(self):
        # predicted=90, actual=100 → 10% off (absolute)
        assert _compute_deviation_pct(90.0, 100.0) == pytest.approx(10.0)


# ===========================================================================
# validate_against_reference
# ===========================================================================


class TestValidateAgainstReference:
    """Reference stat comparison logic."""

    def test_exact_match(self):
        stats = {"fcr": 125.0, "mf": 200.0, "life": 1000.0}
        result = validate_against_reference(stats, stats)
        assert result["pass"] is True
        assert result["max_deviation_pct"] == 0.0
        for detail in result["deviations"].values():
            assert detail["deviation_pct"] == 0.0
            assert detail["within_tolerance"] is True

    def test_within_tolerance(self):
        predicted = {"fcr": 122.0}  # 2.4% off from 125
        expected = {"fcr": 125.0}
        result = validate_against_reference(predicted, expected, tolerance_pct=5.0)
        assert result["pass"] is True
        assert result["max_deviation_pct"] == pytest.approx(2.4)
        assert result["deviations"]["fcr"]["within_tolerance"] is True

    def test_exceeds_tolerance(self):
        predicted = {"fcr": 100.0}  # 20% off from 125
        expected = {"fcr": 125.0}
        result = validate_against_reference(predicted, expected, tolerance_pct=5.0)
        assert result["pass"] is False
        assert result["max_deviation_pct"] == pytest.approx(20.0)
        assert result["deviations"]["fcr"]["within_tolerance"] is False

    def test_mixed_stats(self):
        predicted = {"fcr": 124.0, "mf": 80.0}  # fcr ~0.8% off, mf 20% off
        expected = {"fcr": 125.0, "mf": 100.0}
        result = validate_against_reference(predicted, expected, tolerance_pct=5.0)
        assert result["pass"] is False
        assert result["deviations"]["fcr"]["within_tolerance"] is True
        assert result["deviations"]["mf"]["within_tolerance"] is False

    def test_zero_values_both_zero(self):
        result = validate_against_reference({"mf": 0.0}, {"mf": 0.0})
        assert result["pass"] is True
        assert result["deviations"]["mf"]["deviation_pct"] == 0.0

    def test_zero_values_expected_zero_predicted_nonzero(self):
        result = validate_against_reference({"mf": 50.0}, {"mf": 0.0})
        assert result["pass"] is False
        assert result["deviations"]["mf"]["deviation_pct"] == 100.0

    def test_missing_predicted_stat_defaults_to_zero(self):
        result = validate_against_reference({}, {"fcr": 100.0})
        assert result["pass"] is False
        assert result["deviations"]["fcr"]["predicted"] == 0.0
        assert result["deviations"]["fcr"]["deviation_pct"] == 100.0

    def test_custom_tolerance(self):
        predicted = {"mf": 88.0}  # 12% off from 100
        expected = {"mf": 100.0}
        strict = validate_against_reference(predicted, expected, tolerance_pct=5.0)
        loose = validate_against_reference(predicted, expected, tolerance_pct=15.0)
        assert strict["pass"] is False
        assert loose["pass"] is True


# ===========================================================================
# record_live_measurement
# ===========================================================================


class TestRecordLiveMeasurement:
    """Database recording of live in-game measurements."""

    def test_record_and_retrieve(self, db_session: Session):
        rec = record_live_measurement(
            db_session,
            gear_set_id="test-set-1",
            build_def="warlock_echoing_strike_mf",
            predicted={"damage": 500.0, "mf": 200.0},
            actual={"damage": 480.0, "mf": 195.0},
            notes="First test measurement",
        )
        assert rec.id is not None
        assert rec.gear_set_id == "test-set-1"
        assert rec.build_def == "warlock_echoing_strike_mf"
        assert rec.predicted_damage == 500.0
        assert rec.actual_damage == 480.0
        assert rec.predicted_mf == 200.0
        assert rec.actual_mf == 195.0
        assert rec.notes == "First test measurement"

    def test_deviation_computed(self, db_session: Session):
        rec = record_live_measurement(
            db_session,
            gear_set_id="dev-check",
            build_def="test_build",
            predicted={"damage": 110.0, "mf": 100.0},
            actual={"damage": 100.0, "mf": 100.0},
        )
        # damage deviation = |110-100|/100 * 100 = 10%
        # mf deviation = 0%
        # max is 10%
        assert rec.deviation_max == pytest.approx(10.0)

    def test_multiple_records(self, db_session: Session):
        for i in range(3):
            record_live_measurement(
                db_session,
                gear_set_id=f"set-{i}",
                build_def="warlock_echoing_strike_mf",
                predicted={"damage": 100.0 + i * 10},
                actual={"damage": 100.0},
            )
        results = check_all_validations(db_session)
        assert len(results) == 3

    def test_partial_stats(self, db_session: Session):
        """Only some stat pairs provided — others remain None."""
        rec = record_live_measurement(
            db_session,
            gear_set_id="partial",
            build_def="test_build",
            predicted={"fcr": 125.0},
            actual={"fcr": 120.0},
        )
        assert rec.predicted_fcr == 125.0
        assert rec.actual_fcr == 120.0
        assert rec.predicted_damage is None
        assert rec.actual_damage is None
        # deviation_max from fcr: |125-120|/120 * 100 ≈ 4.17%
        assert rec.deviation_max == pytest.approx(4.1667, abs=0.01)

    def test_empty_notes_stored_as_none(self, db_session: Session):
        rec = record_live_measurement(
            db_session,
            gear_set_id="no-notes",
            build_def="test_build",
            predicted={"mf": 100.0},
            actual={"mf": 100.0},
        )
        assert rec.notes is None


# ===========================================================================
# check_all_validations
# ===========================================================================


class TestCheckAllValidations:
    """Querying stored validation records."""

    def test_empty_db(self, db_session: Session):
        results = check_all_validations(db_session)
        assert results == []

    def test_filter_by_build(self, db_session: Session):
        record_live_measurement(
            db_session,
            gear_set_id="a",
            build_def="build_alpha",
            predicted={"mf": 100.0},
            actual={"mf": 100.0},
        )
        record_live_measurement(
            db_session,
            gear_set_id="b",
            build_def="build_beta",
            predicted={"mf": 100.0},
            actual={"mf": 100.0},
        )
        record_live_measurement(
            db_session,
            gear_set_id="c",
            build_def="build_alpha",
            predicted={"mf": 100.0},
            actual={"mf": 100.0},
        )

        alpha_only = check_all_validations(db_session, build_def="build_alpha")
        assert len(alpha_only) == 2
        assert all(r["build_def"] == "build_alpha" for r in alpha_only)

        beta_only = check_all_validations(db_session, build_def="build_beta")
        assert len(beta_only) == 1

    def test_returns_all(self, db_session: Session):
        for i in range(4):
            record_live_measurement(
                db_session,
                gear_set_id=f"set-{i}",
                build_def=f"build_{i}",
                predicted={"damage": 100.0},
                actual={"damage": 100.0},
            )
        results = check_all_validations(db_session)
        assert len(results) == 4

    def test_pass_field_reflects_deviation(self, db_session: Session):
        # Within tolerance (0% deviation)
        record_live_measurement(
            db_session,
            gear_set_id="good",
            build_def="test",
            predicted={"mf": 100.0},
            actual={"mf": 100.0},
        )
        # Exceeds tolerance (50% deviation)
        record_live_measurement(
            db_session,
            gear_set_id="bad",
            build_def="test",
            predicted={"mf": 150.0},
            actual={"mf": 100.0},
        )
        results = check_all_validations(db_session)
        good_rec = next(r for r in results if r["gear_set_id"] == "good")
        bad_rec = next(r for r in results if r["gear_set_id"] == "bad")
        assert good_rec["pass"] is True
        assert bad_rec["pass"] is False


# ===========================================================================
# Maxroll reference fixture
# ===========================================================================


class TestMaxrollReferenceFixture:
    """Tests for the Maxroll Echoing Strike gear fixture."""

    def test_reference_fixture_loads(self):
        assert isinstance(MAXROLL_STANDARD_GEAR, dict)
        assert len(MAXROLL_STANDARD_GEAR) == 10  # 10 gear slots
        for slot, item in MAXROLL_STANDARD_GEAR.items():
            assert "name" in item, f"Missing 'name' in slot {slot}"
            assert "stats" in item, f"Missing 'stats' in slot {slot}"
            assert isinstance(item["stats"], dict)

    def test_expected_aggregate_has_required_keys(self):
        required = {"all_skills", "fcr", "mf", "life", "mana", "fhr", "dr"}
        assert required.issubset(EXPECTED_AGGREGATE.keys())

    def test_aggregate_stats_match(self):
        """Aggregate stats computed from fixture gear match EXPECTED_AGGREGATE within 5%."""
        # Build items_by_slot in the format aggregate_stats expects
        items_by_slot: dict[str, list[dict]] = {}
        for slot, item in MAXROLL_STANDARD_GEAR.items():
            items_by_slot[slot] = [item["stats"]]

        computed = aggregate_stats(items_by_slot)

        result = validate_against_reference(computed, EXPECTED_AGGREGATE, tolerance_pct=5.0)
        for stat, detail in result["deviations"].items():
            assert detail["within_tolerance"], (
                f"{stat}: predicted={detail['predicted']}, "
                f"expected={detail['expected']}, "
                f"deviation={detail['deviation_pct']:.2f}%"
            )
