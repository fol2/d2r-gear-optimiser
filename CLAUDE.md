# D2R Gear Optimiser

## Project Overview

Python CLI tool that optimises Diablo 2 Resurrected gear loadouts. Takes a player's inventory (SQLite) and returns the Top 5 gear combinations for a target build using exhaustive search with hard-constraint pruning.

## Architecture

Layered: `CLI (Click + Rich) → Orchestrator → Core (models/resolver/search/formula/validation) → Data (SQLite + YAML)`

- **Core layer** has NO I/O side effects — pure functions only
- **CLI and future API** are sibling consumers of core
- **Formula engine** uses Protocol pattern — one implementation per build
- **Build definitions** are data-driven YAML files

## Conventions

- **Language:** Python 3.13, UK English in code/docs
- **Package manager:** uv
- **Models:** SQLModel (Pydantic v2 + SQLAlchemy) for DB models, plain Pydantic BaseModel for value objects
- **CLI:** Click groups + Rich tables/panels for output
- **Testing:** pytest, tests in `tests/unit/` and `tests/integration/`
- **Linting:** ruff
- **Style:** Type hints everywhere. No unnecessary abstractions. YAGNI.

## Key Directories

- `src/d2r_optimiser/core/` — Pure logic (models, resolver, search, formula, validation)
- `src/d2r_optimiser/cli/` — Click commands
- `src/d2r_optimiser/loader/` — YAML data file loaders
- `data/` — Static YAML (items, runewords, breakpoints, builds)
- `docs/specs/` — Design specification
- `docs/plans/` — Implementation plans

## Database

- SQLite via SQLModel, default path `./stash.db`
- Configurable via `D2R_DB_PATH` environment variable
- `stash.db` is in `.gitignore` — never commit

## Adding a New Build

1. Create `data/builds/<build_name>.yaml` with skill tree, objectives, constraints
2. Create `src/d2r_optimiser/core/formula/<build_name>.py` implementing `BuildFormula` Protocol
3. Add tests in `tests/unit/test_formula_<build_name>.py`
4. No core changes needed

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
