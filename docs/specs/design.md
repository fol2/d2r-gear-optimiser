# D2R Gear Optimiser -- Design Specification

**Version:** 1.0
**Date:** 2026-04-10
**Status:** Locked

---

## 1. Overview

A Python CLI tool that takes a player's inventory (stored in SQLite) and returns the **Top 5 gear loadouts** for a given build target. The v1 reference build is **Warlock Echoing Strike MF variant**.

The system is designed as an extensible framework: any Warlock build can be added via data-driven YAML definitions, and the architecture permits future expansion to other D2R classes without core rewrites.

---

## 2. Design Decisions

All decisions below are **locked** and form the binding contract for implementation.

| Area | Decision |
|---|---|
| **Scope** | Extensible framework + Echoing Strike MF reference build. Supports any Warlock build via data-driven YAML. Architecturally extensible to other D2R classes. |
| **Tech stack** | Python 3.13 + uv + SQLModel + Pydantic v2 + Click + Rich |
| **Storage** | SQLite (inventory/loadouts/validation) + YAML (build definitions + static game data) + YAML export for hand-review |
| **Input** | Claude Code vision layer (user drops screenshot, Claude reads affixes + updates DB) + CLI manual edit commands |
| **Scoring** | Hybrid: build YAML defines default weights, CLI can override with `--weight` or use presets (`--mode mf/dps/balanced`). Output is Top 5 loadouts with per-dimension breakdown. |
| **Hard constraints** | Str/Dex requirements, FCR breakpoint, resistance cap (75), slot type match, resource conflicts (same rune cannot be used twice) |
| **Algorithm** | Exhaustive search + hard-constraint-only pruning + multiprocessing (v1 CPU, v2 GPU). No score-based pruning -- user wants unexpected combinations discovered. 1s--5min acceptable, max 200 items. |
| **Runes/Jewels/Runewords** | Full resource search. Inventory stores raw runes/jewels. Preprocessing enumerates all possible runewords from rune pool + socket bases. Search tracks resource consumption to prevent double-use. |
| **Formula validation** | Layer 1: research synthesis (Maxroll/community). Layer 2: Maxroll reference loadouts as pytest auto-tests. Layer 3: live in-game validation via `optimise validate` command. Layer 4: deviation tracking with calibration log. |
| **Performance** | 1s--5min acceptable, max 200 items, CPU multiprocessing v1, GPU vectorised v2 |
| **Version control** | stash.db in .gitignore, YAML export for human review, build YAMLs + data files committed |
| **Deployment** | Local CLI first, FastAPI web API as v2 future. Core logic decoupled -- no I/O in core layer. |

---

## 3. Architecture

### 3.1 Layered Design

```
┌──────────────────────────────────────────────────────┐
│                   CLI Layer                           │
│              (Click + Rich)                           │
├──────────────────────────────────────────────────────┤
│                Core Logic Layer                       │
│  ┌────────────┬───────────┬───────────┬────────────┐ │
│  │  Resource   │  Search   │  Formula  │ Validator  │ │
│  │  Resolver   │  Engine   │  Engine   │            │ │
│  └────────────┴───────────┴───────────┴────────────┘ │
│                 Orchestrator                          │
├──────────────────────────────────────────────────────┤
│                 Data Layer                            │
│          (SQLite + YAML + Loader)                     │
└──────────────────────────────────────────────────────┘
```

The core logic layer contains **no I/O**. All database access and file reads are handled by the data layer and passed in. This decoupling allows future deployment as a FastAPI web API (v2) without modifying core logic.

### 3.2 Core Components

#### 3.2.1 Domain Models (`core/models/`)

Pydantic v2 and SQLModel definitions for all domain entities:

- **Item** -- base item with slot, type, name, base, item level, ethereal flag, socket count, location
- **Affix** -- stat modifier attached to an item (explicit or implicit)
- **Socket** -- individual socket on an item, tracks what fills it
- **Rune** -- rune type and quantity in inventory
- **Jewel** -- jewel with affixes (via JSON or child table)
- **Runeword** -- static recipe: name, rune sequence, base types, bonus stats
- **Build** -- build definition loaded from YAML
- **Loadout** -- a complete gear set across all slots
- **ScoreResult** -- per-dimension breakdown (damage, MF, EHP, breakpoint score)
- **ValidationRecord** -- predicted vs actual stats with deviation

#### 3.2.2 Resource Resolver (`core/resolver/`)

Expands raw inventory into the full candidate pool before search begins.

