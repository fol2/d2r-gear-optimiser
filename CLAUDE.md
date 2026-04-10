# D2R Gear Optimiser

## Project Overview

Python CLI tool that optimises Diablo 2 Resurrected gear loadouts. Takes a player's inventory (SQLite) and returns the Top 5 gear combinations for a target build using exhaustive search with hard-constraint pruning. V1 reference: Warlock Echoing Strike MF build.

**Repo:** https://github.com/fol2/d2r-gear-optimiser
**Version:** v0.1.0
**Tests:** 244 passing, ruff clean

## Architecture

Layered: `CLI (Click + Rich) → Orchestrator → Core (models/resolver/search/formula/validation) → Data (SQLite + YAML)`

- **Core layer** has NO I/O side effects — pure functions only
- **CLI and future API** are sibling consumers of core
- **Formula engine** uses Protocol pattern (structural typing) — one implementation per build
- **Build definitions** are data-driven YAML files
- **Search** is exhaustive (no score-based pruning) — user wants unexpected combinations
- **Orchestrator** (`core/orchestrator.py`) wires everything: load build → query inventory → resolve candidates → search → return

## Key Patterns

### Import Direction (never reverse)
```
CLI → Orchestrator → Core (resolver/search/formula/validation) → Models
                                                                  ↑
Loaders ─────────────────────────────────────────────────────────┘
```

### Formula Protocol (structural typing)
```python
@runtime_checkable
class BuildFormula(Protocol):
    def compute_damage(self, stats, build) -> float: ...
    def compute_mf(self, stats, build) -> float: ...
    def compute_ehp(self, stats, build) -> float: ...
    def compute_breakpoint_score(self, stats, build) -> float: ...
    def score(self, stats, build) -> ScoreBreakdown: ...
```
New builds implement this protocol. `get_formula("module_name")` dynamically imports and instantiates.

### Candidate Dict Format (search engine interface)
```python
{"item_uid": str, "stats": {stat: value}, "resource_cost": Counter}
```
The orchestrator converts DB items → this format. The search engine consumes it.

### Stat Naming Convention
Use these keys consistently across all YAML, models, and formulas:
`mf`, `fcr`, `fhr`, `frw`, `ed`, `all_skills`, `life`, `mana`, `strength`, `dexterity`, `vitality`, `energy`, `resist_fire`, `resist_cold`, `resist_lightning`, `resist_poison`, `resist_all`, `ias`, `cb`, `ds`, `ll`, `ml`, `dr`, `mdr`, `damage_min`, `damage_max`

## Conventions

- **Language:** Python 3.13, UK English in code and docs
- **Package manager:** uv
- **Models:** SQLModel (table=True) for DB, plain Pydantic BaseModel for value objects
- **CLI:** Click groups + Rich tables/panels for output
- **Testing:** pytest in `tests/unit/` and `tests/integration/`
- **Linting:** ruff (line-length 100)
- **Style:** Type hints everywhere. YAGNI. No unnecessary abstractions.
- **Timestamps:** Use `utcnow()` from `core/models/_common.py` (single source)
- **Errors:** LoaderError for YAML issues, FileNotFoundError for missing files, ValidationError for schema issues. Never swallow exceptions silently.

## Key Directories

```
src/d2r_optimiser/
├── core/
│   ├── models/     # Domain models (Item, Affix, Socket, Rune, Jewel, etc.)
│   ├── db/         # SQLite engine, session, schema registration
│   ├── resolver/   # Expand inventory → candidate pool (runewords, sockets)
│   ├── search/     # Exhaustive search + multiprocessing
│   ├── formula/    # BuildFormula Protocol + per-build scoring
│   ├── validation/ # Maxroll reference + live calibration
│   └── orchestrator.py  # Top-level optimise() entry point
├── cli/            # Click commands (run, inv, build, validate)
└── loader/         # YAML data file loaders
data/               # Static YAML (runewords, runes, items, builds, breakpoints)
tests/              # unit/ + integration/ + fixtures/
docs/               # specs/, plans/, guides
```

## Database

- SQLite via SQLModel, default path `./stash.db`
- Configurable via `D2R_DB_PATH` environment variable
- `stash.db` is in `.gitignore` — never commit
- DB auto-initialises on first CLI access via `ensure_db()`

## Adding a New Build

1. Create `data/builds/<build_name>.yaml` — skill tree, objectives, constraints, presets
2. Create `src/d2r_optimiser/core/formula/<build_name>.py` — implement `BuildFormula` Protocol
3. Add tests in `tests/unit/test_formula_<build_name>.py`
4. No core changes needed — `get_formula()` auto-discovers by module name

## Common Pitfalls

- **Git lock files:** Parallel agents committing simultaneously causes `index.lock` conflicts. Always commit centrally from the coordinator, not from subagents.
- **Ring slots:** `ring1` and `ring2` are separate slots in the search engine but both map to `ring` in inventory. The orchestrator handles the duplication.
- **Resource tracking:** Runes are fungible (tracked by type + quantity). Jewels are individual (tracked by uid). The search engine uses `Counter` to detect double-use.
- **Multiprocessing + Protocol:** `BuildFormula` instances can't be pickled across processes. `parallel_search()` takes a module name string and each worker creates its own instance via `get_formula()`.
- **ObjectiveWeights:** Must sum to 1.0 (±0.01). Pydantic model_validator enforces this.

## Scoring System

4 dimensions scored per loadout:
1. **damage** — weapon base × ED × skill multiplier × FCR speed factor
2. **magic_find** — effective_mf(raw) / 250 (diminishing returns curve)
3. **effective_hp** — life × DR factor × resistance factor
4. **breakpoint_score** — FCR (70%) + FHR (20%) + resistance cap (10%)

Presets: `mf` (MF-heavy), `dps` (damage-heavy), `balanced`, `survivability`

## Validation Pipeline

1. **Research synthesis** — Formula coefficients from Maxroll/community (V1 approximations)
2. **Maxroll reference tests** — Standard endgame loadout as pytest fixture
3. **Live in-game validation** — `optimise validate record` captures actual stats
4. **Deviation tracking** — `optimise validate check` with colour-coded reports

## Running Tests

```bash
uv run pytest tests/ -v          # all tests
uv run pytest tests/unit/ -v     # unit only
uv run ruff check src/ tests/    # lint
```

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialised workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
