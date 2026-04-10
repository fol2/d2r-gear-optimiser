"""Comprehensive tests for YAML data loaders."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from d2r_optimiser.loader import (
    LoaderError,
    list_builds,
    load_base_items,
    load_breakpoints,
    load_build,
    load_runewords,
)

# ---------------------------------------------------------------------------
# Paths to real data files
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_RUNEWORDS_PATH = _DATA_DIR / "runewords.yaml"
_BREAKPOINTS_PATH = _DATA_DIR / "breakpoints.yaml"
_BUILDS_DIR = _DATA_DIR / "builds"
_BUILD_WARLOCK_PATH = _BUILDS_DIR / "warlock_echoing_strike_mf.yaml"

# Known D2R runes (El through Zod) for cross-reference validation
_ALL_RUNE_NAMES = [
    "El", "Eld", "Tir", "Nef", "Eth", "Ith", "Tal", "Ral", "Ort", "Thul",
    "Amn", "Sol", "Shael", "Dol", "Hel", "Io", "Lum", "Ko", "Fal", "Lem",
    "Pul", "Um", "Mal", "Ist", "Gul", "Vex", "Ohm", "Lo", "Sur", "Ber",
    "Jah", "Cham", "Zod",
]


# ===========================================================================
# Happy-path tests — real data files
# ===========================================================================


class TestLoadRunewordsHappyPath:
    """Load data/runewords.yaml and verify content."""

    def test_load_runewords_full(self):
        recipes = load_runewords(_RUNEWORDS_PATH)
        # The file contains 98 entries
        assert len(recipes) >= 80

    def test_spirit_fields(self):
        recipes = load_runewords(_RUNEWORDS_PATH)
        by_name = {r.name: r for r in recipes}

        spirit = by_name["Spirit"]
        assert spirit.rune_sequence == "Tal-Thul-Ort-Amn"
        assert spirit.socket_count == 4
        bases = json.loads(spirit.base_types)
        assert "sword" in bases
        assert "shield" in bases
        stats = json.loads(spirit.stats_json)
        assert stats["all_skills"] == 2
        assert stats["fhr"] == 55

    def test_enigma_fields(self):
        recipes = load_runewords(_RUNEWORDS_PATH)
        by_name = {r.name: r for r in recipes}

        enigma = by_name["Enigma"]
        assert enigma.rune_sequence == "Jah-Ith-Ber"
        assert enigma.socket_count == 3
        bases = json.loads(enigma.base_types)
        assert "body_armour" in bases
        stats = json.loads(enigma.stats_json)
        assert stats["teleport"] == 1
        assert stats["all_skills"] == 2

    def test_all_recipes_have_valid_json(self):
        """Every recipe must have parseable base_types and stats_json."""
        recipes = load_runewords(_RUNEWORDS_PATH)
        for recipe in recipes:
            bases = json.loads(recipe.base_types)
            assert isinstance(bases, list)
            assert len(bases) >= 1

            stats = json.loads(recipe.stats_json)
            assert isinstance(stats, dict)
            assert len(stats) >= 1


class TestLoadBuildHappyPath:
    """Load data/builds/warlock_echoing_strike_mf.yaml."""

    def test_load_build(self):
        build = load_build(_BUILD_WARLOCK_PATH)
        assert build.name == "warlock_echoing_strike_mf"
        assert build.display_name == "Echoing Strike MF Warlock"
        assert build.character_class == "warlock"
        assert build.formula_module == "warlock_echoing_strike"

    def test_build_skill_points(self):
        build = load_build(_BUILD_WARLOCK_PATH)
        assert build.skill_points["echoing_strike"] == 20
        assert build.skill_points["mirrored_blades"] == 20
        assert build.skill_points["blade_warp"] == 20

    def test_build_objectives(self):
        build = load_build(_BUILD_WARLOCK_PATH)
        obj = build.objectives
        total = obj.damage + obj.magic_find + obj.effective_hp + obj.breakpoint_score
        assert abs(total - 1.0) < 1e-9

    def test_build_constraints(self):
        build = load_build(_BUILD_WARLOCK_PATH)
        assert len(build.constraints) >= 2
        stat_names = {c.stat for c in build.constraints}
        assert "fcr" in stat_names
        assert "resistance_all" in stat_names

    def test_build_presets(self):
        build = load_build(_BUILD_WARLOCK_PATH)
        assert "mf" in build.presets
        assert "dps" in build.presets
        assert "balanced" in build.presets

        # Each preset weights must sum to 1.0
        for preset_name, weights in build.presets.items():
            total = (
                weights.damage + weights.magic_find
                + weights.effective_hp + weights.breakpoint_score
            )
            assert abs(total - 1.0) < 1e-9, (
                f"Preset '{preset_name}' weights sum to {total}"
            )

    def test_build_reference_loadouts(self):
        build = load_build(_BUILD_WARLOCK_PATH)
        assert build.reference_loadouts is not None
        assert len(build.reference_loadouts) >= 1


class TestListBuildsHappyPath:
    """List build files in data/builds/."""

    def test_list_builds(self):
        names = list_builds(_BUILDS_DIR)
        assert len(names) >= 1
        assert "warlock_echoing_strike_mf" in names


class TestLoadBreakpointsHappyPath:
    """Load data/breakpoints.yaml and verify structure."""

    def test_load_breakpoints(self):
        bp = load_breakpoints(_BREAKPOINTS_PATH)
        assert "warlock" in bp

    def test_warlock_fcr_thresholds(self):
        bp = load_breakpoints(_BREAKPOINTS_PATH)
        fcr = bp["warlock"]["fcr"]
        thresholds = [entry["threshold"] for entry in fcr]
        # Known thresholds: 0, 9, 20, 37, 63, 105, 200
        assert 0 in thresholds
        assert 9 in thresholds
        assert 37 in thresholds
        assert 105 in thresholds
        assert 200 in thresholds

    def test_warlock_fhr_present(self):
        bp = load_breakpoints(_BREAKPOINTS_PATH)
        assert "fhr" in bp["warlock"]

    def test_all_entries_have_threshold_and_frames(self):
        bp = load_breakpoints(_BREAKPOINTS_PATH)
        for class_name, stat_tables in bp.items():
            for stat_name, value in stat_tables.items():
                # Some classes (e.g. Druid) have form-specific sub-tables
                if isinstance(value, dict):
                    for form_name, entries in value.items():
                        label = f"{class_name}.{stat_name}.{form_name}"
                        for entry in entries:
                            assert "threshold" in entry, f"{label} entry missing threshold"
                            assert "frames" in entry, f"{label} entry missing frames"
                else:
                    label = f"{class_name}.{stat_name}"
                    for entry in value:
                        assert "threshold" in entry, f"{label} entry missing threshold"
                        assert "frames" in entry, f"{label} entry missing frames"


# ===========================================================================
# Error handling tests — tmp_path fixtures
# ===========================================================================


class TestRunewordErrors:
    """Error paths for the runeword loader."""

    def test_runeword_missing_rune_sequence(self, tmp_path: Path):
        bad_yaml = tmp_path / "bad_runewords.yaml"
        bad_yaml.write_text(
            "runewords:\n"
            "  - name: Broken\n"
            "    socket_count: 3\n"
            "    base_types: [shield]\n"
            "    stats:\n"
            "      ed: 50\n",
            encoding="utf-8",
        )
        with pytest.raises(LoaderError, match="missing required fields"):
            load_runewords(bad_yaml)

    def test_runeword_empty_file(self, tmp_path: Path):
        empty = tmp_path / "empty.yaml"
        empty.write_text("", encoding="utf-8")
        # Empty YAML parses to None -> returns empty list
        result = load_runewords(empty)
        assert result == []

    def test_runeword_empty_list(self, tmp_path: Path):
        f = tmp_path / "empty_list.yaml"
        f.write_text("runewords:\n", encoding="utf-8")
        result = load_runewords(f)
        assert result == []

    def test_runeword_missing_top_level_key(self, tmp_path: Path):
        f = tmp_path / "bad_key.yaml"
        f.write_text("recipes:\n  - name: Foo\n", encoding="utf-8")
        with pytest.raises(LoaderError, match="top-level 'runewords' key"):
            load_runewords(f)

    def test_runeword_not_a_list(self, tmp_path: Path):
        f = tmp_path / "not_list.yaml"
        f.write_text("runewords: not_a_list\n", encoding="utf-8")
        with pytest.raises(LoaderError, match="must be a list"):
            load_runewords(f)

    def test_runeword_rune_sequence_not_list(self, tmp_path: Path):
        f = tmp_path / "seq_bad.yaml"
        f.write_text(
            "runewords:\n"
            "  - name: Bad\n"
            "    rune_sequence: Tal-Thul\n"
            "    socket_count: 2\n"
            "    base_types: [shield]\n"
            "    stats:\n"
            "      ed: 10\n",
            encoding="utf-8",
        )
        with pytest.raises(LoaderError, match="rune_sequence must be a non-empty list"):
            load_runewords(f)

    def test_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            load_runewords(Path("/nonexistent/runewords.yaml"))


class TestBuildErrors:
    """Error paths for the build loader."""

    def test_build_missing_required_field(self, tmp_path: Path):
        """Build YAML missing 'name' triggers Pydantic ValidationError."""
        f = tmp_path / "bad_build.yaml"
        f.write_text(
            # Missing 'name'
            "display_name: Test\n"
            "character_class: warlock\n"
            "description: test\n"
            "formula_module: test\n"
            "skill_points:\n"
            "  strike: 20\n"
            "objectives:\n"
            "  damage: 0.4\n"
            "  magic_find: 0.4\n"
            "  effective_hp: 0.15\n"
            "  breakpoint_score: 0.05\n"
            "constraints: []\n"
            "presets: {}\n",
            encoding="utf-8",
        )
        with pytest.raises(ValidationError):
            load_build(f)

    def test_build_weights_not_summing_to_one(self, tmp_path: Path):
        """Weights summing to 0.8 triggers Pydantic ValidationError."""
        f = tmp_path / "bad_weights.yaml"
        f.write_text(
            "name: test_build\n"
            "display_name: Test\n"
            "character_class: warlock\n"
            "description: test\n"
            "formula_module: test\n"
            "skill_points:\n"
            "  strike: 20\n"
            "objectives:\n"
            "  damage: 0.3\n"
            "  magic_find: 0.3\n"
            "  effective_hp: 0.1\n"
            "  breakpoint_score: 0.1\n"
            "constraints: []\n"
            "presets: {}\n",
            encoding="utf-8",
        )
        with pytest.raises(ValidationError, match="must sum to 1.0"):
            load_build(f)

    def test_build_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.yaml"
        f.write_text("", encoding="utf-8")
        with pytest.raises(LoaderError, match="must contain a YAML mapping"):
            load_build(f)

    def test_build_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            load_build(Path("/nonexistent/build.yaml"))

    def test_list_builds_nonexistent_dir(self):
        with pytest.raises(FileNotFoundError):
            list_builds(Path("/nonexistent/builds/"))


class TestBreakpointErrors:
    """Error paths for the breakpoint loader."""

    def test_breakpoints_malformed_not_list(self, tmp_path: Path):
        """Breakpoints YAML with non-list thresholds triggers LoaderError."""
        f = tmp_path / "bad_bp.yaml"
        f.write_text(
            "breakpoints:\n"
            "  warlock:\n"
            "    fcr: not_a_list\n",
            encoding="utf-8",
        )
        with pytest.raises(LoaderError, match="must be a list"):
            load_breakpoints(f)

    def test_breakpoints_missing_threshold(self, tmp_path: Path):
        f = tmp_path / "missing_threshold.yaml"
        f.write_text(
            "breakpoints:\n"
            "  warlock:\n"
            "    fcr:\n"
            "      - frames: 15\n",
            encoding="utf-8",
        )
        with pytest.raises(LoaderError, match="missing 'threshold' or 'frames'"):
            load_breakpoints(f)

    def test_breakpoints_missing_frames(self, tmp_path: Path):
        f = tmp_path / "missing_frames.yaml"
        f.write_text(
            "breakpoints:\n"
            "  warlock:\n"
            "    fcr:\n"
            "      - threshold: 0\n",
            encoding="utf-8",
        )
        with pytest.raises(LoaderError, match="missing 'threshold' or 'frames'"):
            load_breakpoints(f)

    def test_breakpoints_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.yaml"
        f.write_text("", encoding="utf-8")
        with pytest.raises(LoaderError, match="top-level 'breakpoints' key"):
            load_breakpoints(f)

    def test_breakpoints_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            load_breakpoints(Path("/nonexistent/breakpoints.yaml"))

    def test_breakpoints_class_not_mapping(self, tmp_path: Path):
        f = tmp_path / "class_not_map.yaml"
        f.write_text(
            "breakpoints:\n"
            "  warlock: not_a_mapping\n",
            encoding="utf-8",
        )
        with pytest.raises(LoaderError, match="must be a mapping"):
            load_breakpoints(f)


class TestItemErrors:
    """Error paths for the base items loader."""

    def test_items_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.yaml"
        f.write_text("", encoding="utf-8")
        result = load_base_items(f)
        assert result == []

    def test_items_missing_top_key(self, tmp_path: Path):
        f = tmp_path / "no_key.yaml"
        f.write_text("bases:\n  - name: Shako\n", encoding="utf-8")
        with pytest.raises(LoaderError, match="top-level 'items' or 'base_items' key"):
            load_base_items(f)

    def test_items_nonexistent(self):
        with pytest.raises(FileNotFoundError):
            load_base_items(Path("/nonexistent/items.yaml"))

    def test_items_valid_fixture(self, tmp_path: Path):
        """Verify the loader works with a well-formed items fixture."""
        f = tmp_path / "items.yaml"
        f.write_text(
            "items:\n"
            "  - name: Shako\n"
            "    slot: helmet\n"
            "    max_sockets: 1\n"
            "  - name: Monarch\n"
            "    slot: shield\n"
            "    max_sockets: 4\n",
            encoding="utf-8",
        )
        items = load_base_items(f)
        assert len(items) == 2
        assert items[0]["name"] == "Shako"
        assert items[1]["max_sockets"] == 4


# ===========================================================================
# Cross-reference test
# ===========================================================================


class TestCrossReference:
    """Cross-reference runeword data against known D2R rune names."""

    def test_runeword_rune_names_valid(self):
        """Every rune name in loaded runewords must be a known D2R rune (El through Zod)."""
        recipes = load_runewords(_RUNEWORDS_PATH)
        rune_set = set(_ALL_RUNE_NAMES)

        for recipe in recipes:
            rune_names = recipe.rune_sequence.split("-")
            for rune_name in rune_names:
                assert rune_name in rune_set, (
                    f"Runeword '{recipe.name}' references unknown rune '{rune_name}'. "
                    f"Valid runes: {sorted(rune_set)}"
                )
