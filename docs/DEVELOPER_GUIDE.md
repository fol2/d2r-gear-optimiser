# D2R Gear Optimiser -- Developer Guide

A reference for developers and contributors working on the D2R Gear Optimiser codebase.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [Adding a New Build](#adding-a-new-build)
- [Adding a New Class](#adding-a-new-class)
- [Key Design Decisions](#key-design-decisions)
- [Testing Guide](#testing-guide)
- [Data File Formats](#data-file-formats)
- [Formula Validation Pipeline](#formula-validation-pipeline)
- [Performance](#performance)

---

## Architecture Overview

### Layer Diagram

```
+----------------------------------------------------------+
|  CLI Layer (Click + Rich)                                |
|  optimise inv | build | run | validate                   |
+----------------------------------------------------------+
|  Orchestrator (core/orchestrator.py)                     |
|  Wires loaders, DB, resolver, search, formula together   |
+----------------------------------------------------------+
|  Core Domain (no I/O -- pure logic)                      |
|  +------------+  +-----------+  +----------+  +--------+ |
|  | Formula    |  | Search    |  | Resolver |  | Valid. | |
|  | (scoring)  |  | (engine)  |  | (rw/sock)|  |        | |
|  +------------+  +-----------+  +----------+  +--------+ |
+----------------------------------------------------------+
|  Data Layer                                              |
|  +------------+  +-----------+  +----------+             |
|  | Loader     |  | DB/ORM    |  | Models   |             |
|  | (YAML)     |  | (SQLite)  |  | (SQLModel|             |
|  +------------+  +-----------+  | /Pydantic)|            |
+----------------------------------------------------------+
|  data/  (YAML reference files)                           |
|  runewords.yaml | runes.yaml | breakpoints.yaml          |
|  items.yaml | builds/ | uniques.yaml | sets.yaml         |
+----------------------------------------------------------+
```

### Component Responsibilities

**CLI Layer** (`cli/`): Click command groups with Rich terminal output. Thin layer -- parses arguments, calls the orchestrator or DB helpers, and renders results. All formatting (tables, panels, colour coding) lives here.

**Orchestrator** (`core/orchestrator.py`): The single public entry point `optimise()` that wires the full pipeline. Loads the build definition, queries inventory from SQLite, runs the resource resolver to expand the candidate pool, dispatches the search engine (single-threaded or parallel), and returns ranked results. Raises `BuildNotFoundError` and `EmptyInventoryError` for known failure modes.

**Formula Engine** (`core/formula/`): Protocol-based scoring. Each build has its own formula class implementing `BuildFormula`. The `base.py` module defines the Protocol and a factory function `get_formula()` that dynamically imports formula modules by name. Shared utilities (MF diminishing returns, breakpoint lookup, stat aggregation, constraint checking) live in `common.py`.

**Search Engine** (`core/search/`): Exhaustive slot-by-slot combinatorial search with hard-constraint-only pruning. `engine.py` implements the recursive search with a min-heap for top-K tracking. `pruning.py` handles constraint checks and resource conflict detection. `parallel.py` shards the search by weapon slot across worker processes using `ProcessPoolExecutor`.

**Resource Resolver** (`core/resolver/`): Preprocessor that expands the raw inventory into a full candidate pool. `runewords.py` enumerates all craftable runewords from the rune pool and socket bases. `sockets.py` enumerates socket-filling combinations (runes/jewels into empty sockets).

**Validator** (`core/validation/`): Compares predicted stats from the formula engine against reference data and live in-game measurements. Records validations to the database and produces deviation reports.

**Models** (`core/models/`): Pydantic v2 and SQLModel definitions for all domain entities. SQLModel tables for persistent data (Item, Affix, Socket, Rune, Jewel, Loadout, ValidationRecord). Plain Pydantic BaseModel for value objects (BuildDefinition, ObjectiveWeights, Constraint, ScoreBreakdown, LoadoutSlot).

**DB** (`core/db/`): SQLite database session factory and schema initialisation. Configurable via `D2R_DB_PATH` environment variable.

**Loader** (`loader/`): YAML file parsers that return domain model instances. One loader per data file type (runewords, builds, items, breakpoints).

### Data Flow

```
optimise run warlock_echoing_strike_mf --mode mf
        |
        v
   CLI (run.py) -- parse args, resolve --mode
        |
        v
   orchestrator.optimise()
        |
        +-- load_build() -----> data/builds/warlock_echoing_strike_mf.yaml
        |                           -> BuildDefinition model
        +-- load_runewords() -> data/runewords.yaml
        |                           -> list[RunewordRecipe]
        +-- load_breakpoints() -> data/breakpoints.yaml
        |                           -> dict
        +-- SQLite query -----> stash.db
        |                           -> items + runes + jewels
        |
        v
   Resource Resolver
        |
        +-- enumerate_craftable_runewords(rune_pool, bases, recipes)
        +-- enumerate_socket_options(item, runes, jewels)
        |
        v
   Candidate Pool (candidates_by_slot: dict[str, list[dict]])
        |
        v
   Search Engine
        |
        +-- parallel_search() -- shard by weapon slot
        |       +-- worker 1: search(weapon=A, remaining_slots)
        |       +-- worker 2: search(weapon=B, remaining_slots)
        |       +-- ...
        |       +-- merge top-K from all workers
        |
        v
   Formula Engine
        |   (called per complete loadout in the search)
        +-- formula.score(stats, build) -> ScoreBreakdown
        +-- _compute_total_score(breakdown, build) -> float
        |
        v
   Ranked top-K results
        |
        v
   CLI output (Rich table or JSON)
```

---

## Project Structure

```
d2r-planner/
|-- src/
|   +-- d2r_optimiser/
|       |-- __init__.py              # Package version (__version__)
|       |-- core/
|       |   |-- __init__.py
|       |   |-- orchestrator.py      # Top-level optimise() entry point
|       |   |-- models/
|       |   |   |-- __init__.py      # Re-exports all public model classes
|       |   |   |-- _common.py       # Shared helpers (utcnow)
|       |   |   |-- item.py          # Item, Affix, Socket (SQLModel tables)
|       |   |   |-- rune.py          # Rune, Jewel, JewelAffix, RunewordRecipe
|       |   |   |-- build.py         # BuildDefinition, ObjectiveWeights, Constraint
|       |   |   |-- loadout.py       # Loadout, LoadoutItem, LoadoutSlot, ScoreBreakdown
|       |   |   +-- validation.py    # ValidationRecord
|       |   |-- db/
|       |   |   |-- __init__.py      # Re-exports get_engine, create_all_tables, reset_engine
|       |   |   |-- schema.py        # Imports all SQLModel tables for metadata registration
|       |   |   +-- session.py       # Engine factory, session management
|       |   |-- formula/
|       |   |   |-- __init__.py      # Re-exports BuildFormula, get_formula, helpers
|       |   |   |-- base.py          # BuildFormula Protocol + get_formula() factory
|       |   |   |-- common.py        # effective_mf, lookup_breakpoint, aggregate_stats, constraints
|       |   |   +-- warlock_echoing_strike.py  # EchoingStrikeFormula implementation
|       |   |-- resolver/
|       |   |   |-- __init__.py      # Re-exports enumerate_craftable_runewords, enumerate_socket_options
|       |   |   |-- runewords.py     # Runeword enumeration from rune pool + socket bases
|       |   |   +-- sockets.py       # Socket filling combination enumeration
|       |   |-- search/
|       |   |   |-- __init__.py      # Re-exports search, parallel_search
|       |   |   |-- engine.py        # Exhaustive recursive search with top-K heap
|       |   |   |-- pruning.py       # Hard constraint checks, resource conflict detection
|       |   |   +-- parallel.py      # ProcessPoolExecutor weapon-sharded parallelism
|       |   +-- validation/
|       |       |-- __init__.py      # Re-exports validate_against_reference, record_live_measurement, check_all_validations
|       |       +-- validator.py     # Deviation computation, DB persistence
|       |-- cli/
|       |   |-- __init__.py          # Registers all command groups on the cli object
|       |   |-- main.py              # Root Click group (--db, --verbose, --version)
|       |   |-- _db_helpers.py       # ensure_db() helper for session creation
|       |   |-- inv.py               # inv list|add|remove|import|export|add-rune|add-jewel
|       |   |-- build.py             # build list|show
|       |   |-- run.py               # run <build> [--mode] [--top-k] [--workers] [--json]
|       |   +-- validate.py          # validate record|check
|       +-- loader/
|           |-- __init__.py          # Re-exports all loader functions + LoaderError
|           |-- builds.py            # load_build(), list_builds()
|           |-- runewords.py         # load_runewords()
|           |-- items.py             # load_base_items()
|           +-- breakpoints.py       # load_breakpoints()
|-- data/
|   |-- items.yaml                   # 118 base item types (slots, sockets, requirements)
|   |-- uniques.yaml                 # 36 unique items with full affix data
|   |-- sets.yaml                    # 6 set definitions with per-piece and set-bonus stats
|   |-- runewords.yaml               # 98 runeword recipes with rune sequences and stats
|   |-- runes.yaml                   # 33 runes with weapon/armour/shield stat variants
|   |-- breakpoints.yaml             # FCR/FHR/FBR breakpoint tables per class
|   +-- builds/
|       +-- warlock_echoing_strike_mf.yaml  # V1 reference build definition
|-- tests/
|   |-- __init__.py
|   |-- conftest.py                  # Shared pytest fixtures and configuration
|   |-- unit/
|   |   |-- __init__.py
|   |   |-- test_models.py           # Model instantiation, validation, round-trip
|   |   |-- test_loaders.py          # Loader happy paths and malformed-input rejection
|   |   |-- test_resolver.py         # Runeword and socket enumeration
|   |   |-- test_formula.py          # MF curve, breakpoint lookup, formula scoring
|   |   |-- test_search.py           # Search engine, pruning, resource conflicts
|   |   |-- test_validation.py       # Deviation computation, record persistence
|   |   |-- test_orchestrator.py     # End-to-end orchestrator with fixture DB
|   |   +-- test_cli.py              # Click CliRunner tests for all commands
|   |-- integration/
|   |   |-- __init__.py
|   |   +-- test_end_to_end.py       # Full pipeline from empty DB to ranked loadouts
|   +-- fixtures/
|       |-- __init__.py
|       +-- maxroll_echoing_strike.py  # Maxroll reference loadout data for validation
|-- docs/
|   |-- specs/
|   |   +-- design.md                # Locked design specification
|   +-- plans/
|       +-- implementation.md        # Phased implementation plan
|-- pyproject.toml
|-- CLAUDE.md                        # AI assistant project instructions
+-- README.md
```

---

## Adding a New Build

Adding a new build requires two files and no changes to core code. This is by design -- the Protocol pattern and dynamic factory function make build extensions pure additions.

### Step 1: Create the Build Definition YAML

Create `data/builds/<build_name>.yaml`:

```yaml
# ─── Metadata ───────────────────────────────────────────────────────────────
name: warlock_hydra_mf
display_name: "Hydra MF Warlock"
character_class: warlock
description: |
  Fire-based MF farmer using Hydra for safe, off-screen clearing.
  Target 105% FCR breakpoint for comfortable play.
  Core loop: Teleport to pack → cast Hydra → Teleport away → loot.

formula_module: warlock_hydra  # maps to core/formula/warlock_hydra.py

# ─── Skill Allocation ──────────────────────────────────────────────────────
skill_points:
  hydra: 20          # Primary damage skill
  fire_mastery: 20   # Synergy — scales fire damage
  fire_bolt: 20      # Synergy
  fire_ball: 20      # Synergy
  warmth: 1          # Mana regeneration
  teleport: 1        # Mobility (from Enigma or +skills)
  # ... remaining points

# ─── Objectives (default weights, must sum to 1.0) ─────────────────────────
objectives:
  damage: 0.40
  magic_find: 0.35
  effective_hp: 0.15
  breakpoint_score: 0.10

# ─── Hard Constraints ──────────────────────────────────────────────────────
constraints:
  - stat: fcr
    operator: ">="
    value: 105          # 105% FCR breakpoint
  - stat: resistance_all
    operator: ">="
    value: 75           # Max res in Hell
  - stat: strength
    operator: ">="
    value: 0            # Dynamically checked against gear requirements
  - stat: dexterity
    operator: ">="
    value: 0

# ─── Weight Presets ─────────────────────────────────────────────────────────
# Each preset must have damage + magic_find + effective_hp + breakpoint_score = 1.0
presets:
  mf:
    damage: 0.25
    magic_find: 0.50
    effective_hp: 0.15
    breakpoint_score: 0.10
  dps:
    damage: 0.55
    magic_find: 0.15
    effective_hp: 0.20
    breakpoint_score: 0.10
  balanced:
    damage: 0.35
    magic_find: 0.35
    effective_hp: 0.20
    breakpoint_score: 0.10
  survivability:
    damage: 0.20
    magic_find: 0.20
    effective_hp: 0.45
    breakpoint_score: 0.15

# ─── Reference Loadouts (optional, for validation) ─────────────────────────
reference_loadouts:
  - name: "Standard Endgame"
    source: "https://maxroll.gg/d2/guides/hydra-warlock-guide"
    notes: "Standard endgame setup."
    gear:
      weapon: "Arioc's Needle"
      shield: "Spirit Monarch"
      # ... full gear list
    expected_stats:
      fcr: 125
      magic_find: 200
      plus_all_skills: 12
```

**Key rules:**
- `formula_module` must match the Python module name (without `.py`).
- `objectives` weights must sum to exactly 1.0 (tolerance: 0.99 -- 1.01).
- Each preset must also sum to 1.0.
- Constraints use operators: `>=`, `<=`, `==`, `>`, `<`.

### Step 2: Create the Formula Module

Create `src/d2r_optimiser/core/formula/<formula_module>.py`:

```python
"""Warlock Hydra MF build formula.

Implements the BuildFormula protocol via structural typing.
"""

from __future__ import annotations

from d2r_optimiser.core.formula.common import effective_mf, lookup_breakpoint
from d2r_optimiser.core.models import BuildDefinition, ScoreBreakdown


class HydraFormula:
    """Warlock Hydra MF build formula.

    Naming convention: the class name must end with 'Formula'.
    The get_formula() factory discovers it automatically.
    """

    def __init__(self, breakpoints: dict | None = None) -> None:
        self._breakpoints = breakpoints or {}

    def compute_damage(self, stats: dict[str, float], build: BuildDefinition) -> float:
        """Compute normalised damage score (0-1)."""
        # Implement Hydra-specific damage formula here
        # Use stats["ed"], stats["all_skills"], stats["fcr"], etc.
        ...
        return min(raw / ceiling, 1.0)

    def compute_mf(self, stats: dict[str, float], build: BuildDefinition) -> float:
        """Compute normalised MF score (0-1)."""
        raw_mf = stats.get("mf", 0.0)
        eff = effective_mf(raw_mf)
        return eff["unique"] / 250.0

    def compute_ehp(self, stats: dict[str, float], build: BuildDefinition) -> float:
        """Compute normalised EHP score (0-1)."""
        # Implement survivability formula
        ...
        return min(raw_ehp / ceiling, 1.0)

    def compute_breakpoint_score(
        self, stats: dict[str, float], build: BuildDefinition
    ) -> float:
        """Compute breakpoint attainment score (0-1)."""
        # Check FCR, FHR, resistance targets
        ...
        return score

    def score(self, stats: dict[str, float], build: BuildDefinition) -> ScoreBreakdown:
        """Compute all dimensions and return a ScoreBreakdown."""
        return ScoreBreakdown(
            damage=self.compute_damage(stats, build),
            magic_find=self.compute_mf(stats, build),
            effective_hp=self.compute_ehp(stats, build),
            breakpoint_score=self.compute_breakpoint_score(stats, build),
        )
```

**Key rules:**
- The class name must end with `Formula` (e.g. `HydraFormula`).
- No inheritance required -- the `BuildFormula` Protocol uses structural typing.
- All `compute_*` methods receive pre-aggregated `stats: dict[str, float]` (the search engine sums all item affixes before calling the formula).
- Return values are normalised to [0, 1] for consistent weighting.
- Use helpers from `common.py` for MF curves, breakpoint lookups, and constraint checks.

### Step 3: Add Tests

Create `tests/unit/test_formula_<build_name>.py`:

```python
"""Tests for the Warlock Hydra formula."""

import pytest
from d2r_optimiser.core.formula.base import get_formula


def test_factory_resolves_hydra():
    formula = get_formula("warlock_hydra")
    assert formula is not None
    assert hasattr(formula, "compute_damage")
    assert hasattr(formula, "score")


def test_zero_stats_produces_low_scores(sample_build):
    formula = get_formula("warlock_hydra")
    breakdown = formula.score({}, sample_build)
    assert breakdown.damage < 0.1
    assert breakdown.magic_find == 0.0


def test_known_loadout_scoring(sample_build, reference_stats):
    formula = get_formula("warlock_hydra")
    breakdown = formula.score(reference_stats, sample_build)
    # Assert expected values within tolerance
    assert 0.5 < breakdown.damage < 0.9
    assert 0.3 < breakdown.magic_find < 0.8
```

### Why No Core Changes Are Needed

The `get_formula()` factory in `base.py` uses dynamic import:

```python
def get_formula(module_name: str) -> BuildFormula:
    full_module = f"d2r_optimiser.core.formula.{module_name}"
    mod = importlib.import_module(full_module)
    # Finds the first class ending with "Formula"
    for _name, obj in inspect.getmembers(mod, inspect.isclass):
        if _name.endswith("Formula") and obj.__module__ == mod.__name__:
            return obj()
```

The build YAML's `formula_module` field tells the orchestrator which module to import. The search engine, CLI, and resolver are completely build-agnostic.

### Step 4: Verify

```bash
# Check the build loads correctly
uv run optimise build show warlock_hydra_mf

# Run the optimiser (requires items in your inventory)
uv run optimise run warlock_hydra_mf

# Run your tests
uv run pytest tests/unit/test_formula_warlock_hydra.py -v
```

---

## Adding a New Class

Adding a class beyond Warlock requires changes in several areas, though the core architecture remains unchanged.

### What Needs to Change

**1. Breakpoints in `data/breakpoints.yaml`**

Add FCR/FHR/FBR breakpoint tables for the new class. The file already has a structure that supports any number of classes:

```yaml
sorceress:
  fcr:
    - { threshold: 0, frames: 13 }
    - { threshold: 9, frames: 12 }
    - { threshold: 20, frames: 11 }
    - { threshold: 37, frames: 10 }
    - { threshold: 63, frames: 9 }
    - { threshold: 105, frames: 8 }
    - { threshold: 200, frames: 7 }
  fhr:
    - { threshold: 0, frames: 15 }
    - { threshold: 5, frames: 14 }
    # ...
```

**2. New Formula Module**

Create `src/d2r_optimiser/core/formula/<class_build>.py` implementing the `BuildFormula` Protocol. Class-specific mechanics (e.g. Paladin auras, Necromancer summon scaling, Amazon attack speed tables) are encoded in the formula.

**3. New Build YAML**

Create `data/builds/<class_build_variant>.yaml` with the build definition.

**4. Class-Specific Base Stats (if needed)**

The current Echoing Strike formula hard-codes Warlock base stats (base life, life per vitality, etc.) as module-level constants. A new class formula would define its own constants. If multiple builds of the same class share base stats, extract them into a shared module (e.g. `core/formula/_class_stats.py`).

**5. CLI Changes**

No CLI changes are needed for `--mode` presets -- these are defined per-build in the YAML. The `--mode` option accepts any preset name defined in the build file.

If new stat types are introduced (e.g. Amazon-specific stats), they are handled naturally by the EAV affix model -- just use new `stat` keys.

---

## Key Design Decisions

### Why SQLite (not YAML) for Inventory

Player inventory is mutable, relational, and queried frequently during optimisation. SQLite provides:

- **ACID transactions** for safe concurrent reads/writes.
- **Indexed queries** by slot, type, item_id -- important for filtering the candidate pool.
- **Foreign keys** to enforce referential integrity (item -> affixes, item -> sockets).
- **Persistence** without serialisation overhead.

YAML is used for static reference data (runewords, builds, breakpoints) that is committed to version control and changes rarely.

### Why Exhaustive Search (not Greedy/GA)

The user explicitly wants **unexpected, non-obvious combinations** surfaced. Greedy algorithms converge on locally optimal solutions and miss globally superior but counter-intuitive loadouts. Genetic algorithms do not guarantee finding the true optimum.

Exhaustive search with hard-constraint pruning ensures every valid combination is evaluated. The performance budget (1-5 minutes for 200 items) is acceptable for this use case. Score-based pruning is deliberately excluded to avoid filtering out novel solutions.

### Why Protocol (not ABC) for Formula

The `BuildFormula` Protocol uses structural typing -- a class satisfies the protocol by having the right methods, without inheriting from a base class. Benefits:

- **No coupling**: Formula implementations do not import or depend on the protocol definition.
- **Testability**: Any object with the right method signatures works, making mocks trivial.
- **Simplicity**: No metaclass machinery, no `super()` calls, no registration patterns.
- **Runtime checkable**: The protocol is decorated with `@runtime_checkable` for optional isinstance checks.

### Why EAV for Affixes

D2R has 200+ possible affixes. A traditional wide-column table (one column per stat) would be impractical and require schema changes for every new stat type. The Entity-Attribute-Value pattern (the `Affix` table with `stat` and `value` columns) provides:

- **Extensibility**: New stats require zero schema changes.
- **Sparse storage**: Items only store the affixes they have.
- **Uniform aggregation**: The search engine sums stats with a single generic loop rather than per-column logic.

The trade-off is that type-specific validation is done at the application layer, not the database layer.

### Why Multiprocessing (not Threading)

Python's GIL prevents true CPU parallelism with threads. The search engine is CPU-bound (combinatorial enumeration, constraint checking, formula computation). `multiprocessing` with `ProcessPoolExecutor` achieves genuine parallel execution.

The search is naturally shardable by weapon slot: each weapon candidate creates an independent sub-problem. Workers do not share mutable state -- each gets a serialised copy of the candidate pool and creates its own formula instance.

---

## Testing Guide

### Running Tests

```bash
# Run all tests
uv run pytest tests/ -v

# Run a specific test file
uv run pytest tests/unit/test_formula.py -v

# Run a specific test by name
uv run pytest tests/unit/test_formula.py -k "test_effective_mf" -v

# Run with coverage
uv run pytest tests/ --cov=d2r_optimiser --cov-report=term-missing

# Run only unit tests
uv run pytest tests/unit/ -v

# Run only integration tests
uv run pytest tests/integration/ -v
```

### Linting

```bash
# Check for lint issues
uv run ruff check src/ tests/

# Auto-fix where possible
uv run ruff check --fix src/ tests/

# Format code
uv run ruff format src/ tests/
```

### Test Structure

```
tests/
|-- conftest.py                    # Shared fixtures (in-memory DB, sample items, builds)
|-- unit/                          # Fast, isolated tests (no real DB, no I/O)
|   |-- test_models.py             # Model instantiation, Pydantic validation, round-trips
|   |-- test_loaders.py            # Loader functions with fixture YAML data
|   |-- test_resolver.py           # Runeword and socket enumeration logic
|   |-- test_formula.py            # MF curve, breakpoint lookup, formula scoring
|   |-- test_search.py             # Search engine, pruning, resource conflicts
|   |-- test_validation.py         # Deviation computation, record persistence
|   |-- test_orchestrator.py       # Orchestrator with mocked or in-memory DB
|   +-- test_cli.py                # Click CliRunner tests for all commands
|-- integration/
|   +-- test_end_to_end.py         # Full pipeline from import to optimisation
+-- fixtures/
    +-- maxroll_echoing_strike.py   # Reference loadout data for validation tests
```

### Writing New Tests -- Patterns to Follow

**Unit test for a formula method:**

```python
def test_effective_mf_at_300():
    result = effective_mf(300)
    assert abs(result["unique"] - 136.36) < 0.5
    assert abs(result["set"] - 187.5) < 0.5
    assert abs(result["rare"] - 200.0) < 0.5
```

**Unit test with a fixture build:**

```python
@pytest.fixture
def sample_build():
    return BuildDefinition(
        name="test_build",
        display_name="Test Build",
        character_class="warlock",
        description="Test",
        formula_module="warlock_echoing_strike",
        skill_points={"echoing_strike": 20},
        objectives=ObjectiveWeights(
            damage=0.35, magic_find=0.40,
            effective_hp=0.15, breakpoint_score=0.10,
        ),
        constraints=[
            Constraint(stat="fcr", operator=">=", value=75),
        ],
        presets={},
    )
```

**CLI test with CliRunner:**

```python
from click.testing import CliRunner
from d2r_optimiser.cli import cli

def test_inv_list_empty_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    runner = CliRunner()
    result = runner.invoke(cli, ["--db", db_path, "inv", "list"])
    assert result.exit_code == 0
    assert "No items" in result.output
```

**In-memory DB fixture for tests:**

```python
@pytest.fixture
def session(tmp_path):
    from d2r_optimiser.core.db import create_all_tables, get_engine, reset_engine
    reset_engine()
    db_path = tmp_path / "test.db"
    engine = get_engine(url=f"sqlite:///{db_path}")
    create_all_tables(engine=engine)
    with Session(engine) as session:
        yield session
```

### Reference Loadout Fixture

The file `tests/fixtures/maxroll_echoing_strike.py` contains a known-good Maxroll loadout as Python data: every gear slot with exact item name, affixes, and socket fillings, plus expected aggregate stats. This fixture serves as the ground truth for formula calibration tests.

Formula tests use this fixture to verify that `formula.score()` produces stats within 5% of the Maxroll reference values.

---

## Data File Formats

### `data/runewords.yaml`

```yaml
# Top-level key: runewords (list)
runewords:
  - name: Spirit                       # Unique runeword name
    rune_sequence: Tal-Thul-Ort-Amn    # Ordered rune list, hyphen-separated
    base_types:                         # Valid base item categories (JSON-compatible list)
      - sword
      - shield
    socket_count: 4                     # Must match number of runes in sequence
    stats:                              # Bonus stats granted by the completed runeword
      all_skills: 2
      fcr: 35
      fhr: 55
      vitality: 22
      mana: 89
      resistance_all: 30               # Average roll for reference

  - name: Enigma
    rune_sequence: Jah-Ith-Ber
    base_types:
      - body
    socket_count: 3
    stats:
      all_skills: 2
      frw: 45
      strength: 15                     # 0.75 per character level approximation
      mf: 99                           # 1 per character level at level 99
      dr: 8
```

The loader parses each entry into a `RunewordRecipe` SQLModel instance. The `stats` dict is serialised to `stats_json` for database storage.

### `data/breakpoints.yaml`

```yaml
# Top-level keys: class names
warlock:
  fcr:                                 # Faster Cast Rate breakpoints
    - { threshold: 0, frames: 15 }     # Base cast speed (0% FCR)
    - { threshold: 9, frames: 14 }
    - { threshold: 20, frames: 13 }
    - { threshold: 37, frames: 12 }
    - { threshold: 48, frames: 11 }
    - { threshold: 75, frames: 10 }
    - { threshold: 105, frames: 9 }
    - { threshold: 200, frames: 8 }
  fhr:                                 # Faster Hit Recovery breakpoints
    - { threshold: 0, frames: 15 }
    - { threshold: 5, frames: 14 }
    - { threshold: 9, frames: 13 }
    - { threshold: 14, frames: 12 }
    - { threshold: 20, frames: 11 }
    - { threshold: 30, frames: 10 }
    - { threshold: 42, frames: 9 }
    - { threshold: 60, frames: 8 }
    - { threshold: 86, frames: 7 }
    - { threshold: 142, frames: 6 }
    - { threshold: 280, frames: 5 }

# Additional classes follow the same structure
amazon:
  fcr:
    - { threshold: 0, frames: 19 }
    # ...
```

The `lookup_breakpoint()` function in `common.py` takes a list of `{threshold, frames}` dicts and returns the entry for the highest threshold met.

### `data/builds/*.yaml`

Full schema reference:

```yaml
# Required fields
name: string                         # Internal name (matches filename without .yaml)
display_name: string                 # Human-readable name shown in CLI output
character_class: string              # "warlock" / "amazon" / etc.
description: string                  # Multi-line description of the build
formula_module: string               # Python module name in core/formula/

# Required: skill allocation
skill_points:                        # dict[str, int]
  skill_name: 20                     # Skill name -> points allocated

# Required: default objective weights (must sum to 1.0)
objectives:
  damage: float                      # Weight for damage dimension
  magic_find: float                  # Weight for MF dimension
  effective_hp: float                # Weight for EHP dimension
  breakpoint_score: float            # Weight for breakpoint dimension

# Required: hard constraints
constraints:                         # list of constraint dicts
  - stat: string                     # Stat key (e.g. "fcr", "resistance_all")
    operator: string                 # ">=" / "<=" / "==" / ">" / "<"
    value: float                     # Threshold value

# Required: weight presets
presets:                             # dict[str, ObjectiveWeights]
  preset_name:                       # Preset name used with --mode
    damage: float
    magic_find: float
    effective_hp: float
    breakpoint_score: float

# Optional: reference loadouts for validation
reference_loadouts:                  # list | null
  - name: string                     # Descriptive name
    source: string                   # URL or reference
    notes: string                    # Multi-line notes
    gear:                            # dict[slot, item_name]
      weapon: string
      shield: string
      # ...
    expected_stats:                  # dict[stat, value]
      fcr: int
      magic_find: int
      # ...
```

### `data/uniques.yaml`

```yaml
uniques:
  - name: "Harlequin Crest"
    base: "Shako"
    slot: helmet
    item_level: 69
    affixes:
      all_skills: 2
      life: 98                       # Fixed value (not a range for V1)
      mana: 98
      dr: 10
      mf: 50
```

### `data/sets.yaml`

```yaml
sets:
  - set_name: "Tal Rasha's Wrappings"
    pieces:
      - name: "Tal Rasha's Adjudication"
        base: "Amulet"
        slot: amulet
        affixes:
          light_res: 33
          fire_res: 33
          cold_res: 33
          life: 42
      # ... other set pieces
    partial_bonuses:
      2:                             # Bonus for wearing 2 pieces
        mf: 65
      3:
        fhr: 10
    full_set_bonus:                   # All pieces worn
      mf: 150
      resistance_all: 50
```

### `data/runes.yaml`

```yaml
runes:
  - name: Ist
    level: 24
    weapon_stats:
      mf: 30
    armour_stats:
      mf: 25
    shield_stats:
      mf: 25

  - name: Ber
    level: 30
    weapon_stats:
      cb: 20                         # Crushing Blow 20%
    armour_stats:
      dr: 8                          # Damage Reduction 8%
    shield_stats:
      dr: 8
```

Rune stats vary by item context (weapon vs armour vs shield). The orchestrator resolves the correct stat set based on the item's slot.

---

## Formula Validation Pipeline

### Overview

```
Layer 1: Research Synthesis
    |  Formulae derived from Maxroll + community sources
    v
Layer 2: Maxroll Reference Tests
    |  pytest auto-tests: predicted stats vs known-good loadouts
    v
Layer 3: Live In-Game Validation
    |  `optimise validate` records actual measurements
    v
Layer 4: Deviation Tracking
       Calibration log tracks drift over time
```

### Layer 1: Research Synthesis

The initial formula implementation is derived from published guides (Maxroll, community wikis) and D2R data mining. This forms the starting point for each `BuildFormula` implementation. Key sources are cited in the formula module's docstring.

### Layer 2: Maxroll Reference Tests

Known-good loadouts from Maxroll guides are stored as pytest fixtures in `tests/fixtures/reference_loadouts/`. Automated tests in `tests/unit/test_formula.py` verify that the formula engine produces stats matching these references within a defined tolerance (default 5%).

```python
def test_maxroll_reference_within_tolerance(maxroll_loadout, sample_build):
    formula = get_formula("warlock_echoing_strike")
    predicted = formula.score(maxroll_loadout["stats"], sample_build)
    expected = maxroll_loadout["expected_stats"]

    result = validate_against_reference(
        predicted_stats={"mf": predicted.magic_find * 250},
        expected_stats=expected,
        tolerance_pct=5.0,
    )
    assert result["pass"], f"Deviations: {result['deviations']}"
```

### Layer 3: Live In-Game Validation

Users record actual measurements with `optimise validate record`:

```bash
uv run optimise validate record my_mf_set \
    --build warlock_echoing_strike_mf \
    --predicted-mf 266 --actual-mf 259
```

Records are persisted in the `validationrecord` table with per-stat predicted/actual pairs and the maximum deviation percentage.

### Layer 4: Deviation Tracking

`optimise validate check` retrieves all validation records and displays a colour-coded report:

- **Green (< 5%)**: Formula is well calibrated.
- **Yellow (5-10%)**: Minor inaccuracy, investigate if persistent.
- **Red (>= 10%)**: Significant deviation, formula needs adjustment.

Over time, the accumulated validation records form a calibration log. If a pattern of consistent deviation is detected (e.g. damage always 8% high), the formula constants should be adjusted.

### How to Add a New Reference Loadout

1. Add the loadout data to `tests/fixtures/maxroll_echoing_strike.py` (or create a new fixture file for a different build).
2. Include every gear slot, exact affixes, and expected aggregate stats.
3. Add a test in `tests/unit/test_formula.py` that loads the fixture and runs `validate_against_reference()`.
4. Run `uv run pytest tests/unit/test_formula.py -v` to verify.

---

## Performance

### Search Complexity Analysis

The search is exhaustive: for `N` slots each with `C_i` candidates, the worst-case search space is:

```
C_1 * C_2 * ... * C_N
```

With the canonical 10 slots and typical inventories:

| Inventory Size | Typical Candidates Per Slot | Search Space | Expected Runtime |
|---|---|---|---|
| 20 items | 2-3 per slot | ~60,000 | < 1 second |
| 50 items | 5-6 per slot | ~10 million | 10-60 seconds |
| 100 items | 10-12 per slot | ~1 billion | 1-5 minutes |
| 200 items (max) | 20 per slot | ~10 trillion | Up to 5 minutes with pruning |

Hard-constraint pruning significantly reduces the effective search space. Constraint violations at early slots (e.g. weapon + shield already exceed a `<=` constraint) prune entire subtrees. Resource conflict detection (same rune used twice) also eliminates large branches.

### Multiprocessing Architecture

```
Main Process
    |
    +-- Load build, inventory, resolve candidates
    |
    +-- Shard weapon candidates across workers
    |       |
    |       +-- Worker 1: search(weapon=A, remaining)
    |       +-- Worker 2: search(weapon=B, remaining)
    |       +-- Worker 3: search(weapon=C, remaining)
    |       +-- ...
    |
    +-- Merge results from all workers
    +-- Re-sort for global top-K
    +-- Return
```

Each worker receives:
- One fixed weapon candidate.
- A serialised copy of all remaining-slot candidates.
- The build definition.
- The formula module name (workers create their own formula instances, since Protocol instances are not picklable).

Workers are fully independent -- no shared mutable state. Results are merged and re-sorted by the main process.

The default worker count is `min(cpu_count, weapon_candidate_count)`. With `--workers 1`, the search runs single-threaded in the main process.

### When to Use `--workers`

- **Default (auto)**: Best for most cases. One worker per weapon candidate, up to the CPU core count.
- **`--workers 1`**: Forces single-threaded. Useful for debugging, profiling, or when the inventory is small.
- **`--workers N`**: Override when you want to limit CPU usage (e.g. leave cores free for other tasks) or when you know the optimal count for your machine.

### Memory Considerations

The search uses a min-heap of size `top_k` (default 5) rather than storing all valid loadouts. Memory usage is proportional to the candidate pool size, not the search space size. Each worker process gets a copy of the candidate pool, so peak memory is approximately `workers * candidate_pool_size`.

For a 200-item inventory with socket variants and runeword expansions, the candidate pool typically fits comfortably in memory.
