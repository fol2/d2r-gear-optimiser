# D2R Gear Optimiser -- Implementation Plan

> **Version:** 0.1.0 (V1: Warlock Echoing Strike MF build)
> **Created:** 2026-04-10
> **Status:** Draft

---

## Conventions

- **Complexity:** S = a few hours, M = half-day to full day, L = multi-day
- **File paths** are relative to repository root (`d2r-planner/`)
- Every phase lists its **entry criteria** (what must be done before starting) and **exit criteria** (definition of done for the phase)
- Dependencies between tasks use the notation `P1.2` = Phase 1, Task 2

---

## Phase 1: Domain Models + DB

> Define every data structure the system will touch. No business logic yet -- pure schema.

**Entry criteria:** Project skeleton exists with empty `__init__.py` in all subpackages.
**Exit criteria:** All models importable, DB initialises with empty tables, `pytest` passes a smoke test that creates and round-trips one row per table.

### P1.1 -- Item, Affix, and Socket models `[M]`

- [ ] Create `src/d2r_optimiser/core/models/item.py`
  - `Item` SQLModel table: id, name, item_type (enum: unique / set / runeword / rare / magic / crafted / white), base_type, slot (enum: helm / armour / weapon / shield / gloves / boots / belt / amulet / ring / charm), required_level, required_str, required_dex, is_ethereal, num_sockets, image_url (optional)
  - `Affix` SQLModel table: id, item_id (FK), stat_key (e.g. `enhanced_damage`, `faster_cast_rate`), stat_value (float), stat_display (human string)
  - `Socket` SQLModel table: id, item_id (FK), socket_index (0-based), filled_rune_id (FK nullable), filled_jewel_id (FK nullable)
  - **Note:** The existing implementation uses plain `str` fields for `slot` and `item_type`. This is acceptable for V1 -- `StrEnum` can be introduced as a future refinement if validation strictness is needed.
- **Acceptance:** `Item`, `Affix`, `Socket` can be instantiated, serialised to dict, validated by Pydantic.
- **Dependencies:** None.

### P1.2 -- Rune and Jewel models `[S]`

- [ ] Create `src/d2r_optimiser/core/models/rune.py`
  - `Rune` SQLModel table: id, name, level (rune tier 1-33), weapon_stat, helm_stat, shield_stat, armour_stat
  - `Jewel` SQLModel table: id, name, affixes (JSON list of stat dicts)
  - `RunewordRecipe` SQLModel table: id, name (unique), rune_sequence (str), base_types (JSON str), socket_count, stats_json (JSON str). Stored in DB as static reference data seeded from YAML.
- **Acceptance:** Round-trip serialisation works; `RunewordRecipe` validates rune ordering.
- **Dependencies:** P1.1 (enums).

### P1.3 -- Build and objective models `[M]`

- [ ] Create `src/d2r_optimiser/core/models/build.py`
  - `Build` Pydantic model: name, class_name, skill_tree (dict), objective_weights (`ObjectiveWeights`), constraints (list of `Constraint`), formula_module (str)
  - `ObjectiveWeights`: damage_weight, mf_weight, ehp_weight, breakpoint_weight (all float, sum to 1.0 via validator)
  - `Constraint` Pydantic model: stat_key, operator (>=, <=, ==, in), threshold (float or list)
- **Acceptance:** A sample YAML-like dict deserialises into a valid `Build`.
- **Dependencies:** None.

### P1.4 -- Loadout and score models `[M]`

- [ ] Create `src/d2r_optimiser/core/models/loadout.py`
  - `Loadout` SQLModel table: id, build_name, created_at, total_score, rank
  - `LoadoutSlot` Pydantic BaseModel (not a DB table): slot, item_uid, socket_fillings -- used as an in-memory value object during optimisation
  - `LoadoutItem` SQLModel table: loadout_id (FK, composite PK), item_id (FK), slot (composite PK) -- the DB-persisted link between loadout and items
  - `ScoreBreakdown` Pydantic model: damage, magic_find, effective_hp, breakpoint_score
- **Acceptance:** A `Loadout` with `LoadoutSlot` children persists and reloads from SQLite.
- **Dependencies:** P1.1.

### P1.5 -- Validation models `[S]`

- [ ] Create `src/d2r_optimiser/core/models/validation.py`
  - `ValidationRecord` SQLModel table: id, gear_set_id (str label), build_def, predicted_damage, actual_damage, predicted_mf, actual_mf, predicted_hp, actual_hp, predicted_fcr, actual_fcr, deviation_max, notes, created_at -- explicit columns per stat for direct querying