- **runewords.py** -- enumerates all craftable runewords from the current rune pool + available socket bases. Each candidate is tagged with its resource cost (which runes it consumes).
- **sockets.py** -- enumerates socket filling combinations (runes/jewels into socketed items). Each combination is tagged with resource cost.

The resolver output is a list of candidate items (real items + virtual runeword items + socket-filled variants), each annotated with the resources it would consume.

#### 3.2.3 Search Engine (`core/search/`)

- **engine.py** -- exhaustive combinatorial search across all gear slots. Generates every valid loadout combination from the candidate pool.
- **pruning.py** -- hard-constraint-only pruning. Rejects combinations that violate: Str/Dex requirements, FCR breakpoint misses, resistance cap failures, slot type mismatches, resource conflicts (same rune/jewel used twice). **No score-based pruning** -- the user explicitly wants unexpected combinations surfaced.
- **parallel.py** -- multiprocessing support. Search is sharded by weapon slot: each weapon choice spawns an independent sub-search across remaining slots, distributed across CPU cores.

#### 3.2.4 Formula Engine (`core/formula/`)

Protocol-based design allowing per-build formula implementations.

- **base.py** -- defines the `BuildFormula` protocol:
  - `compute_damage(loadout) -> float`
  - `compute_mf(loadout) -> float`
  - `compute_ehp(loadout) -> float`
  - `compute_breakpoint_score(loadout) -> float`
  - `compose_score(damage, mf, ehp, breakpoint, weights) -> float`
- **common.py** -- shared formula utilities (diminishing returns curves, resistance multiplier calculations, breakpoint lookup)
- **warlock_echoing_strike.py** -- reference implementation of `BuildFormula` for the Echoing Strike MF build

Adding a new Warlock build requires creating one new formula module implementing the `BuildFormula` protocol plus one YAML build definition. No core changes needed.

#### 3.2.5 Validator (`core/validation/`)

Four-layer validation pipeline:

| Layer | Method | Purpose |
|---|---|---|
| 1 | Research synthesis | Formulae derived from Maxroll + community sources |
| 2 | Maxroll reference tests | pytest auto-tests comparing predicted stats against known-good Maxroll loadouts |
| 3 | Live calibration | `optimise validate` command records actual in-game measurements |
| 4 | Deviation tracking | Calibration log tracks predicted-vs-actual over time, flags drift |

- **validator.py** -- orchestrates all four layers. Compares predicted stats from the formula engine against reference data and live measurements. Produces deviation reports.

#### 3.2.6 Orchestrator (`core/orchestrator.py`)

Top-level `optimise()` entry point that wires the pipeline together:

1. Load build definition from YAML
2. Load inventory from SQLite
3. Run resource resolver to expand candidate pool
4. Execute search engine with hard-constraint pruning
5. Score all valid loadouts via formula engine
6. Rank and return Top 5 with per-dimension breakdown

#### 3.2.7 Database (`core/db/`)

