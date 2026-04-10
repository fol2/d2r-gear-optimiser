"""Top-level orchestration — wires loaders, resolver, DB, and search engine together."""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

from sqlmodel import Session, select

from d2r_optimiser.core.db import create_all_tables, get_engine, reset_engine
from d2r_optimiser.core.formula.base import get_formula
from d2r_optimiser.core.models import Affix, Item, Socket
from d2r_optimiser.core.models.rune import Jewel, JewelAffix, Rune, RunewordRecipe
from d2r_optimiser.core.resolver import enumerate_craftable_runewords, enumerate_socket_options
from d2r_optimiser.core.search import parallel_search, search
from d2r_optimiser.loader import load_breakpoints, load_build, load_runewords

logger = logging.getLogger(__name__)

# Resolve data directory: walk up from this file to project root.
# orchestrator.py -> core -> d2r_optimiser -> src -> project root
_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"


class BuildNotFoundError(Exception):
    """Raised when the requested build definition YAML does not exist."""


class EmptyInventoryError(Exception):
    """Raised when the inventory database contains no items."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def optimise(
    db_path: Path | str,
    build_name: str,
    *,
    mode: str | None = None,
    weight_overrides: dict[str, float] | None = None,
    top_k: int = 5,
    workers: int | None = None,
    progress_callback=None,
) -> list[dict]:
    """Top-level optimisation entry point.

    Steps:
    1. Resolve build definition YAML (from data/builds/<build_name>.yaml)
    2. Apply mode preset or weight overrides to objectives
    3. Load runeword recipes from data/runewords.yaml
    4. Load breakpoints from data/breakpoints.yaml
    5. Query inventory from SQLite (items with affixes, runes, jewels)
    6. Build candidate pool:
       a. Existing items grouped by slot with pre-aggregated stats
       b. Craftable runewords from resolver (with stats from recipe)
       c. Socket filling variants for items with empty sockets
    7. Call parallel_search (or search if workers=1)
    8. Return top-K results

    Raises BuildNotFoundError if build YAML not found.
    Raises EmptyInventoryError if no items in DB.
    """
    # ── 1. Load build definition ───────────────────────────────────────────
    builds_dir = _DATA_DIR / "builds"
    build_yaml = builds_dir / f"{build_name}.yaml"
    if not build_yaml.exists():
        msg = f"Build definition not found: {build_yaml}"
        raise BuildNotFoundError(msg)

    build = load_build(build_yaml)

    # ── 2. Apply mode preset or weight overrides ───────────────────────────
    if mode and mode in build.presets:
        build.objectives = build.presets[mode]
    if weight_overrides:
        obj_data = build.objectives.model_dump()
        obj_data.update(weight_overrides)
        from d2r_optimiser.core.models import ObjectiveWeights

        build.objectives = ObjectiveWeights(**obj_data)

    # ── 3. Load runeword recipes ───────────────────────────────────────────
    runewords_path = _DATA_DIR / "runewords.yaml"
    recipes: list[RunewordRecipe] = []
    if runewords_path.exists():
        recipes = load_runewords(runewords_path)
    else:
        logger.warning(
            "Runewords file not found at %s — runeword candidates excluded.",
            runewords_path,
        )

    # ── 4. Load breakpoints ────────────────────────────────────────────────
    bp_path = _DATA_DIR / "breakpoints.yaml"
    breakpoints: dict = {}
    if bp_path.exists():
        breakpoints = load_breakpoints(bp_path)
    else:
        logger.warning("Breakpoints file not found at %s — breakpoint scoring excluded.", bp_path)

    # ── 5. Query inventory from SQLite ─────────────────────────────────────
    reset_engine()
    engine = get_engine(url=f"sqlite:///{db_path}")
    create_all_tables(engine=engine)
    session = Session(engine)

    try:
        items = session.exec(select(Item)).all()
        if not items:
            msg = "Inventory is empty — add items before running optimisation."
            raise EmptyInventoryError(msg)

        rune_pool = session.exec(select(Rune)).all()
        jewel_pool = session.exec(select(Jewel)).all()

        # Load rune stats from YAML for socket-filling lookups
        rune_stats_lookup = _build_rune_stats_lookup()

        # Load jewel stats from DB
        jewel_stats_lookup = _build_jewel_stats_lookup(session, jewel_pool)

        # ── 6. Build candidate pool ────────────────────────────────────────

        # 6a. Existing items grouped by slot with pre-aggregated stats
        candidates_by_slot: dict[str, list[dict]] = {}

        for item in items:
            affixes = session.exec(
                select(Affix).where(Affix.item_id == item.id)
            ).all()
            sockets = session.exec(
                select(Socket).where(Socket.item_id == item.id).order_by(Socket.socket_index)
            ).all()

            base_stats = _aggregate_affixes(affixes)

            # Add stats from filled sockets
            for sock in sockets:
                if sock.filled_with:
                    socket_stats = _get_socket_content_stats(
                        sock.filled_with, item.slot, rune_stats_lookup, jewel_stats_lookup
                    )
                    for stat, val in socket_stats.items():
                        base_stats[stat] = base_stats.get(stat, 0.0) + val

            # Determine empty socket count
            empty_sockets = sum(1 for s in sockets if s.filled_with is None)
            if empty_sockets == 0 and item.socket_count > len(sockets):
                # Socket records not created yet — treat socket_count as empty
                empty_sockets = item.socket_count - len(sockets)

            # Determine the slot(s) this item can fill
            slot_names = _resolve_slots(item)

            for slot in slot_names:
                if slot not in candidates_by_slot:
                    candidates_by_slot[slot] = []

                if empty_sockets > 0 and (rune_pool or jewel_pool):
                    # 6c. Socket filling variants
                    socket_combos = enumerate_socket_options(
                        Item(
                            uid=item.uid,
                            slot=item.slot,
                            item_type=item.item_type,
                            name=item.name,
                            socket_count=empty_sockets,
                        ),
                        rune_pool,
                        jewel_pool,
                        max_combinations=50,
                    )
                    for combo in socket_combos:
                        variant_stats = dict(base_stats)
                        resource_cost: Counter = Counter()
                        for filling in combo:
                            fill_stats = _get_socket_content_stats(
                                filling, item.slot, rune_stats_lookup, jewel_stats_lookup
                            )
                            for stat, val in fill_stats.items():
                                variant_stats[stat] = variant_stats.get(stat, 0.0) + val
                            # Track resource cost
                            if filling in jewel_stats_lookup:
                                resource_cost[f"jewel:{filling}"] += 1
                            else:
                                resource_cost[f"rune:{filling}"] += 1

                        candidates_by_slot[slot].append({
                            "item_uid": item.uid,
                            "stats": variant_stats,
                            "resource_cost": resource_cost,
                            "socket_fillings": combo if combo else None,
                        })
                else:
                    # No empty sockets — just the base item
                    candidates_by_slot[slot].append({
                        "item_uid": item.uid,
                        "stats": dict(base_stats),
                        "resource_cost": Counter(),
                        "socket_fillings": None,
                    })

        # 6b. Craftable runewords from resolver
        craftable = enumerate_craftable_runewords(rune_pool, items, recipes)
        for entry in craftable:
            recipe: RunewordRecipe = entry["recipe"]
            base_item: Item = entry["base"]
            rune_cost: Counter = entry["rune_cost"]

            rw_stats: dict[str, float] = {}
            try:
                parsed = json.loads(recipe.stats_json)
                for stat, val in parsed.items():
                    rw_stats[stat] = float(val)
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.warning("Skipping runeword %s: invalid stats_json", recipe.name)
                continue

            # Resource cost: prefix rune names for conflict detection
            resource_cost = Counter({f"rune:{r}": c for r, c in rune_cost.items()})

            slot_names = _resolve_slots(base_item)
            for slot in slot_names:
                if slot not in candidates_by_slot:
                    candidates_by_slot[slot] = []

                candidates_by_slot[slot].append({
                    "item_uid": f"rw:{recipe.name}:{base_item.uid}",
                    "stats": rw_stats,
                    "resource_cost": resource_cost,
                    "socket_fillings": None,
                })

        # ── 7. Run search ──────────────────────────────────────────────────
        formula_module = build.formula_module

        # Instantiate formula with breakpoints for the build's class
        class_bp = breakpoints.get(build.character_class, {})
        formula = get_formula(formula_module)
        # Inject breakpoints if the formula supports it
        if hasattr(formula, "_breakpoints"):
            formula._breakpoints = class_bp

        if workers == 1:
            results = search(
                candidates_by_slot,
                build,
                formula,
                top_k=top_k,
                progress_callback=progress_callback,
            )
        else:
            results = parallel_search(
                candidates_by_slot,
                build,
                formula_module,
                top_k=top_k,
                workers=workers,
                progress_callback=progress_callback,
                breakpoints=breakpoints,
            )

        return results

    finally:
        session.close()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _aggregate_affixes(affixes: list[Affix]) -> dict[str, float]:
    """Sum affix values into a flat {stat: value} dict."""
    stats: dict[str, float] = {}
    for affix in affixes:
        stats[affix.stat] = stats.get(affix.stat, 0.0) + affix.value
    return stats


def _resolve_slots(item: Item) -> list[str]:
    """Resolve which candidate slots an item can fill.

    Ring-type items produce candidates for both ring1 and ring2.
    All others use the item's slot directly.
    """
    if item.slot == "ring":
        return ["ring1", "ring2"]
    return [item.slot]


def _build_rune_stats_lookup() -> dict[str, dict[str, dict[str, float]]]:
    """Load rune stats from data/runes.yaml into a lookup dict.

    Returns ``{rune_name: {context: {stat: value}}}`` where context is
    ``"weapon_stats"``, ``"armour_stats"``, or ``"shield_stats"``.
    """
    runes_path = _DATA_DIR / "runes.yaml"
    if not runes_path.exists():
        logger.warning("Runes file not found at %s — rune stats unavailable.", runes_path)
        return {}

    import yaml

    raw = runes_path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        logger.warning("Invalid YAML in %s: %s — rune stats unavailable.", runes_path, exc)
        return {}
    if not data or "runes" not in data:
        return {}

    lookup: dict[str, dict[str, dict[str, float]]] = {}
    for rune_entry in data["runes"]:
        name = rune_entry["name"]
        lookup[name] = {}
        for ctx in ("weapon_stats", "armour_stats", "shield_stats"):
            if ctx in rune_entry and isinstance(rune_entry[ctx], dict):
                # Filter to numeric values only
                lookup[name][ctx] = {
                    k: float(v)
                    for k, v in rune_entry[ctx].items()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)
                }
    return lookup


def _build_jewel_stats_lookup(
    session: Session, jewel_pool: list[Jewel]
) -> dict[str, dict[str, float]]:
    """Build jewel stats lookup from DB.

    Returns ``{jewel_uid: {stat: value}}``.
    """
    lookup: dict[str, dict[str, float]] = {}
    for jewel in jewel_pool:
        affixes = session.exec(
            select(JewelAffix).where(JewelAffix.jewel_id == jewel.id)
        ).all()
        stats: dict[str, float] = {}
        for a in affixes:
            stats[a.stat] = stats.get(a.stat, 0.0) + a.value
        lookup[jewel.uid] = stats
    return lookup


def _get_socket_content_stats(
    filling: str,
    item_slot: str,
    rune_stats_lookup: dict[str, dict[str, dict[str, float]]],
    jewel_stats_lookup: dict[str, dict[str, float]],
) -> dict[str, float]:
    """Get stats for a socket filling (rune name or jewel uid).

    For runes, the stat context depends on the item slot:
    - weapon -> weapon_stats
    - shield -> shield_stats
    - everything else -> armour_stats
    """
    # Check if it is a jewel first
    if filling in jewel_stats_lookup:
        return dict(jewel_stats_lookup[filling])

    # It is a rune
    rune_data = rune_stats_lookup.get(filling, {})
    if not rune_data:
        return {}

    if item_slot == "weapon":
        ctx = "weapon_stats"
    elif item_slot == "shield":
        ctx = "shield_stats"
    else:
        ctx = "armour_stats"

    return dict(rune_data.get(ctx, {}))
