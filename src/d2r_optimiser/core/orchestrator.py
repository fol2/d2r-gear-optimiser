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
from d2r_optimiser.core.models.rune import Gem, Jewel, JewelAffix, Rune, RunewordRecipe
from d2r_optimiser.core.resolver import enumerate_craftable_runewords, enumerate_socket_options
from d2r_optimiser.core.search import parallel_search, search
from d2r_optimiser.core.stats import merge_stats, normalise_stats
from d2r_optimiser.loader import load_breakpoints, load_build, load_runewords, load_sets

logger = logging.getLogger(__name__)

# Resolve data directory: walk up from this file to project root.
# orchestrator.py -> core -> d2r_optimiser -> src -> project root
_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"


class BuildNotFoundError(Exception):
    """Raised when the requested build definition YAML does not exist."""


class EmptyInventoryError(Exception):
    """Raised when the inventory database contains no items."""


class InvalidBuildModeError(Exception):
    """Raised when the requested preset mode is not defined by the build."""


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
    if mode:
        if mode not in build.presets:
            available = ", ".join(sorted(build.presets)) or "none"
            msg = f"Unknown mode {mode!r} for build {build_name!r}. Available modes: {available}"
            raise InvalidBuildModeError(msg)
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

    # ── 4b. Load set bonus definitions ────────────────────────────────────
    sets_path = _DATA_DIR / "sets.yaml"
    set_lookup: dict[str, dict] = {}
    if sets_path.exists():
        try:
            set_lookup = _build_set_lookup(load_sets(sets_path))
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to load set definitions from %s: %s", sets_path, exc)
    else:
        logger.warning("Sets file not found at %s — set bonuses excluded.", sets_path)

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
        gem_pool = session.exec(select(Gem)).all()
        jewel_pool = session.exec(select(Jewel)).all()
        available_pool = _build_available_resource_pool(rune_pool, gem_pool, jewel_pool)

        # Load rune stats from YAML for socket-filling lookups
        rune_stats_lookup = _build_rune_stats_lookup()
        gem_stats_lookup = _build_gem_stats_lookup()

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
                        sock.filled_with,
                        item.slot,
                        rune_stats_lookup,
                        gem_stats_lookup,
                        jewel_stats_lookup,
                    )
                    merge_stats(base_stats, socket_stats)

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

                if empty_sockets > 0 and (rune_pool or gem_pool or jewel_pool):
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
                        gem_pool,
                        max_combinations=50,
                    )
                    for combo in socket_combos:
                        variant_stats = dict(base_stats)
                        resource_cost: Counter = Counter()
                        for filling in combo:
                            fill_stats = _get_socket_content_stats(
                                filling,
                                item.slot,
                                rune_stats_lookup,
                                gem_stats_lookup,
                                jewel_stats_lookup,
                            )
                            merge_stats(variant_stats, fill_stats)
                            # Track resource cost
                            if filling in jewel_stats_lookup:
                                resource_cost[f"jewel:{filling}"] += 1
                            elif filling in gem_stats_lookup:
                                resource_cost[f"gem:{filling}"] += 1
                            else:
                                resource_cost[f"rune:{filling}"] += 1

                        candidates_by_slot[slot].append({
                            "item_uid": item.uid,
                            "stats": variant_stats,
                            "resource_cost": resource_cost,
                            "socket_fillings": combo if combo else None,
                            "set_meta": _candidate_set_meta(item.name, set_lookup),
                        })
                else:
                    # No empty sockets — just the base item
                    candidates_by_slot[slot].append({
                        "item_uid": item.uid,
                        "stats": dict(base_stats),
                        "resource_cost": Counter(),
                        "socket_fillings": None,
                        "set_meta": _candidate_set_meta(item.name, set_lookup),
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
                    "stats": normalise_stats(rw_stats),
                    "resource_cost": resource_cost,
                    "socket_fillings": None,
                    "set_meta": None,
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
                available_pool=available_pool,
                progress_callback=progress_callback,
            )
        else:
            results = parallel_search(
                candidates_by_slot,
                build,
                formula_module,
                top_k=top_k,
                workers=workers,
                available_pool=available_pool,
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
        merge_stats(stats, {affix.stat: affix.value})
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
                lookup[name][ctx] = normalise_stats(lookup[name][ctx])
    return lookup


def _build_gem_stats_lookup() -> dict[str, dict[str, dict[str, float]]]:
    """Load gem stats from data/gems.yaml into a lookup dict."""
    gems_path = _DATA_DIR / "gems.yaml"
    if not gems_path.exists():
        logger.warning("Gems file not found at %s — gem stats unavailable.", gems_path)
        return {}

    import yaml

    raw = gems_path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        logger.warning("Invalid YAML in %s: %s — gem stats unavailable.", gems_path, exc)
        return {}
    if not data or "gems" not in data:
        return {}

    lookup: dict[str, dict[str, dict[str, float]]] = {}
    for gem_entry in data["gems"]:
        name = gem_entry["name"]
        lookup[name] = {}
        for ctx in ("weapon_stats", "armour_stats", "shield_stats"):
            if ctx in gem_entry and isinstance(gem_entry[ctx], dict):
                lookup[name][ctx] = {
                    k: float(v)
                    for k, v in gem_entry[ctx].items()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)
                }
                lookup[name][ctx] = normalise_stats(lookup[name][ctx])
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
            merge_stats(stats, {a.stat: a.value})
        lookup[jewel.uid] = stats
    return lookup


def _build_available_resource_pool(
    rune_pool: list[Rune],
    gem_pool: list[Gem],
    jewel_pool: list[Jewel],
) -> Counter:
    """Build a resource availability counter for search-time conflict checks."""
    pool: Counter = Counter()
    for rune in rune_pool:
        if rune.quantity > 0:
            pool[f"rune:{rune.rune_type}"] += rune.quantity
    for gem in gem_pool:
        if gem.quantity > 0:
            pool[f"gem:{gem.name}"] += gem.quantity
    for jewel in jewel_pool:
        pool[f"jewel:{jewel.uid}"] += 1
    return pool


def _get_socket_content_stats(
    filling: str,
    item_slot: str,
    rune_stats_lookup: dict[str, dict[str, dict[str, float]]],
    gem_stats_lookup: dict[str, dict[str, dict[str, float]]],
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
        return normalise_stats(jewel_stats_lookup[filling])

    if item_slot == "weapon":
        ctx = "weapon_stats"
    elif item_slot == "shield":
        ctx = "shield_stats"
    else:
        ctx = "armour_stats"

    gem_data = gem_stats_lookup.get(filling, {})
    if gem_data:
        return normalise_stats(gem_data.get(ctx, {}))

    rune_data = rune_stats_lookup.get(filling, {})
    if not rune_data:
        return {}

    return normalise_stats(rune_data.get(ctx, {}))


def _build_set_lookup(set_defs: list) -> dict[str, dict]:
    """Index set definitions by item name for search-time bonus application."""
    lookup: dict[str, dict] = {}
    for set_def in set_defs:
        set_size = len(set_def.items)
        partial_bonuses = {
            threshold: normalise_stats(stats)
            for threshold, stats in set_def.partial_bonuses.items()
        }
        full_bonus = normalise_stats(set_def.full_bonus)
        for item in set_def.items:
            lookup[item.name] = {
                "set_name": set_def.set_name,
                "set_size": set_size,
                "item_name": item.name,
                "item_partial_bonus": {
                    threshold: normalise_stats(stats)
                    for threshold, stats in item.item_partial_bonus.items()
                },
                "partial_bonuses": partial_bonuses,
                "full_bonus": full_bonus,
            }
    return lookup


def _candidate_set_meta(item_name: str, set_lookup: dict[str, dict]) -> dict | None:
    """Return set metadata for an item candidate if it belongs to a set."""
    meta = set_lookup.get(item_name)
    if not meta:
        return None
    return {
        "set_name": meta["set_name"],
        "set_size": meta["set_size"],
        "item_name": meta["item_name"],
        "item_partial_bonus": dict(meta["item_partial_bonus"]),
        "partial_bonuses": dict(meta["partial_bonuses"]),
        "full_bonus": dict(meta["full_bonus"]),
    }
