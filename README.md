# D2R Gear Optimiser

Exhaustive gear loadout optimiser for Diablo II: Resurrected. Given a player's inventory (items, runes, jewels) and a build definition, the optimiser searches all valid equipment combinations to find the top-K loadouts that maximise a weighted scoring formula while respecting hard constraints (FCR breakpoints, resistance caps, etc.).

## Installation

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <repo-url> && cd d2r-planner
uv sync
uv run optimise --help
```

## Quick Start

```bash
# 1. Add items to your inventory
uv run optimise inv add --name "Harlequin Crest" --slot helmet --type unique \
    --affix mf=50 --affix all_skills=2 --affix dr=10

# 2. Add runes to the pool
uv run optimise inv add-rune Ist --quantity 2

# 3. Bulk import from YAML
uv run optimise inv import my_stash.yaml

# 4. Run the optimiser
uv run optimise run warlock_echoing_strike_mf

# 5. Run with a weight preset
uv run optimise run warlock_echoing_strike_mf --mode mf --top-k 3

# 6. Output as JSON for scripting
uv run optimise run warlock_echoing_strike_mf --json
```

## CLI Command Reference

| Command | Description |
|---|---|
| `optimise --help` | Show top-level help and available commands |
| `optimise inv list [--slot X] [--type Y]` | List inventory items with optional filters |
| `optimise inv add --name --slot --type [--affix stat=val ...]` | Add a single item |
| `optimise inv remove <uid> [--yes]` | Remove an item by UID |
| `optimise inv import <file.yaml>` | Bulk import items from YAML |
| `optimise inv export` | Export full inventory to YAML |
| `optimise inv add-rune <type> [--quantity N]` | Add runes to the pool |
| `optimise inv add-jewel --name --affix stat=val ...` | Add a jewel with affixes |
| `optimise build list` | List available build definitions |
| `optimise build show <name>` | Show full details for a build |
| `optimise run <build> [--mode M] [--top-k N] [--workers W] [--json]` | Run the gear optimiser |
| `optimise validate record <id> --actual-mf X --predicted-mf Y ...` | Record a live measurement |
| `optimise validate check [--build name]` | Show deviation report for all validations |

### Global Options

- `--db <path>` : SQLite database path (default: `stash.db`, env: `D2R_DB_PATH`)
- `--verbose` : Enable debug logging
- `--version` : Show version

## Architecture

The system is organised in four layers: data loading, domain logic, search engine, and CLI.

```
+----------------------------------------------------------+
|  CLI Layer (click + rich)                                |
|  inv | build | run | validate                            |
+----------------------------------------------------------+
|  Orchestrator (core/orchestrator.py)                     |
|  Wires loaders, DB, resolver, search engine together     |
+----------------------------------------------------------+
|  Core Domain                                             |
|  +------------+  +-----------+  +----------+  +--------+ |
|  | Formula    |  | Search    |  | Resolver |  | Valid. | |
|  | (scoring)  |  | (engine)  |  | (rw/sock)|  |        | |
|  +------------+  +-----------+  +----------+  +--------+ |
+----------------------------------------------------------+
|  Data Layer                                              |
|  +------------+  +-----------+  +----------+             |
|  | Loader     |  | DB/ORM    |  | Models   |             |
|  | (YAML)     |  | (SQLite)  |  | (Pydantic|             |
|  +------------+  +-----------+  | /SQLModel)|            |
+----------------------------------------------------------+
|  data/  (YAML reference files)                           |
|  runewords.yaml | runes.yaml | breakpoints.yaml          |
|  items.yaml | builds/ | uniques.yaml | sets.yaml         |
+----------------------------------------------------------+
```

**Search algorithm**: exhaustive slot-by-slot assignment with hard-constraint pruning and resource-conflict detection. The weapon slot is sharded across worker processes for parallelism. A min-heap maintains the top-K results without storing the full result set.

## Adding New Builds

1. Create `data/builds/<build_name>.yaml` following the existing template
2. Implement a formula class in `src/d2r_optimiser/core/formula/<module>.py`
3. Set `formula_module` in the YAML to match the module name
4. Define objectives, constraints, and presets in the YAML
5. Test: `uv run optimise build show <build_name>`

## Data Files

| File | Contents |
|---|---|
| `data/runewords.yaml` | 98 runeword recipes with rune sequences, base types, and stats |
| `data/runes.yaml` | 33 runes with weapon/armour/shield stat variants |
| `data/breakpoints.yaml` | FCR/FHR/FBR breakpoint tables per class |
| `data/items.yaml` | 118 base item types with slots and socket counts |
| `data/uniques.yaml` | 36 unique items with full affix data |
| `data/sets.yaml` | 6 set definitions with per-piece and set-bonus stats |
| `data/builds/` | Build definition YAML files |

## Development

```bash
# Run tests
uv run pytest tests/ -v

# Run linter
uv run ruff check src/ tests/

# Run a specific test file
uv run pytest tests/unit/test_orchestrator.py -v
```
