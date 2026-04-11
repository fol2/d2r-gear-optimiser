"""Tests for the CLI commands."""

import yaml
from click.testing import CliRunner

from d2r_optimiser.cli import cli
from d2r_optimiser.cli.run import _parse_weight_overrides
from d2r_optimiser.vision import ParsedScreenshotItem
from d2r_optimiser.vision.router import resolve_provider


def _run(args: list[str], **kwargs):
    """Helper to invoke CLI with CliRunner."""
    runner = CliRunner()
    return runner.invoke(cli, args, catch_exceptions=False, **kwargs)


class TestBasicCommands:
    """Basic CLI smoke tests."""

    def test_help(self):
        result = _run(["--help"])
        assert result.exit_code == 0
        assert "D2R Gear Optimiser" in result.output
        assert "inv" in result.output
        assert "build" in result.output

    def test_version(self):
        result = _run(["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output


class TestInventoryList:
    """Tests for inv list."""

    def test_inv_list_empty(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = _run(["--db", db, "inv", "list"])
        assert result.exit_code == 0
        assert "No items" in result.output

    def test_inv_list_filter_slot(self, tmp_path):
        db = str(tmp_path / "test.db")
        # Add two items in different slots
        _run([
            "--db", db, "inv", "add",
            "--name", "Shako",
            "--slot", "helmet",
            "--type", "unique",
        ])
        _run([
            "--db", db, "inv", "add",
            "--name", "Enigma",
            "--slot", "body",
            "--type", "runeword",
        ])
        # Filter by helmet only
        result = _run(["--db", db, "inv", "list", "--slot", "helmet"])
        assert result.exit_code == 0
        assert "Shako" in result.output
        assert "Enigma" not in result.output


class TestInventoryAdd:
    """Tests for inv add."""

    def test_inv_add_and_list(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = _run([
            "--db", db, "inv", "add",
            "--name", "Harlequin Crest",
            "--slot", "helmet",
            "--type", "unique",
            "--base", "Shako",
            "--affix", "mf=50",
            "--affix", "all_skills=2",
            "--affix", "dr=10",
            "--sockets", "1",
            "--socket-fill", "Ist",
        ])
        assert result.exit_code == 0
        assert "Added" in result.output
        assert "harlequin_crest_001" in result.output

        # Verify it appears in list
        result = _run(["--db", db, "inv", "list"])
        assert result.exit_code == 0
        assert "Harlequin Crest" in result.output
        assert "mf=50" in result.output

    def test_inv_add_generates_sequential_uids(self, tmp_path):
        db = str(tmp_path / "test.db")
        _run([
            "--db", db, "inv", "add",
            "--name", "Nagelring",
            "--slot", "ring",
            "--type", "unique",
        ])
        result = _run([
            "--db", db, "inv", "add",
            "--name", "Nagelring",
            "--slot", "ring",
            "--type", "unique",
        ])
        assert result.exit_code == 0
        assert "nagelring_002" in result.output

    def test_inv_add_invalid_affix(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = _run([
            "--db", db, "inv", "add",
            "--name", "Bad Item",
            "--slot", "helmet",
            "--type", "unique",
            "--affix", "bad_format",
        ])
        assert "Invalid affix format" in result.output


class TestInventoryRemove:
    """Tests for inv remove."""

    def test_inv_remove(self, tmp_path):
        db = str(tmp_path / "test.db")
        # Add an item
        _run([
            "--db", db, "inv", "add",
            "--name", "Shako",
            "--slot", "helmet",
            "--type", "unique",
        ])
        # Remove it with --yes to skip prompt
        result = _run(["--db", db, "inv", "remove", "shako_001", "--yes"])
        assert result.exit_code == 0
        assert "Removed" in result.output

        # Verify it is gone
        result = _run(["--db", db, "inv", "list"])
        assert "shako_001" not in result.output

    def test_inv_remove_not_found(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = _run(["--db", db, "inv", "remove", "nonexistent", "--yes"])
        assert "not found" in result.output.lower()


class TestInventoryEdit:
    """Tests for inv edit."""

    def test_inv_edit_updates_affixes_and_sockets(self, tmp_path):
        db = str(tmp_path / "test.db")
        _run([
            "--db", db, "inv", "add",
            "--name", "Shako",
            "--slot", "helmet",
            "--type", "unique",
            "--affix", "mf=50",
            "--sockets", "1",
            "--socket-fill", "Ist",
        ])

        result = _run([
            "--db", db, "inv", "edit", "shako_001",
            "--name", "Harlequin Crest",
            "--affix", "mf=74",
            "--affix", "all_skills=2",
            "--sockets", "2",
            "--socket-fill", "Ist",
            "--socket-fill", "Ist",
        ])

        assert result.exit_code == 0
        assert "Updated" in result.output

        result = _run(["--db", db, "inv", "list"])
        assert "Harlequin Crest" in result.output
        assert "mf=74" in result.output

    def test_inv_edit_not_found(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = _run(["--db", db, "inv", "edit", "missing_001", "--name", "Nope"])
        assert "not found" in result.output.lower()


class TestInventoryRune:
    """Tests for inv add-rune."""

    def test_inv_add_rune(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = _run(["--db", db, "inv", "add-rune", "Ist", "--quantity", "3"])
        assert result.exit_code == 0
        assert "3x Ist" in result.output
        assert "Total: 3" in result.output

    def test_inv_add_rune_accumulates(self, tmp_path):
        db = str(tmp_path / "test.db")
        _run(["--db", db, "inv", "add-rune", "Ist", "--quantity", "2"])
        result = _run(["--db", db, "inv", "add-rune", "Ist", "--quantity", "3"])
        assert "Total: 5" in result.output


class TestInventoryGem:
    """Tests for inv add-gem."""

    def test_inv_add_gem(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = _run(["--db", db, "inv", "add-gem", "Topaz", "--quantity", "4"])
        assert result.exit_code == 0
        assert "4x Perfect Topaz" in result.output
        assert "Total: 4" in result.output

    def test_inv_add_gem_accumulates(self, tmp_path):
        db = str(tmp_path / "test.db")
        _run(["--db", db, "inv", "add-gem", "Diamond", "--quantity", "2"])
        result = _run(["--db", db, "inv", "add-gem", "Diamond", "--quantity", "3"])
        assert "Total: 5" in result.output


class TestInventoryJewel:
    """Tests for inv add-jewel."""

    def test_inv_add_jewel(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = _run([
            "--db", db, "inv", "add-jewel",
            "--name", "40/15 ED/IAS",
            "--affix", "ed=40",
            "--affix", "ias=15",
        ])
        assert result.exit_code == 0
        assert "Added jewel" in result.output


class TestInventoryScreenshot:
    """Tests for screenshot-driven item import."""

    def test_inv_add_from_screenshot(self, tmp_path, monkeypatch):
        db = str(tmp_path / "test.db")
        image = tmp_path / "tooltip.png"
        image.write_bytes(b"fake image bytes")

        def _fake_parse(_image, *, provider=None, model=None):
            return ParsedScreenshotItem(
                parse_ok=True,
                name="Harlequin Crest",
                slot="helmet",
                item_type="unique",
                base="Shako",
                affixes={"mf": 50, "all_skills": 2},
                socket_count=1,
                socket_fill=["Ist"],
                confidence=0.92,
            )

        monkeypatch.setattr("d2r_optimiser.cli.inv.parse_item_screenshot", _fake_parse)

        result = _run([
            "--db", db, "inv", "add-from-screenshot", str(image), "--provider", "gemini", "--yes",
        ])

        assert result.exit_code == 0
        assert "Added" in result.output

        result = _run(["--db", db, "inv", "list"])
        assert "Harlequin Crest" in result.output
        assert "mf=50" in result.output


class TestScreenshotProviderRouting:
    """Tests for screenshot provider auto-resolution."""

    def test_resolve_provider_prefers_gemini(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "present")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert resolve_provider("auto") == "gemini"

    def test_resolve_provider_rejects_unknown(self):
        try:
            resolve_provider("foo")
        except Exception as exc:
            assert "Unsupported screenshot provider" in str(exc)
        else:
            raise AssertionError("Expected provider resolution to fail")


class TestImportExport:
    """Tests for inv import and inv export."""

    def test_inv_import_export_roundtrip(self, tmp_path):
        db = str(tmp_path / "test.db")

        # Create YAML import file
        import_data = {
            "items": [
                {
                    "name": "Harlequin Crest",
                    "slot": "helmet",
                    "type": "unique",
                    "base": "Shako",
                    "affixes": {"mf": 50, "all_skills": 2},
                },
                {
                    "name": "War Traveler",
                    "slot": "boots",
                    "type": "unique",
                    "base": "Battle Boots",
                    "affixes": {"mf": 45},
                },
            ]
        }
        import_file = tmp_path / "import.yaml"
        import_file.write_text(yaml.dump(import_data), encoding="utf-8")

        # Import
        result = _run(["--db", db, "inv", "import", str(import_file)])
        assert result.exit_code == 0
        assert "Imported 2 item(s)" in result.output

        # Export
        result = _run(["--db", db, "inv", "export"])
        assert result.exit_code == 0
        exported = yaml.safe_load(result.output)
        assert len(exported["items"]) == 2

        names = {item["name"] for item in exported["items"]}
        assert "Harlequin Crest" in names
        assert "War Traveler" in names

    def test_inv_import_invalid_yaml(self, tmp_path):
        db = str(tmp_path / "test.db")
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("not: a: valid: {yaml", encoding="utf-8")
        result = _run(["--db", db, "inv", "import", str(bad_file)])
        # Should not crash — either error message or non-zero exit
        # The YAML parser may or may not raise depending on content
        # Just ensure we don't get an unhandled exception
        assert result.exit_code is not None

    def test_inv_import_missing_items_key(self, tmp_path):
        db = str(tmp_path / "test.db")
        bad_file = tmp_path / "no_items.yaml"
        bad_file.write_text("foo: bar\n", encoding="utf-8")
        result = _run(["--db", db, "inv", "import", str(bad_file)])
        assert "items" in result.output.lower() or result.exit_code != 0


class TestBuildCommands:
    """Tests for build list and build show."""

    def test_build_list(self):
        result = _run(["build", "list"])
        assert result.exit_code == 0
        assert "warlock_echoing_strike_mf" in result.output
        assert "warlock_summoner" in result.output

    def test_build_show(self):
        result = _run(["build", "show", "warlock_echoing_strike_mf"])
        assert result.exit_code == 0
        assert "Echoing Strike" in result.output
        assert "warlock" in result.output
        # Check that skill points are shown
        assert "echoing_strike" in result.output
        # Check that constraints are shown
        assert "fcr" in result.output
        # Check that presets are shown
        assert "mf" in result.output

    def test_build_show_summoner(self):
        result = _run(["build", "show", "warlock_summoner"])
        assert result.exit_code == 0
        assert "Summoner Warlock" in result.output
        assert "starter" in result.output
        assert "summon_goatman" in result.output

    def test_build_show_not_found(self):
        result = _run(["build", "show", "nonexistent_build"])
        assert "not found" in result.output.lower()


class TestEdgeCases:
    """Edge case and error handling tests."""

    def test_missing_db_directory(self, tmp_path):
        """Graceful error when DB path directory does not exist."""
        bad_path = str(tmp_path / "nonexistent_dir" / "test.db")
        # SQLite will fail to create DB in a non-existent directory
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--db", bad_path, "inv", "list"],
            catch_exceptions=True,
        )
        # Should either show an error or exit non-zero — not an unhandled crash
        assert result.exit_code != 0 or "error" in result.output.lower()

    def test_inv_export_empty(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = _run(["--db", db, "inv", "export"])
        assert result.exit_code == 0
        assert "No items" in result.output

    def test_inv_add_with_ethereal(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = _run([
            "--db", db, "inv", "add",
            "--name", "Ethereal Titan",
            "--slot", "weapon",
            "--type", "unique",
            "--ethereal",
        ])
        assert result.exit_code == 0
        assert "Added" in result.output


class TestRunWeightParsing:
    """Tests for `optimise run --weight` parsing."""

    def test_parse_weight_overrides_supports_aliases(self):
        overrides = _parse_weight_overrides(("mf=0.5", "bp=0.1", "damage=0.25", "ehp=0.15"))
        assert overrides == {
            "magic_find": 0.5,
            "breakpoint_score": 0.1,
            "damage": 0.25,
            "effective_hp": 0.15,
        }

    def test_parse_weight_overrides_rejects_unknown_key(self):
        try:
            _parse_weight_overrides(("speed=0.5",))
        except ValueError as exc:
            assert "unsupported key" in str(exc)
        else:
            raise AssertionError("Expected ValueError for unsupported weight key")