- **Acceptance:** Deviation percentage computed correctly for positive, zero, and negative values.
- **Dependencies:** P1.4.

### P1.6 -- Models package `__init__` re-exports `[S]`

- [ ] Update `src/d2r_optimiser/core/models/__init__.py`
  - Re-export all public classes so consumers can `from d2r_optimiser.core.models import Item, Rune, Build, ...`
- **Acceptance:** Single import path works for every model.
- **Dependencies:** P1.1 -- P1.5.

### P1.7 -- DB schema and session factory `[M]`

- [ ] Create `src/d2r_optimiser/core/db/schema.py`
  - Import all SQLModel table classes so SQLModel.metadata knows about them
  - `create_all(engine)` helper
- [ ] Create `src/d2r_optimiser/core/db/session.py`
  - `get_engine(db_path: Path | None) -> Engine` -- configurable via `D2R_DB_PATH` env var, default `./stash.db`
  - `get_session() -> Session` context manager
  - `create_all_tables(engine)` -- calls `SQLModel.metadata.create_all()`
  - `reset_engine()` -- for test isolation
- [ ] Update `src/d2r_optimiser/core/db/__init__.py` with re-exports
- **Acceptance:** `create_all_tables()` creates a valid SQLite file with all tables. WAL mode is a V2 optimisation (not required for V1).
- **Dependencies:** P1.1 -- P1.5.

### P1.8 -- Phase 1 tests `[M]`

- [ ] Create `tests/test_models.py`
  - Instantiation and Pydantic validation for every model
  - Round-trip: create -> persist -> reload for every SQLModel table
  - Edge cases: enum validation rejects unknown slots, ObjectiveWeights rejects sum != 1.0
- [ ] Create `tests/test_db.py`
  - `init_db` creates all expected tables
  - Session insert + query smoke test
- **Acceptance:** `pytest tests/test_models.py tests/test_db.py` all green.
- **Dependencies:** P1.1 -- P1.7.

---

## Phase 2: Static Data + Loaders

> Populate YAML reference data and build the loaders that parse it into domain models.

**Entry criteria:** Phase 1 complete (all models importable, DB working).
**Exit criteria:** All static YAML files loadable into domain models. `pytest` covers loader happy paths and malformed-input rejection.

### P2.1 -- Runeword recipes YAML `[L]`

- [ ] Create `data/runewords.yaml`
  - Every D2R runeword (including Ladder and 2.4+ additions): name, rune list (ordered), allowed base types, granted stats
  - Use the stat_key vocabulary from P1.1 Affix
- **Acceptance:** File parses without error; contains at least 80 runewords; spot-check 5 iconic runewords (Enigma, Infinity, Spirit, Grief, Chains of Honour) against official data.
- **Dependencies:** P1.1 (stat_key enum vocabulary).

### P2.2 -- Breakpoints YAML `[M]`

- [ ] Create `data/breakpoints.yaml`
  - Structure: `{ class_name: { fcr: [thresholds], fhr: [thresholds], ias: { weapon_type: [thresholds] } } }`
  - V1 requires at minimum: Warlock (Sorceress) FCR and FHR breakpoints
  - Include all classes for completeness
- **Acceptance:** Warlock FCR breakpoints match known values (0, 9, 20, 37, 63, 105, 200).
- **Dependencies:** None.

### P2.3 -- Warlock Echoing Strike MF build YAML `[M]`

- [ ] Create `data/builds/warlock_echoing_strike_mf.yaml`
  - Fields: name, class_name, skill_tree (skill allocations), objective_weights, constraints (e.g. FCR >= 105, all_res >= 75, str >= enough for gear), formula_module
  - Echoing Strike specifics: skill synergies, Lightning Mastery, MF target
- **Acceptance:** Deserialises into a valid `Build` model. Objective weights sum to 1.0. Constraints are well-defined.
- **Dependencies:** P1.3.

### P2.4 -- Items YAML (base types) `[M]`

- [ ] Create `data/items.yaml`
  - Base item types relevant to V1: monarchs, crystal swords, flails, mage plates, dusk shrouds, etc.
  - Fields: name, base_type, slot, max_sockets, required_str, required_dex, required_level
- **Acceptance:** Every base type referenced in runewords.yaml exists here.
- **Dependencies:** P1.1.

### P2.4b -- Uniques and Sets YAML `[L]`

