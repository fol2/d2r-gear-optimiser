# D2R Gear Optimiser -- User Guide

A comprehensive guide to using the D2R Gear Optimiser CLI to find the best gear loadouts for your Diablo II: Resurrected characters.

---

## Table of Contents

- [Getting Started](#getting-started)
- [Managing Your Inventory](#managing-your-inventory)
- [Using Screenshot Input (Claude Code Workflow)](#using-screenshot-input-claude-code-workflow)
- [Running the Optimiser](#running-the-optimiser)
- [Understanding Scoring](#understanding-scoring)
- [Browsing Builds](#browsing-builds)
- [Formula Validation](#formula-validation)
- [Common Stat Names Reference](#common-stat-names-reference)
- [Frequently Asked Questions](#frequently-asked-questions)

---

## Getting Started

### Prerequisites

- **Python 3.13** or later
- **[uv](https://docs.astral.sh/uv/)** -- the fast Python package manager from Astral

### Installation

```bash
git clone <repo-url>
cd d2r-planner
uv sync
```

`uv sync` installs all dependencies and creates a virtual environment automatically. There is no need to create one manually.

### First Run

Verify the installation:

```bash
uv run optimise --help
```

You will see the top-level help with all available commands:

```
Usage: optimise [OPTIONS] COMMAND [ARGS]...

  D2R Gear Optimiser -- find the best loadout for your build.

Options:
  --db TEXT       Path to SQLite database.  [default: stash.db]
  --verbose       Enable debug logging.
  --version       Show the version and exit.
  --help          Show this message and exit.

Commands:
  build     Browse and inspect build definitions.
  inv       Manage your gear inventory.
  run       Run the gear optimiser for a build.
  validate  Validate formula predictions against live measurements.
```

### Global Options

These options apply to every command:

| Option | Default | Description |
|---|---|---|
| `--db <path>` | `stash.db` | Path to the SQLite database file. Also configurable via the `D2R_DB_PATH` environment variable. |
| `--verbose` | off | Enable debug logging to see internal processing details. |
| `--version` | -- | Print version and exit. |

---

## Managing Your Inventory

All inventory management is done through the `optimise inv` subcommands. Your items, runes, and jewels are stored in a local SQLite database (default: `stash.db`).

### Adding Items

Use `optimise inv add` to add a single item. Every item needs a name, slot, and type. Affixes are added with repeatable `--affix stat=value` flags.

```bash
uv run optimise inv add \
    --name "Harlequin Crest" \
    --slot helmet \
    --type unique \
    --base "Shako" \
    --affix mf=50 \
    --affix all_skills=2 \
    --affix dr=10 \
    --affix life=98 \
    --affix mana=98 \
    --location stash
```

The tool generates a unique ID (UID) automatically based on the item name (e.g. `harlequin_crest_001`).

#### Full Option Reference for `inv add`

| Option | Required | Description |
|---|---|---|
| `--name` | Yes (prompts if omitted) | Display name of the item. |
| `--slot` | Yes (prompts if omitted) | Equipment slot: `helmet`, `body`, `weapon`, `shield`, `gloves`, `belt`, `boots`, `amulet`, `ring`, `charm`. |
| `--type` | Yes (prompts if omitted) | Item type: `unique`, `set`, `runeword`, `rare`, `magic`, `crafted`. |
| `--base` | No | Base item name (e.g. "Shako", "Monarch", "Archon Plate"). |
| `--affix` | No (repeatable) | Stat as `stat=value`, e.g. `--affix mf=50`. Add multiple `--affix` flags. |
| `--sockets` | No (default 0) | Number of sockets on the item. |
| `--socket-fill` | No (repeatable) | Socket fillings in order. Rune name or jewel UID. |
| `--location` | No | Where the item is stored: `stash`, `equipped`, `mule1`, etc. |
| `--ethereal` | No | Flag to mark item as ethereal. |

#### Common Item Examples

**Spirit Monarch (Runeword)**

```bash
uv run optimise inv add \
    --name "Spirit" \
    --slot shield \
    --type runeword \
    --base "Monarch" \
    --sockets 4 \
    --socket-fill Tal --socket-fill Thul --socket-fill Ort --socket-fill Amn \
    --affix all_skills=2 \
    --affix fcr=35 \
    --affix fhr=55 \
    --affix mana=89 \
    --affix vitality=22 \
    --affix resistance_all=30
```

**Enigma (Runeword)**

```bash
uv run optimise inv add \
    --name "Enigma" \
    --slot body \
    --type runeword \
    --base "Mage Plate" \
    --sockets 3 \
    --socket-fill Jah --socket-fill Ith --socket-fill Ber \
    --affix all_skills=2 \
    --affix strength=15 \
    --affix mf=99 \
    --affix frw=45 \
    --affix dr=8
```

**Arachnid Mesh (Unique Belt)**

```bash
uv run optimise inv add \
    --name "Arachnid Mesh" \
    --slot belt \
    --type unique \
    --base "Spiderweb Sash" \
    --affix all_skills=1 \
    --affix fcr=20 \
    --affix slow_target=10
```

**Stone of Jordan (Unique Ring)**

```bash
uv run optimise inv add \
    --name "Stone of Jordan" \
    --slot ring \
    --type unique \
    --affix all_skills=1 \
    --affix mana=20 \
    --affix mana_pct=25
```

> **Note:** Ring-type items (slot `ring`) are automatically considered for both ring1 and ring2 slots during optimisation.

### Adding Runes

Runes are fungible -- tracked by type and quantity, not individually:

```bash
uv run optimise inv add-rune Ist --quantity 3
uv run optimise inv add-rune Ber
uv run optimise inv add-rune Jah --quantity 2
```

If the rune type already exists in your pool, the quantity is added to the existing count:

```
Added 3x Ist rune(s). Total: 3
```

Adding more later:

```bash
uv run optimise inv add-rune Ist --quantity 2
```

```
Added 2x Ist rune(s). Total: 5
```

### Adding Jewels

Jewels are stored individually since each has unique affix rolls:

```bash
uv run optimise inv add-jewel \
    --name "40/15 ED/IAS" \
    --quality magic \
    --affix ed=40 \
    --affix ias=15
```

```bash
uv run optimise inv add-jewel \
    --name "5/5 Lightning Facet" \
    --quality magic \
    --affix light_damage_pct=5 \
    --affix enemy_light_res=-5
```

The `--quality` option accepts `magic`, `rare`, or `crafted`.

### Bulk Import from YAML

For large inventories, write a YAML file and import everything at once:

```bash
uv run optimise inv import my_stash.yaml
```

#### YAML Format

The file must have a top-level `items` list:

```yaml
items:
  - name: "Harlequin Crest"
    slot: helmet
    type: unique
    base: Shako
    location: stash
    affixes:
      mf: 50
      all_skills: 2
      dr: 10
      life: 98
      mana: 98

  - name: "Spirit"
    slot: shield
    type: runeword
    base: Monarch
    sockets: 4
    socket_fill: [Tal, Thul, Ort, Amn]
    affixes:
      all_skills: 2
      fcr: 35
      fhr: 55
      mana: 89
      vitality: 22
      resistance_all: 30

  - name: "Enigma"
    slot: body
    type: runeword
    base: "Mage Plate"
    sockets: 3
    socket_fill: [Jah, Ith, Ber]
    affixes:
      all_skills: 2
      strength: 15
      mf: 99
      frw: 45
      dr: 8

  - name: "War Traveler"
    slot: boots
    type: unique
    base: "Battle Boots"
    affixes:
      mf: 47
      strength: 10
      vitality: 10
      damage_min: 15
      damage_max: 25

  - name: "Chance Guards"
    slot: gloves
    type: unique
    base: "Chain Gloves"
    affixes:
      mf: 40
      ed: 20
      gold_find: 200

  - name: "Mara's Kaleidoscope"
    slot: amulet
    type: unique
    affixes:
      all_skills: 2
      resistance_all: 25

  - name: "Nagelring"
    slot: ring
    type: unique
    affixes:
      mf: 30
      damage_min: 3

  - name: "Stone of Jordan"
    slot: ring
    type: unique
    affixes:
      all_skills: 1
      mana: 20
      mana_pct: 25

  - name: "Arachnid Mesh"
    slot: belt
    type: unique
    base: "Spiderweb Sash"
    affixes:
      all_skills: 1
      fcr: 20
      slow_target: 10

  - name: "Arioc's Needle"
    slot: weapon
    type: unique
    base: "Hyperion Spear"
    sockets: 4
    ethereal: true
    affixes:
      all_skills: 4
      fcr: 50
      damage_demon_pct: 50
      ed: 180
      ignore_target_defense: 1
```

### Listing Inventory

View all items:

```bash
uv run optimise inv list
```

Filter by slot:

```bash
uv run optimise inv list --slot helmet
```

Filter by type:

```bash
uv run optimise inv list --type unique
```

Combine filters:

```bash
uv run optimise inv list --slot ring --type unique
```

The output is a Rich-formatted table showing UID, name, type, slot, base, sockets, key affixes, and location.

### Exporting Inventory

Export your entire inventory back to YAML (for backup, review, or sharing):

```bash
uv run optimise inv export
```

This prints YAML to stdout. Redirect to a file:

```bash
uv run optimise inv export > my_stash_backup.yaml
```

### Removing Items

Remove an item by its UID:

```bash
uv run optimise inv remove harlequin_crest_001
```

You will be prompted to confirm. To skip the confirmation:

```bash
uv run optimise inv remove harlequin_crest_001 --yes
```

Removing an item also deletes its associated affixes and socket records.

---

## Using Screenshot Input (Claude Code Workflow)

The optimiser supports a screenshot-driven workflow via Claude Code's vision capability.

### How It Works

1. **Take a screenshot** of the item in-game (character screen, stash tab, or hover tooltip).
2. **Drop the screenshot into Claude Code** and describe what you want: "Add this item to my inventory."
3. **Claude reads the affixes** from the screenshot and generates the appropriate `optimise inv add` command.
4. **Review and confirm** -- Claude will show you the command before executing it.

### Tips for Clear Screenshots

- **Character screen tooltips**: Hover over the item to show the full stat tooltip. Ensure the tooltip is fully visible and not clipped.
- **Stash tabs**: Arrange items so tooltips do not overlap.
- **Resolution**: Use at least 1080p. Higher resolution produces more accurate readings.
- **Contrast**: Use the default game UI theme. Custom UI skins may confuse the vision layer.
- **One item at a time**: For best accuracy, screenshot one item per image rather than the entire stash.

### Example Conversation

```
You: [drops screenshot of Shako tooltip]
     "Add this Shako to my inventory"

Claude: I can see a Harlequin Crest (Shako) with:
        +2 All Skills, +98 Life, +98 Mana, DR 10%, MF 50%

        uv run optimise inv add \
            --name "Harlequin Crest" \
            --slot helmet --type unique --base "Shako" \
            --affix all_skills=2 --affix life=98 --affix mana=98 \
            --affix dr=10 --affix mf=50

        Shall I run this?
```

---

## Running the Optimiser

### Basic Usage

Run the optimiser for a named build:

```bash
uv run optimise run warlock_echoing_strike_mf
```

This searches all valid gear combinations from your inventory and returns the top 5 loadouts.

### Command Options

```
Usage: optimise run [OPTIONS] BUILD_NAME

  Run the gear optimiser for a build.

Options:
  --mode [mf|dps|balanced|survivability]
                                  Weight preset to use (overrides default objectives).
  --top-k INTEGER                 Number of top results to return.  [default: 5]
  --workers INTEGER               Parallel workers (default: auto).
  --json                          Output as JSON instead of a table.
```

### Weight Presets

Each build defines preset weight profiles that shift the optimiser's priorities:

```bash
# Maximise magic find (farming runs)
uv run optimise run warlock_echoing_strike_mf --mode mf

# Maximise damage output
uv run optimise run warlock_echoing_strike_mf --mode dps

# Even balance across all dimensions
uv run optimise run warlock_echoing_strike_mf --mode balanced

# Prioritise survivability (Hardcore or dangerous content)
uv run optimise run warlock_echoing_strike_mf --mode survivability
```

For the Echoing Strike MF build, the preset weights are:

| Preset | Damage | Magic Find | EHP | Breakpoint |
|---|---|---|---|---|
| *(default)* | 0.35 | 0.40 | 0.15 | 0.10 |
| `mf` | 0.25 | 0.50 | 0.15 | 0.10 |
| `dps` | 0.55 | 0.15 | 0.20 | 0.10 |
| `balanced` | 0.35 | 0.35 | 0.20 | 0.10 |
| `survivability` | 0.20 | 0.20 | 0.45 | 0.15 |

### Adjusting Top-K Results

By default, the optimiser returns the top 5 loadouts. Change this with `--top-k`:

```bash
uv run optimise run warlock_echoing_strike_mf --top-k 10
```

### Using Parallel Workers

The search is parallelised by sharding across weapon candidates. By default, the optimiser uses as many CPU cores as there are weapon candidates.

Override manually:

```bash
uv run optimise run warlock_echoing_strike_mf --workers 8
```

Use `--workers 1` to force single-threaded execution (useful for debugging).

### JSON Output

For scripting or piping results to other tools:

```bash
uv run optimise run warlock_echoing_strike_mf --json
```

This prints a JSON array to stdout:

```json
[
  {
    "slots": {
      "weapon": "ariocs_needle_001",
      "shield": "spirit_001",
      "helmet": "harlequin_crest_001",
      "body": "enigma_001",
      "gloves": "chance_guards_001",
      "belt": "arachnid_mesh_001",
      "boots": "war_traveler_001",
      "amulet": "maras_kaleidoscope_001",
      "ring1": "stone_of_jordan_001",
      "ring2": "nagelring_001"
    },
    "socket_fillings": {},
    "total_score": 0.756,
    "stats": {
      "mf": 266,
      "fcr": 105,
      "all_skills": 13,
      "resistance_all": 55
    },
    "score_breakdown": {
      "damage": 0.624,
      "magic_find": 0.515,
      "effective_hp": 0.412,
      "breakpoint_score": 0.880
    }
  }
]
```

### Reading the Results Table

When run without `--json`, the output is a Rich-formatted table:

| Column | Description |
|---|---|
| **Rank** | Position in the ranking (1 = best). |
| **Score** | Weighted composite score (higher is better). |
| **Weapon** ... **Ring2** | Item UID assigned to each slot. |
| **MF** | Total raw magic find from all gear. |
| **FCR** | Total faster cast rate from all gear. |

Below the table, the tool prints a summary of the best loadout's key stats and the per-dimension score breakdown:

```
Best loadout stats: MF: 266 | FCR: 105 | +Skills: 13 | All Res: 55

Score breakdown: Damage=0.624 MF=0.515 EHP=0.412 BP=0.880
```

---

## Understanding Scoring

### The 4 Dimensions

Every loadout is scored across four dimensions:

| Dimension | Range | What It Measures |
|---|---|---|
| **damage** | 0.0 -- 1.0 | Estimated relative damage output, factoring weapon ED, +skills, FCR cast speed, deadly strike. Normalised against a reference ceiling. |
| **magic_find** | 0.0 -- 1.0 | Effective unique-find MF after diminishing returns. Higher raw MF has less impact per point. |
| **effective_hp** | 0.0 -- 1.0 | Survivability combining life pool, physical damage reduction, and elemental resistances. |
| **breakpoint_score** | 0.0 -- 1.0 | How well the loadout hits FCR/FHR breakpoints and resistance caps. |

### How Weights Work

The composite score is a weighted sum:

```
total_score = damage * W_damage
            + magic_find * W_mf
            + effective_hp * W_ehp
            + breakpoint_score * W_bp
```

Weights always sum to 1.0. They are set by the build YAML's default objectives, then optionally overridden by `--mode` presets.

### MF Diminishing Returns

D2R applies diminishing returns to raw Magic Find. The effective MF for finding different item qualities is:

| Raw MF | Unique (eff) | Set (eff) | Rare (eff) |
|---|---|---|---|
| 0 | 0 | 0 | 0 |
| 50 | 42 | 45 | 46 |
| 100 | 71 | 83 | 86 |
| 200 | 111 | 143 | 150 |
| 300 | 136 | 188 | 200 |
| 400 | 154 | 222 | 240 |
| 500 | 167 | 250 | 273 |
| 700 | 184 | 292 | 323 |
| 1000 | 200 | 333 | 375 |

The formulas:

- **Unique**: `raw_mf * 250 / (raw_mf + 250)` -- asymptote at 250
- **Set**: `raw_mf * 500 / (raw_mf + 500)` -- asymptote at 500
- **Rare**: `raw_mf * 600 / (raw_mf + 600)` -- asymptote at 600

The optimiser uses the **unique-find** effective MF as the scoring basis, since unique drops are typically the primary farming goal.

> **Key insight:** Going from 0 to 200 raw MF gains you 111 effective unique-find MF. Going from 200 to 400 gains only 43 more. Stacking MF beyond 300-400 raw has sharply decreasing returns.

### Hard Constraints

Loadouts that violate any hard constraint are automatically excluded from results. For the Echoing Strike MF build:

| Constraint | Requirement | Reason |
|---|---|---|
| FCR >= 75 | 75% faster cast rate | Minimum breakpoint for acceptable cast speed. |
| Resistance All >= 75 | Max resistance cap | Required to survive Hell difficulty. |
| Strength >= gear requirement | Enough to equip all gear | Dynamically checked. |
| Dexterity >= gear requirement | Enough to equip all gear | Dynamically checked. |

---

## Browsing Builds

### Listing Available Builds

```bash
uv run optimise build list
```

This shows a table of all builds defined in `data/builds/`:

```
                Available Builds
 Name                           Class    Description
 warlock_echoing_strike_mf      warlock  S-tier MF farmer. Physical + Magic ...
```

### Viewing Build Details

```bash
uv run optimise build show warlock_echoing_strike_mf
```

This prints a detailed panel with:

- **Header**: display name, class, formula module, and description.
- **Skill Points**: the full skill allocation table.
- **Default Objectives**: the four dimension weights.
- **Hard Constraints**: every constraint the optimiser enforces.
- **Weight Presets**: all available `--mode` options and their weight distributions.

---

## Formula Validation

The optimiser includes a four-layer validation pipeline to ensure the scoring formula matches reality.

### Recording Live Measurements

After equipping a loadout in-game, record the actual stats you observe:

```bash
uv run optimise validate record my_mf_set \
    --build warlock_echoing_strike_mf \
    --predicted-mf 266 \
    --actual-mf 259 \
    --predicted-fcr 105 \
    --actual-fcr 105 \
    --predicted-damage 1500 \
    --actual-damage 1430 \
    --predicted-hp 2200 \
    --actual-hp 2150 \
    --notes "Tested in Hell Mephisto runs, 2026-04-10"
```

The `gear_set_id` (first argument, e.g. `my_mf_set`) is a label you choose to identify this particular gear combination. The tool computes and stores the maximum deviation across all stat pairs.

#### Record Command Options

| Option | Description |
|---|---|
| `--build` | Build definition name (default: `unknown`). |
| `--actual-damage` | Measured damage value from in-game. |
| `--actual-mf` | Measured magic find from character screen. |
| `--actual-hp` | Measured HP from character screen. |
| `--actual-fcr` | Measured FCR from character screen. |
| `--predicted-damage` | Predicted damage from the formula. |
| `--predicted-mf` | Predicted MF from the formula. |
| `--predicted-hp` | Predicted HP from the formula. |
| `--predicted-fcr` | Predicted FCR from the formula. |
| `--notes` | Free-text notes about this measurement. |

### Checking Accuracy

View the deviation report for all recorded validations:

```bash
uv run optimise validate check
```

Filter by build:

```bash
uv run optimise validate check --build warlock_echoing_strike_mf
```

### Understanding Deviation Reports

The report is a colour-coded Rich table:

| Colour | Deviation | Status | Meaning |
|---|---|---|---|
| Green | < 5% | **PASS** | Formula is well calibrated. |
| Yellow | 5% -- 10% | **WARN** | Minor inaccuracy; consider investigating. |
| Red | >= 10% | **FAIL** | Significant deviation; formula needs adjustment. |

Each row shows predicted vs actual values for damage, MF, HP, and FCR, plus the maximum deviation percentage.

The summary line at the bottom reports how many records are within the 5% tolerance.

### Using Validation to Calibrate the Formula

1. **Record multiple gear sets** with varying stat distributions.
2. **Run `validate check`** to identify which stats deviate most.
3. **Investigate**: if MF consistently deviates, check whether all gear affixes are entered correctly. If damage deviates, the formula's scaling constants may need adjustment.
4. **Iterate**: after formula adjustments, re-run validation to confirm improvement.

The validation records persist in the database, building a calibration log over time.

---

## Common Stat Names Reference

Use these abbreviations when adding affixes via `--affix`:

### Offensive Stats

| Stat Key | Full Name |
|---|---|
| `ed` | Enhanced Damage % |
| `damage_min` | Minimum Damage (flat) |
| `damage_max` | Maximum Damage (flat) |
| `all_skills` | +To All Skills |
| `ias` | Increased Attack Speed % |
| `fcr` | Faster Cast Rate % |
| `ds` | Deadly Strike % |
| `cb` | Crushing Blow % |
| `ar` | Attack Rating |
| `light_damage_pct` | +% Lightning Damage |
| `enemy_light_res` | -% Enemy Lightning Resistance |
| `damage_demon_pct` | +% Damage to Demons |
| `ignore_target_defense` | Ignore Target's Defence (flag: 1) |

### Defensive Stats

| Stat Key | Full Name |
|---|---|
| `life` | +Life (flat) |
| `mana` | +Mana (flat) |
| `strength` | +Strength |
| `dexterity` | +Dexterity |
| `vitality` | +Vitality |
| `dr` | Damage Reduction % |
| `fhr` | Faster Hit Recovery % |
| `resistance_all` | +All Resistances |
| `fire_res` | +Fire Resistance |
| `cold_res` | +Cold Resistance |
| `light_res` | +Lightning Resistance |
| `poison_res` | +Poison Resistance |

### Utility Stats

| Stat Key | Full Name |
|---|---|
| `mf` | Magic Find % |
| `gold_find` | Gold Find % |
| `frw` | Faster Run/Walk % |
| `ll` | Life Leech % |
| `ml` | Mana Leech % |
| `mana_pct` | +Mana % |
| `slow_target` | Slow Target % |

---

## Frequently Asked Questions

### "Why does the optimiser take a long time?"

The optimiser uses **exhaustive search** -- it evaluates every valid gear combination to find the absolute best loadouts. No score-based pruning is applied because the design goal is to surface unexpected, non-obvious combinations that a greedy or heuristic algorithm would miss.

Runtime depends on inventory size. With 50+ items, expect 1 to 5 minutes. The search is parallelised across CPU cores by sharding on the weapon slot. Use `--workers` to control parallelism.

If you want faster results during iteration, reduce your inventory to the items you are seriously considering, or use `--top-k 1` to reduce heap management overhead.

### "Can I use this for other classes?"

Not yet. V1 supports the Warlock class with the Echoing Strike MF build. However, the architecture is fully extensible:

- Build definitions are data-driven YAML files.
- Formulae use a Protocol pattern -- any build can supply its own scoring logic.
- Breakpoint data for all classes is stored in `data/breakpoints.yaml`.

Adding a new class requires a new formula module and build YAML. No changes to the core search engine, CLI, or resolver are needed.

### "My MF is 500% but the score says 0.67?"

The MF dimension score applies **diminishing returns**. At 500% raw MF, effective unique-find MF is approximately 167 out of a theoretical maximum of 250. The score `167 / 250 = 0.67` correctly reflects that you are getting 67% of the maximum possible unique-find benefit.

This is not a bug -- it is the real D2R mechanic. Stacking MF beyond 300-400% provides minimal additional unique-find chance.

### "How accurate is the damage formula?"

The V1 damage formula is an approximation based on Maxroll guides and community research. It captures the main scaling factors (weapon damage, ED, +skills, FCR breakpoints, deadly strike) but does not model every interaction in the D2R engine.

Use the `validate` command to compare predicted stats against actual in-game measurements. The target accuracy is within 5% of live values. The formula will be refined over time based on validation data.

### "What if I have two of the same ring?"

Add them as separate items with the same name. Each will get a unique UID (e.g. `nagelring_001`, `nagelring_002`). The optimiser considers both for the ring1 and ring2 slots but enforces that the same physical item cannot appear in both slots simultaneously.

### "How does the runeword resolver work?"

When you have runes in your pool and socketed base items in your inventory, the resolver automatically enumerates all craftable runewords. For example, if you have Jah + Ith + Ber runes and a 3-socket Mage Plate, the resolver will create a virtual "Enigma in Mage Plate" candidate. The search engine then considers this alongside your real items.

Resource conflicts are tracked: the same rune cannot be used in two different items within a single loadout.

### "Where is my data stored?"

All inventory data is stored in `stash.db` (a SQLite file) in the project root, or wherever the `--db` option / `D2R_DB_PATH` environment variable points. This file is in `.gitignore` and is never committed to version control.

Use `optimise inv export > backup.yaml` to create a portable backup of your inventory.