- **schema.py** -- SQLModel table definitions
- **session.py** -- session factory and connection management
- **migrations/** -- schema migration scripts

---

## 4. SQLite Schema

### 4.1 Entity-Relationship Diagram

```
┌──────────┐       ┌──────────┐
│  items   │──1:N──│ affixes  │
│          │──1:N──│ sockets  │
└────┬─────┘       └──────────┘
     │
     │ (FK via loadout_items)
     │
┌────┴──────────┐
│ loadout_items │
└────┬──────────┘
     │
┌────┴─────┐     ┌─────────────────────┐
│ loadouts │     │ validation_records  │
└──────────┘     └─────────────────────┘

┌──────────┐     ┌──────────┐     ┌───────────┐
│  runes   │     │  jewels  │     │ runewords │
└──────────┘     └──────────┘     └───────────┘
```

### 4.2 Table Definitions

#### `items`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER | PK, autoincrement |
| uid | TEXT | Unique identifier for the physical item |
| slot | TEXT | Equipment slot (helm, armor, weapon, etc.) |
| item_type | TEXT | Category (unique, set, rare, magic, runeword, etc.) |
| name | TEXT | Display name |
| base | TEXT | Base item type (e.g. "Diadem", "Archon Plate") |
| item_level | INTEGER | Item level |
| ethereal | BOOLEAN | Ethereal flag |
| socket_count | INTEGER | Number of sockets |
| location | TEXT | Where the item is stored (stash tab, equipped, etc.) |
| notes | TEXT | Free-form notes |
| created_at | DATETIME | Record creation timestamp |
| updated_at | DATETIME | Last update timestamp |

#### `affixes`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER | PK, autoincrement |
| item_id | INTEGER | FK to items.id |
| stat | TEXT | Stat identifier (e.g. "enhanced_damage", "magic_find") |
| value | REAL | Numeric value |
| is_implicit | BOOLEAN | Whether this is an implicit (base) affix |

#### `sockets`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER | PK, autoincrement |
| item_id | INTEGER | FK to items.id |
| socket_index | INTEGER | Socket position (0-based) |
| filled_with | TEXT | What fills this socket (rune name, jewel id, or null) |

#### `runes`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER | PK, autoincrement |
| rune_type | TEXT | Rune name (e.g. "Ber", "Jah", "Ist") |
| quantity | INTEGER | Count in inventory |

#### `jewels`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER | PK, autoincrement |

Jewel affixes stored via JSON column or child table (implementation detail deferred to schema module).

#### `runewords`

Static reference/recipe table, committed to version control.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER | PK, autoincrement |
| name | TEXT | Runeword name (e.g. "Enigma", "Heart of the Oak") |
| rune_sequence | TEXT | Ordered rune list (e.g. "Jah+Ith+Ber") |
| base_types | TEXT | Valid base item types |
| bonus_stats | TEXT/JSON | Stats granted by the completed runeword |

#### `loadouts`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER | PK, autoincrement |
| name | TEXT | Loadout display name |
| build_def | TEXT | Build definition reference |
| created_at | DATETIME | When this loadout was generated |
| score | REAL | Composite score |
| damage | REAL | Damage dimension score |
| magic_find | REAL | MF dimension score |
| effective_hp | REAL | EHP dimension score |
| notes | TEXT | Free-form notes |

#### `loadout_items`

| Column | Type | Notes |
|---|---|---|
| loadout_id | INTEGER | FK to loadouts.id, part of composite PK |
| item_id | INTEGER | FK to items.id |
| slot | TEXT | Slot assignment, part of composite PK (with loadout_id) |

#### `validation_records`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER | PK, autoincrement |
| gear_set_id | INTEGER | Reference to the gear set being validated |
| build_def | TEXT | Build definition used for prediction |
| predicted | TEXT/JSON | Predicted stat values |
| actual | TEXT/JSON | Actual in-game measured values |
| deviation | TEXT/JSON | Per-stat deviation (predicted vs actual) |
| notes | TEXT | Free-form notes |
| created_at | DATETIME | When this validation was recorded |

---

## 5. Scoring System

### 5.1 Dimensions

| Dimension | Unit | Formula |
|---|---|---|
| **damage** | DPS | `weapon_base * ED_stacks * (1 + skill_bonus) * FCR_multiplier * crit` |
| **magic_find** | % | Sum of all slot + charm MF, effective MF via diminishing returns curve |
| **effective_hp** | HP | `Life * (1 / (1 - DR%)) * res_multiplier` |
| **breakpoint_score** | 0--1 | 0 = missed breakpoint, 1 = all breakpoints met (FCR + FHR + res cap) |

### 5.2 Weight System

Build YAML files define **default weights** for each dimension. These can be overridden at runtime:

- **`--weight`** flag -- set individual dimension weights from the CLI
- **`--mode` presets** -- predefined weight profiles:
  - `mf` -- prioritises magic find
  - `dps` -- prioritises damage output
  - `balanced` -- equal weighting across dimensions

The composite score is computed by the formula engine's `compose_score()` method using the active weight profile.

### 5.3 Output

Each optimisation run returns the **Top 5 loadouts**, each with:

- Full gear list (item per slot)
- Composite score
- Per-dimension breakdown (damage, MF, EHP, breakpoint score)
- Resource consumption summary (which runes/jewels are used)

---

## 6. Algorithm

### 6.1 Overview

The optimiser uses **exhaustive search with hard-constraint-only pruning**. No score-based pruning is applied -- the user explicitly wants unexpected, non-obvious combinations to surface.

### 6.2 Pipeline

```
Inventory (SQLite)
       │
       ▼
┌──────────────────┐
│ Resource Resolver │  Expand raw runes/jewels/bases into
│                  │  all possible runewords + socket fills
└───────┬──────────┘
        │
        ▼
  Candidate Pool
  (real items + virtual runeword items + socket variants)
        │
        ▼
┌──────────────────┐
│  Search Engine   │  Exhaustive combinatorial search
│                  │  across all gear slots
└───────┬──────────┘
        │  Hard-constraint pruning:
        │  - Str/Dex requirements
        │  - FCR breakpoint
        │  - Resistance cap (75)
        │  - Slot type match
        │  - Resource conflicts
        ▼
  Valid Loadouts
        │
        ▼
┌──────────────────┐
│  Formula Engine  │  Score each loadout on all dimensions
└───────┬──────────┘
        │
        ▼
  Ranked Top 5
  (with per-dimension breakdown)
```

### 6.3 Resource Tracking

The search engine tracks resource consumption across the entire loadout:

- Each candidate item declares its resource cost (e.g. "consumes 1x Ber, 1x Jah" for an Enigma)
- When a candidate is placed in a slot, its resources are subtracted from the available pool
- Subsequent slot assignments can only draw from the remaining pool
- This prevents the same physical rune or jewel from being used in multiple items within a single loadout

### 6.4 Parallelisation

Search is sharded by **weapon slot**: each weapon choice creates an independent sub-problem (fill all remaining slots from the remaining candidate pool). These sub-problems are distributed across CPU cores via Python's `multiprocessing` module.

### 6.5 Performance Bounds

| Parameter | Limit |
|---|---|
| Max inventory size | 200 items |
| Acceptable runtime | 1 second -- 5 minutes |
| v1 parallelism | CPU multiprocessing |
| v2 parallelism | GPU vectorised (future) |

---

## 7. CLI Interface

### 7.1 Command Tree

```
optimise
├── run <build-name>                    # Run optimisation
├── inv
│   ├── list [--slot X]                 # List inventory items
│   ├── add                             # Interactive item add
│   ├── edit <id>                       # Interactive item edit
│   ├── import <yaml>                   # Bulk import from YAML
│   └── export [<yaml>]                 # Dump inventory to YAML
├── validate
│   ├── <build> --actual ...            # Record live measurement
│   └── check                           # Run all validation tests
└── build
    ├── list                            # List available builds
    └── show <name>                     # Show build detail
```

### 7.2 Input Methods

1. **Claude Code vision layer** -- user drops a screenshot, Claude reads affixes and updates the database
2. **CLI manual commands** -- `optimise inv add`, `optimise inv edit`, `optimise inv import`

### 7.3 Output Rendering

Rich library provides:

- Formatted tables for loadout comparison
- Per-dimension score breakdowns
- Colour-coded constraint satisfaction (pass/fail)
- Progress bars during long searches

---

## 8. Build Definitions (YAML)

Build definitions are data-driven YAML files stored in `data/builds/`. Each file defines:

- Build name and description
- Required breakpoints (FCR, FHR)
- Stat requirements
- Default scoring weights per dimension
- Skill and gear slot expectations

Adding a new Warlock build requires:

1. One new YAML file in `data/builds/`
2. One new formula module implementing the `BuildFormula` protocol

No changes to core code, CLI, or search engine.

---

## 9. Runes, Jewels, and Runewords

### 9.1 Inventory Storage

- **Runes** -- stored by type and quantity (e.g. 3x Ist, 1x Ber)
- **Jewels** -- stored individually with their affixes
- **Socket bases** -- items with open sockets are tracked in the items table

### 9.2 Preprocessing (Resource Resolver)

Before search begins, the resolver expands the inventory:

1. Enumerate all **craftable runewords** from available runes + compatible socket bases
2. Enumerate all **socket filling combinations** (runes/jewels into socketed items)
3. Tag each candidate with its **resource cost**

### 9.3 Conflict Prevention

The search engine enforces that no physical resource is consumed more than once per loadout. If a loadout uses a Ber rune in an Enigma runeword, that same Ber cannot also appear in another item's socket.

---

## 10. Formula Validation

### 10.1 Four-Layer Pipeline

```
Layer 1: Research Synthesis
    │  Formulae derived from Maxroll + community sources
    ▼
Layer 2: Maxroll Reference Tests
    │  pytest auto-tests: predicted stats vs known-good loadouts
    ▼
Layer 3: Live In-Game Validation
    │  `optimise validate` records actual measurements
    ▼
Layer 4: Deviation Tracking
       Calibration log tracks drift over time
```

### 10.2 Layer Details

**Layer 1 -- Research Synthesis**
Damage, MF, and EHP formulae are derived from Maxroll guides and community research. These form the initial implementation of each `BuildFormula`.

**Layer 2 -- Maxroll Reference Tests**
Known-good loadouts from Maxroll are stored as pytest fixtures in `tests/fixtures/reference_loadouts/`. Automated tests verify that the formula engine predicts stats matching these references within a defined tolerance.

**Layer 3 -- Live Calibration**
The `optimise validate <build> --actual ...` command allows the user to record actual in-game stats (damage numbers, MF percentage, etc.) for a specific gear set. These are stored in the `validation_records` table.

**Layer 4 -- Deviation Tracking**
The `optimise validate check` command runs all stored validations and reports deviations. A calibration log tracks how predictions drift from reality over time, flagging formulae that need correction.

---

## 11. Package Layout

```
src/d2r_optimiser/
├── core/
│   ├── models/
│   │   ├── item.py
│   │   ├── build.py
│   │   ├── loadout.py
│   │   ├── rune.py
│   │   └── validation.py
│   ├── resolver/
│   │   ├── runewords.py
│   │   └── sockets.py
│   ├── search/
│   │   ├── engine.py
│   │   ├── pruning.py
│   │   └── parallel.py
│   ├── formula/
│   │   ├── base.py
│   │   ├── common.py
│   │   └── warlock_echoing_strike.py
│   ├── validation/
│   │   └── validator.py
│   ├── orchestrator.py
│   └── db/
│       ├── schema.py
│       ├── session.py
│       └── migrations/
├── cli/
│   ├── main.py
│   ├── run.py
│   ├── inv.py
│   ├── validate.py
│   └── build.py
└── loader/
    ├── items.py
    ├── builds.py
    └── runewords.py

data/
├── items.yaml
├── uniques.yaml
├── sets.yaml
├── runewords.yaml
├── breakpoints.yaml
└── builds/
    └── warlock_echoing_strike_mf.yaml

tests/
├── unit/
├── integration/
└── fixtures/
    └── reference_loadouts/
```

---

## 12. Data Files

| File | Contents | Committed |
|---|---|---|
| `data/items.yaml` | Base item definitions | Yes |
| `data/uniques.yaml` | Unique item stat ranges | Yes |
| `data/sets.yaml` | Set item and set bonus definitions | Yes |
| `data/runewords.yaml` | Runeword recipes and stats | Yes |
| `data/breakpoints.yaml` | FCR/FHR/FBR breakpoint tables | Yes |
| `data/builds/*.yaml` | Build definitions with weights | Yes |
| `stash.db` | Player inventory (SQLite) | No (.gitignore) |

---

## 13. Non-Goals for v1

The following are explicitly **out of scope** for v1:

- **Web UI** -- FastAPI is planned for v2; v1 is CLI only
- **GPU acceleration** -- v2 will add GPU-vectorised search; v1 uses CPU multiprocessing
- **Auto-import from D2R save files** -- online players have no local saves; input is via screenshot vision or manual CLI
- **Support for all 8 D2R classes** -- v1 covers Warlock only; the architecture is extensible to other classes
- **Charm grid simulation** -- charms are tracked for MF but grid layout optimisation is not modelled
- **Mercenary optimisation** -- merc gear is tracked in inventory but not included in the optimisation search

---

## 14. Success Criteria

| # | Criterion |
|---|---|
| 1 | Given 50+ items in inventory, `optimise run echoing_strike_mf` returns Top 5 loadouts in <5 minutes |
| 2 | All returned loadouts meet hard constraints (Str/Dex requirements, FCR breakpoint, resistance cap) |
| 3 | Maxroll reference loadout matches predicted stats within +/-5% |
| 4 | Adding a new Warlock build = adding 1 YAML + 1 formula module, no core changes required |

---

## 15. Deployment Strategy

### v1 -- Local CLI

- Installed via `uv` as a Python package
- All data stored locally (SQLite + YAML)
- Single-user, single-machine

### v2 -- FastAPI Web API (Future)

- Core logic layer is already decoupled from I/O
- CLI and API become two thin frontends over the same orchestrator
- Database and YAML access abstracted behind the data layer

---

## Appendix A: Tech Stack Summary

| Component | Technology |
|---|---|
| Language | Python 3.13 |
| Package manager | uv |
| ORM / models | SQLModel + Pydantic v2 |
| Database | SQLite |
| Configuration | YAML |
| CLI framework | Click |
| Terminal rendering | Rich |
| Testing | pytest |
| Parallelism (v1) | multiprocessing |
| Parallelism (v2) | GPU vectorised |
| Web API (v2) | FastAPI |