- [ ] Create `data/uniques.yaml`
  - Unique items relevant to Warlock MF builds: Harlequin Crest, Arachnid Mesh, War Traveler, Chance Guards, Stone of Jordan, Mara's Kaleidoscope, Sandstorm Trek, Andariel's Visage, Arioc's Needle, etc.
  - Fields: name, base, slot, item_level, affixes (list of stat:value pairs)
- [ ] Create `data/sets.yaml`
  - Set items relevant to V1 (Tal Rasha's, etc.): name, set_name, base, slot, affixes, partial_set_bonuses, full_set_bonuses
- **Note:** Player-owned unique/set items with specific rolls are entered via `optimise inv add`. These YAML files provide reference data (perfect/average rolls) for the optimiser to know what stats an item grants, and for Maxroll reference loadout validation.
- **Acceptance:** At minimum 20 unique items and 5 set items relevant to Echoing Strike MF builds.
- **Dependencies:** P1.1.

### P2.5 -- Runeword loader `[M]`

- [ ] Create `src/d2r_optimiser/loader/runewords.py`
  - `load_runewords(path: Path) -> list[RunewordRecipe]`
  - Validates each entry against `RunewordRecipe` schema
  - Raises `LoaderError` with line context on malformed entries
- **Acceptance:** Loads full `runewords.yaml`; rejects a YAML file with a missing rune list.
- **Dependencies:** P1.2, P2.1.

### P2.6 -- Build loader `[S]`

- [ ] Create `src/d2r_optimiser/loader/builds.py`
  - `load_build(path: Path) -> Build`
  - `list_builds(directory: Path) -> list[str]` (returns build names from file names)
- **Acceptance:** Loads V1 build definition; rejects a build with weights summing to 0.8.
- **Dependencies:** P1.3, P2.3.

### P2.7 -- Item data loader `[S]`

- [ ] Create `src/d2r_optimiser/loader/items.py`
  - `load_base_items(path: Path) -> list[Item]`
  - Used for populating the DB with static base-type data (not player inventory)
- **Acceptance:** Loads `items.yaml` into `Item` models.
- **Dependencies:** P1.1, P2.4.

### P2.8 -- Loader package init + error types `[S]`

- [ ] Update `src/d2r_optimiser/loader/__init__.py`
  - Re-export `load_runewords`, `load_build`, `list_builds`, `load_base_items`, `load_breakpoints`
  - Define `LoaderError(Exception)` base class
- **Dependencies:** P2.5 -- P2.7b.

### P2.7b -- Breakpoints loader `[S]`

- [ ] Create `src/d2r_optimiser/loader/breakpoints.py`
  - `load_breakpoints(path: Path) -> dict` -- returns nested dict of class -> stat -> threshold list
  - Used by formula engine to look up FCR/FHR breakpoints
- **Acceptance:** Loads `breakpoints.yaml`, returns Warlock FCR thresholds correctly.
- **Dependencies:** P2.2.

### P2.9 -- Phase 2 tests `[M]`

- [ ] Create `tests/test_loaders.py`
  - Happy-path load for each YAML file
  - Malformed YAML rejection tests (missing fields, bad types, invalid enum values)
  - Cross-reference: all rune names in runewords.yaml exist in a known rune list
- [ ] Create `tests/fixtures/` directory with small sample YAML files for isolated tests
- **Acceptance:** `pytest tests/test_loaders.py` all green.
- **Dependencies:** P2.5 -- P2.8.

---

## Phase 3: Resource Resolver

> Given a player's rune pool and socketed bases, enumerate what can be built.

**Entry criteria:** Phase 2 complete (loaders working, runeword data available).
**Exit criteria:** Resolver correctly enumerates runewords and socket options. Tests cover combinatorics edge cases.

### P3.1 -- Runeword resolver `[L]`

- [ ] Create `src/d2r_optimiser/core/resolver/runewords.py`
  - `enumerate_craftable_runewords(rune_pool: list[Rune], bases: list[Item], recipes: list[RunewordRecipe]) -> list[tuple[RunewordRecipe, Item]]`
  - For each recipe: check rune availability (with counts -- duplicates matter), check base type compatibility, check socket count
  - Return all valid (recipe, base) pairs
  - Account for rune consumption: a rune used in one runeword is unavailable for another (handled at search level, but resolver must report resource requirements)
- **Acceptance:** Given pool [Jah, Ith, Ber] + Mage Plate (3os), returns Enigma. Does not return Enigma if Jah is missing. Does not return if base has 4os.
- **Dependencies:** P1.1, P1.2, P2.1, P2.5.

### P3.2 -- Socket filler resolver `[M]`

- [ ] Create `src/d2r_optimiser/core/resolver/sockets.py`
  - `enumerate_socket_options(item: Item, rune_pool: list[Rune], jewel_pool: list[Jewel]) -> list[list[Rune | Jewel]]`
  - For each empty socket in the item, enumerate which runes or jewels could fill it
  - Generate all valid permutations (order matters for runes in non-runeword items? No -- but we enumerate all combos)
  - Prune: do not exceed available pool counts
- **Acceptance:** Item with 2 empty sockets, pool of [Um, Ist, MF jewel] returns all valid 2-picks. Handles items with 0 empty sockets (returns single empty list).
- **Dependencies:** P1.1, P1.2.

### P3.3 -- Resolver package init `[S]`

- [ ] Update `src/d2r_optimiser/core/resolver/__init__.py`
  - Re-export `enumerate_craftable_runewords`, `enumerate_socket_options`
- **Dependencies:** P3.1, P3.2.

### P3.4 -- Phase 3 tests `[M]`

- [ ] Create `tests/test_resolver.py`
  - Runeword resolver: exact match, missing rune, wrong base type, insufficient sockets, duplicate rune consumption
  - Socket resolver: 0 sockets, 1 socket, multi-socket, pool exhaustion
  - Edge case: empty pools return empty results (no crash)
- **Acceptance:** `pytest tests/test_resolver.py` all green.
- **Dependencies:** P3.1 -- P3.3.

---

## Phase 4: Formula Engine

> Scoring logic: how good is a loadout for a given build?

**Entry criteria:** Phase 1 complete (models available). Phase 2 complete (build definitions loadable).
**Exit criteria:** Echoing Strike formula produces correct scores for known loadouts. Protocol allows future build formulas.

### P4.1 -- BuildFormula protocol `[S]`

- [ ] Create `src/d2r_optimiser/core/formula/base.py`
  - `BuildFormula` Protocol class with methods:
    - `compute_damage(loadout, build) -> float`
    - `compute_mf(loadout, build) -> float`
    - `compute_ehp(loadout, build) -> float`
    - `compute_breakpoint_score(loadout, build) -> float`
    - `compose_score(loadout, build) -> ScoreResult`
  - `get_formula(module_name: str) -> BuildFormula` factory function (imports module dynamically)
- **Acceptance:** Protocol is structural (no inheritance required). Factory resolves `"warlock_echoing_strike"` to the correct module.
- **Dependencies:** P1.3, P1.4.

### P4.2 -- Common formula helpers `[M]`

- [ ] Create `src/d2r_optimiser/core/formula/common.py`
  - `effective_mf(raw_mf: int) -> dict[str, float]` -- applies diminishing returns curve for unique/set/rare
    - Unique: `mf * 250 / (mf + 250)`
    - Set: `mf * 500 / (mf + 500)`
    - Rare: `mf * 600 / (mf + 600)`
  - `lookup_breakpoint(breakpoints: list[int], stat_value: int) -> int` -- returns highest threshold met
  - `total_resistance(loadout) -> dict[str, int]` -- sum fire/cold/lightning/poison res from all gear
  - `meets_stat_requirement(loadout, stat: str, threshold: int) -> bool`
  - `aggregate_stat(loadout, stat_key: str) -> float` -- sum a stat across all equipped items + socketed runes/jewels
- **Acceptance:** `effective_mf(300)` returns approximately 136 for uniques. Breakpoint lookup for FCR=105 with Sorc table returns 105.
- **Dependencies:** P1.1, P1.4, P2.2.

### P4.3 -- Warlock Echoing Strike formula `[L]`

- [ ] Create `src/d2r_optimiser/core/formula/warlock_echoing_strike.py`
  - Implements `BuildFormula` protocol
  - `compute_damage`: Echoing Strike average damage factoring skill level, synergies, +lightning damage, -enemy lightning res, Lightning Mastery
  - `compute_mf`: Applies `effective_mf()` from common, weights unique-find MF highest
  - `compute_ehp`: Base life + vitality scaling + energy shield (if applicable) + resistance factor
  - `compute_breakpoint_score`: FCR breakpoint tier (0-1 normalised), FHR bonus
  - `compose_score`: Weighted sum using `ObjectiveWeights` from build definition, penalise constraint violations
- **Acceptance:** Known Maxroll reference loadout scores within 5% of hand-calculated expected value. Zero-gear loadout scores near zero. Constraint violation (e.g. FCR < 105) produces a visible penalty.
- **Dependencies:** P4.1, P4.2, P1.3.

### P4.4 -- Formula package init `[S]`

- [ ] Update `src/d2r_optimiser/core/formula/__init__.py`
  - Re-export `BuildFormula`, `get_formula`, `effective_mf`, `lookup_breakpoint`
- **Dependencies:** P4.1 -- P4.3.

### P4.5 -- Phase 4 tests `[M]`

- [ ] Create `tests/test_formula.py`
  - `effective_mf` curve correctness for 0, 100, 300, 500, 1000 MF
  - Breakpoint lookup: exact match, between thresholds, zero, above max
  - Echoing Strike formula: known loadout scoring, edge cases (no weapon, all empty slots)
  - Weighted composition: verify weights are applied correctly
- [ ] Create `tests/fixtures/reference_loadout.py` -- Maxroll Echoing Strike standard gear as fixture data
- **Acceptance:** `pytest tests/test_formula.py` all green.
- **Dependencies:** P4.1 -- P4.4.

---

## Phase 5: Search Engine

> Exhaustive search with pruning. The hot loop of the optimiser.

**Entry criteria:** Phase 3 (resolver) and Phase 4 (formula) complete.
**Exit criteria:** Search finds the optimal loadout for a small test inventory. Multiprocessing wrapper scales to multiple cores.

### P5.1 -- Hard constraint pruning `[M]`

- [ ] Create `src/d2r_optimiser/core/search/pruning.py`
  - `check_hard_constraints(partial_loadout, build) -> list[str]`
    - Returns list of violated constraint descriptions (empty = pass)
  - Constraint checks:
    - Stat requirements: str/dex for each equipped item
    - FCR >= build minimum (if partial loadout already cannot reach threshold, prune)
    - All-res >= build minimum
    - Resource conflicts: same rune/jewel assigned to two slots
  - `can_possibly_satisfy(partial_loadout, remaining_candidates, build) -> bool`
    - Optimistic upper-bound check: even if we fill remaining slots with the best possible items, can we meet constraints?
- **Acceptance:** Partial loadout missing 50 FCR with no remaining FCR gear gets pruned. Resource conflict (same Ist rune in two items) detected.
- **Dependencies:** P1.3, P1.4, P4.2.

### P5.2 -- Exhaustive search engine `[L]`

- [ ] Create `src/d2r_optimiser/core/search/engine.py`
  - `search(inventory, build, recipes, top_k=5) -> list[tuple[Loadout, ScoreResult]]`
  - Slot-by-slot enumeration:
    1. Group inventory items by slot
    2. For each slot, enumerate candidates (including runeword options from resolver, socket fill options)
    3. Recursively assign items to slots, prune via `check_hard_constraints` at each step
    4. Score complete loadouts via formula engine
    5. Maintain top-K heap
  - Track resource consumption (runes, jewels) across slots to prevent double-use
  - Progress callback for Rich progress bar integration
- **Acceptance:** Given a 20-item inventory, finds the same top loadout as a brute-force check. Handles inventory with no valid loadouts gracefully (returns empty list).
- **Dependencies:** P3.1, P3.2, P4.3, P5.1.

### P5.3 -- Multiprocessing wrapper `[M]`

- [ ] Create `src/d2r_optimiser/core/search/parallel.py`
  - `parallel_search(inventory, build, recipes, top_k=5, workers=None) -> list[tuple[Loadout, ScoreResult]]`
  - Shard by weapon slot: each worker gets a different weapon candidate, searches remaining slots
  - Merge results from all workers, re-sort, return global top-K
  - Default workers = `os.cpu_count() - 1` (leave one core free)
  - Fallback: if `workers=1` or inventory is small, delegate to single-threaded `search()`
- **Acceptance:** Produces identical results to single-threaded search. Wall-clock time improves on 4+ core machine with large inventory.
- **Dependencies:** P5.2.

### P5.4 -- Search package init `[S]`

- [ ] Update `src/d2r_optimiser/core/search/__init__.py`
  - Re-export `search`, `parallel_search`
- **Dependencies:** P5.1 -- P5.3.

### P5.5 -- Phase 5 tests `[L]`

- [ ] Create `tests/test_search.py`
  - Small inventory (5 items per slot): verify top-1 matches brute force
  - Pruning effectiveness: count nodes visited with and without pruning, assert reduction
  - Resource conflict: ensure no loadout double-uses a rune
  - Empty inventory: returns empty list
  - Single valid loadout: returns exactly that one
- [ ] Create `tests/test_parallel.py`
  - Same-result test: parallel vs single-threaded on identical input
  - Fallback: `workers=1` behaves like single-threaded
- **Acceptance:** `pytest tests/test_search.py tests/test_parallel.py` all green.
- **Dependencies:** P5.1 -- P5.4.

---

## Phase 6: Orchestrator

> Wire loader + resolver + search + formula into a single entry point.

**Entry criteria:** Phases 1--5 complete.
**Exit criteria:** `optimise()` returns ranked loadouts from a populated DB. No CLI yet -- callable from Python.

### P6.1 -- Orchestrator implementation `[M]`

- [ ] Create `src/d2r_optimiser/core/orchestrator.py`
  - `optimise(db_path: Path, build_name: str, top_k: int = 5, workers: int | None = None) -> list[tuple[Loadout, ScoreResult]]`
  - Steps:
    1. Load build definition via `load_build()`
    2. Load runeword recipes via `load_runewords()`
    3. Load breakpoints via YAML
    4. Query inventory from SQLite (all items, runes, jewels)
    5. Resolve craftable runewords
    6. Call `parallel_search()`
    7. Persist top-K loadouts to DB
    8. Return results
  - Raise clear errors: `BuildNotFoundError`, `EmptyInventoryError`
- **Acceptance:** End-to-end call with a pre-populated test DB returns 5 ranked loadouts.
- **Dependencies:** P1.7, P2.5, P2.6, P3.1, P5.3.

### P6.2 -- Orchestrator tests `[M]`

- [ ] Create `tests/test_orchestrator.py`
  - Happy path with fixture DB
  - `BuildNotFoundError` on unknown build name
  - `EmptyInventoryError` on empty DB
  - Loadouts persisted to DB after run
- **Acceptance:** `pytest tests/test_orchestrator.py` all green.
- **Dependencies:** P6.1.

---

## Phase 7: CLI

> Click commands with Rich output tables.

**Entry criteria:** Phase 6 complete (orchestrator callable).
**Exit criteria:** All CLI commands functional. `optimise --help` shows full command tree. Output is human-readable with Rich formatting.

### P7.1 -- CLI entry point and group `[S]`

- [ ] Create `src/d2r_optimiser/cli/main.py`
  - `cli` Click group with `--db` option (default `stash.db`)
  - `--verbose` flag for debug logging
  - Version option from `__version__`
- **Acceptance:** `optimise --help` displays command list. `optimise --version` prints version.
- **Dependencies:** None (skeleton only).

### P7.2 -- `optimise run` command `[M]`

- [ ] Create `src/d2r_optimiser/cli/run.py`
  - `run` command: `optimise run <build_name> [--mode mf|dps|balanced|survivability] [--top-k 5] [--workers N] [--weight damage=0.5 --weight mf=0.3]`
  - `--mode` selects a preset from `build.presets` dict (overrides default `build.objectives`)
  - `--weight` allows fine-grained override of individual objective weights
  - Rich progress bar during search
  - Rich table output: rank, items per slot, total score, score breakdown
  - Option to output JSON (`--json`)
- **Acceptance:** `optimise run warlock_echoing_strike_mf` prints a formatted table of top 5 loadouts.
- **Dependencies:** P6.1, P7.1.

### P7.3 -- `optimise inv` commands `[L]`

- [ ] Create `src/d2r_optimiser/cli/inv.py`
  - `optimise inv list [--slot helm] [--type unique]` -- filtered inventory view
  - `optimise inv add` -- interactive prompts (name, type, slot, stats) or `--from-yaml <file>`
  - `optimise inv edit <item_id>` -- modify existing item
  - `optimise inv remove <item_id>` -- soft delete with confirmation
  - `optimise inv import <file>` -- bulk import from YAML/JSON
  - `optimise inv export [--format yaml|json]` -- dump entire inventory
  - All output via Rich tables
- **Acceptance:** Full CRUD cycle: add an item, list it, edit it, export, re-import.
- **Dependencies:** P1.7, P7.1.

### P7.4 -- `optimise build` commands `[S]`

- [ ] Create `src/d2r_optimiser/cli/build.py`
  - `optimise build list` -- lists available build definitions from `data/builds/`
  - `optimise build show <name>` -- prints build details (objectives, constraints, skills)
- **Acceptance:** Lists the V1 build. `show` prints a readable summary.
- **Dependencies:** P2.6, P7.1.

### P7.5 -- `optimise validate` command `[S]`

- [ ] Create `src/d2r_optimiser/cli/validate.py`
  - `optimise validate <loadout_id>` -- runs validation checks, prints deviation report
  - `optimise validate record <loadout_id>` -- prompts user to enter actual in-game stats
  - Rich-formatted deviation table with colour coding (green < 5%, yellow < 10%, red >= 10%)
- **Acceptance:** Validation report renders correctly with sample data.
- **Dependencies:** P8.1 (validator module), P7.1.

### P7.6 -- CLI package init `[S]`

- [ ] Update `src/d2r_optimiser/cli/__init__.py`
  - Import and register all command groups
- **Dependencies:** P7.1 -- P7.5.

### P7.7 -- Phase 7 tests `[M]`

- [ ] Create `tests/test_cli.py`
  - Use Click `CliRunner` for all commands
  - `--help` for every command
  - `run` with a fixture DB
  - `inv list` / `inv add` / `inv export` round-trip
  - `build list` / `build show`
  - Error cases: missing DB, unknown build
- **Acceptance:** `pytest tests/test_cli.py` all green.
- **Dependencies:** P7.1 -- P7.6.

---

## Phase 8: Validation

> Compare optimiser output against known-good reference data (Maxroll guide).

**Entry criteria:** Phase 4 (formula) and Phase 6 (orchestrator) complete.
**Exit criteria:** Validation module detects deviations. Maxroll reference loadout passes within tolerance.

### P8.1 -- Validator module `[M]`

- [ ] Create `src/d2r_optimiser/core/validation/validator.py`
  - `validate_against_reference(loadout, expected_stats: dict[str, float], tolerance_pct: float = 5.0) -> DeviationReport`
    - Compares computed stats against expected, flags deviations above tolerance
  - `record_live_measurement(loadout_id, actual_stats: ActualStats, session) -> ValidationRecord`
    - Persists a manual measurement to DB
  - `check_all_validations(loadout_id, session) -> list[DeviationReport]`
    - Retrieves all historical validations for a loadout
- **Acceptance:** Reference loadout with exact stats returns 0% deviation. Loadout missing 10 FCR returns correct deviation percentage.
- **Dependencies:** P1.4, P1.5, P4.2.

### P8.2 -- Validation package init `[S]`

- [ ] Update `src/d2r_optimiser/core/validation/__init__.py`
  - Re-export `validate_against_reference`, `record_live_measurement`, `check_all_validations`
- **Dependencies:** P8.1.

### P8.3 -- Maxroll reference fixture `[M]`

- [ ] Create `tests/fixtures/maxroll_echoing_strike.py`
  - Complete Maxroll Echoing Strike MF build as Python data:
    - Every gear slot with exact item, affixes, and sockets
    - Expected aggregate stats: total MF, FCR, FHR, resistances, damage, life
  - This fixture serves as the ground-truth for formula calibration
- **Acceptance:** Data matches the published Maxroll guide (manual verification).
- **Dependencies:** P1.1, P1.2.

### P8.4 -- Validation tests `[M]`

- [ ] Create `tests/test_validation.py`
  - Reference loadout: validate_against_reference returns all-pass
  - Modified loadout (swap one item): detects stat changes
  - Tolerance edge cases: exactly at threshold, just above, just below
  - Live measurement record + retrieval round-trip
- **Acceptance:** `pytest tests/test_validation.py` all green.
- **Dependencies:** P8.1 -- P8.3.

---

## Phase 9: Integration Tests + Polish

> End-to-end flows, code quality, documentation.

**Entry criteria:** Phases 1--8 complete.
**Exit criteria:** Full pipeline tested. Ruff clean. Coverage >= 80%.

### P9.1 -- End-to-end integration test `[L]`

- [ ] Create `tests/test_integration.py`
  - Scenario: start from empty DB, import a sample inventory (10-15 items + runes + jewels), run optimise for Echoing Strike MF, verify:
    - Returns 5 results
    - Top result is plausible (scores above a minimum threshold)
    - No resource conflicts in any returned loadout
    - All hard constraints satisfied
    - Loadouts persisted to DB
  - Scenario: re-run with same DB returns same results (deterministic)
- **Acceptance:** `pytest tests/test_integration.py` all green.
- **Dependencies:** P6.1, all prior phases.

### P9.2 -- Ruff lint + format pass `[S]`

- [ ] Run `ruff check --fix src/ tests/` and `ruff format src/ tests/`
  - Fix all lint issues
  - Ensure `ruff check` returns zero errors
- **Acceptance:** `ruff check src/ tests/` exits 0.
- **Dependencies:** All code written.

### P9.3 -- Test coverage check `[S]`

- [ ] Run `pytest --cov=d2r_optimiser --cov-report=term-missing`
  - Identify uncovered paths
  - Add targeted tests to reach >= 80% line coverage
- **Acceptance:** Coverage report shows >= 80%.
- **Dependencies:** P9.1.

### P9.4 -- Type checking pass `[S]`

- [ ] Run `ruff check --select ANN src/` (or consider adding `mypy` to dev deps)
  - Add missing type annotations where flagged
  - Ensure all public function signatures are fully typed
- **Acceptance:** No type annotation warnings on public API.
- **Dependencies:** All code written.

### P9.5 -- README update `[S]`

- [ ] Update `README.md` with:
  - Project description
  - Installation (`uv sync`)
  - Quick-start usage (`optimise run warlock_echoing_strike_mf`)
  - CLI command reference summary
  - Architecture overview (one paragraph + layer diagram in ASCII)
- **Acceptance:** README covers install, usage, and architecture.
- **Dependencies:** P7.1 (CLI finalised).

---

## Phase 10: Review + Ship

> Final quality gate, push, and release.

**Entry criteria:** Phase 9 complete. All tests pass. Lint clean. Coverage >= 80%.
**Exit criteria:** Code on `main` at GitHub. Tagged v0.1.0 release.

### P10.1 -- Self-review checklist `[S]`

- [ ] Walk through every module:
  - No hardcoded paths (all configurable or relative to project root)
  - No secrets or personal data committed
  - All `__init__.py` files have clean re-exports
  - No unused imports or dead code
  - Error messages are helpful (include context, not just "failed")
- **Acceptance:** Checklist completed, all issues resolved.
- **Dependencies:** P9.2.

### P10.2 -- Git housekeeping `[S]`

- [ ] Ensure `.gitignore` covers all generated artefacts
- [ ] Squash any WIP commits if desired
- [ ] Verify commit messages are descriptive
- [ ] Confirm `uv.lock` is NOT committed (already in `.gitignore`)
- **Acceptance:** `git log --oneline` shows clean history.
- **Dependencies:** P10.1.

### P10.3 -- Push to GitHub `[S]`

- [ ] `git push origin main`
- [ ] Verify CI runs (if configured) or manually confirm `pytest` + `ruff` pass in clean checkout
- **Acceptance:** Code visible at `github.com/fol2/d2r-gear-optimiser`. All tests pass on fresh clone.
- **Dependencies:** P10.2.

### P10.4 -- GitHub release v0.1.0 `[S]`

- [ ] Tag `v0.1.0`
- [ ] Create GitHub release with changelog:
  - V1 scope: Warlock Echoing Strike MF build optimisation
  - Features: exhaustive search, runeword resolution, socket optimisation, CLI, validation
- **Acceptance:** Release visible on GitHub. Tag matches `pyproject.toml` version.
- **Dependencies:** P10.3.

---

## Dependency Graph (Abridged)

```
P1 (Models + DB)
 |
 +---> P2 (Data + Loaders) ---> P3 (Resolver) ---+
 |                                                 |
 +---> P4 (Formula) ------------------------------+---> P5 (Search)
                                                   |
                                                   +---> P6 (Orchestrator)
                                                          |
                                           +--------------+---------------+
                                           |                              |
                                      P7 (CLI)                     P8 (Validation)
                                           |                              |
                                           +--------- P9 (Integration) --+
                                                           |
                                                      P10 (Ship)
```

---

## Estimated Total Effort

| Phase | Tasks | Estimated Effort |
|-------|-------|-----------------|
| P1: Domain Models + DB | 8 | ~3 days |
| P2: Static Data + Loaders | 9 | ~3 days |
| P3: Resource Resolver | 4 | ~2 days |
| P4: Formula Engine | 5 | ~3 days |
| P5: Search Engine | 5 | ~3 days |
| P6: Orchestrator | 2 | ~1 day |
| P7: CLI | 7 | ~3 days |
| P8: Validation | 4 | ~2 days |
| P9: Integration + Polish | 5 | ~2 days |
| P10: Review + Ship | 4 | ~1 day |
| **Total** | **53 tasks** | **~23 days** |
