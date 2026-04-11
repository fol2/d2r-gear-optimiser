"""Inventory management CLI commands."""

import re
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.table import Table
from sqlmodel import select

from d2r_optimiser.cli._db_helpers import ensure_db
from d2r_optimiser.core.models import Affix, Item, Socket
from d2r_optimiser.core.models._common import utcnow
from d2r_optimiser.core.models.rune import Gem, Jewel, JewelAffix, Rune
from d2r_optimiser.vision import ParsedScreenshotItem, ScreenshotParserError, parse_item_screenshot

console = Console(width=120)


def _slugify(name: str) -> str:
    """Convert item name to a slug (lowercase, underscores, ASCII only)."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


def _next_uid(session, base_slug: str) -> str:
    """Generate a unique uid by appending a counter to the base slug."""
    existing = session.exec(
        select(Item.uid).where(Item.uid.startswith(base_slug))
    ).all()
    if not existing:
        return f"{base_slug}_001"
    # Extract numeric suffixes and find the max
    max_counter = 0
    for uid in existing:
        match = re.search(r"_(\d+)$", uid)
        if match:
            max_counter = max(max_counter, int(match.group(1)))
    return f"{base_slug}_{max_counter + 1:03d}"


def _parse_affix_args(affixes: tuple[str, ...]) -> dict[str, float]:
    """Parse repeated ``stat=value`` CLI arguments into a numeric mapping."""
    parsed: dict[str, float] = {}
    for affix_str in affixes:
        if "=" not in affix_str:
            msg = f"Invalid affix format: {affix_str!r} (expected stat=value)"
            raise ValueError(msg)
        stat, _, val_str = affix_str.partition("=")
        try:
            value = float(val_str)
        except ValueError as exc:
            msg = f"Invalid affix value: {val_str!r} in {affix_str!r}"
            raise ValueError(msg) from exc
        parsed[stat.strip()] = value
    return parsed


def _delete_item_dependents(session, item: Item) -> None:
    """Delete child rows tied to an inventory item."""
    for affix in session.exec(select(Affix).where(Affix.item_id == item.id)).all():
        session.delete(affix)
    for socket in session.exec(select(Socket).where(Socket.item_id == item.id)).all():
        session.delete(socket)


def _replace_item_affixes(session, item: Item, affixes: dict[str, float]) -> None:
    """Replace an item's affixes with the provided mapping."""
    for affix in session.exec(select(Affix).where(Affix.item_id == item.id)).all():
        session.delete(affix)
    for stat, value in affixes.items():
        session.add(Affix(item_id=item.id, stat=stat, value=value))


def _replace_item_sockets(
    session,
    item: Item,
    socket_count: int,
    socket_fillings: list[str] | tuple[str, ...],
) -> None:
    """Replace an item's socket rows to match the supplied state."""
    for socket in session.exec(select(Socket).where(Socket.item_id == item.id)).all():
        session.delete(socket)

    for index in range(socket_count):
        fill = socket_fillings[index] if index < len(socket_fillings) else None
        session.add(Socket(item_id=item.id, socket_index=index, filled_with=fill))


def _create_inventory_item(
    session,
    *,
    name: str,
    slot: str,
    item_type: str,
    base: str | None = None,
    affixes: dict[str, float] | None = None,
    socket_count: int = 0,
    socket_fillings: list[str] | tuple[str, ...] = (),
    location: str | None = None,
    ethereal: bool = False,
    notes: str | None = None,
) -> Item:
    """Insert an inventory item and its dependent affix/socket rows."""
    slug = _slugify(name)
    uid = _next_uid(session, slug)

    item = Item(
        uid=uid,
        name=name,
        slot=slot,
        item_type=item_type,
        base=base,
        socket_count=socket_count,
        location=location,
        ethereal=ethereal,
        notes=notes,
    )
    session.add(item)
    session.flush()

    _replace_item_affixes(session, item, affixes or {})
    _replace_item_sockets(session, item, socket_count, socket_fillings)
    return item


def _print_parsed_screenshot_item(parsed: ParsedScreenshotItem, image: Path) -> None:
    """Render a parsed screenshot summary before confirmation."""
    console.print(f"[bold]Parsed screenshot:[/bold] {image.name}")
    console.print(f"Name: {parsed.name or '[unknown]'}")
    console.print(f"Slot: {parsed.slot or '[unknown]'}")
    console.print(f"Type: {parsed.item_type or '[unknown]'}")
    if parsed.base:
        console.print(f"Base: {parsed.base}")
    console.print(f"Sockets: {max(parsed.socket_count, len(parsed.socket_fill))}")
    if parsed.socket_fill:
        console.print(f"Socket fill: {', '.join(parsed.socket_fill)}")
    if parsed.affixes:
        console.print(
            "Affixes: "
            + ", ".join(f"{stat}={value:g}" for stat, value in sorted(parsed.affixes.items()))
        )
    if parsed.confidence:
        console.print(f"Confidence: {parsed.confidence:.2f}")
    for warning in parsed.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")


@click.group("inv")
@click.pass_context
def inv_group(ctx: click.Context) -> None:
    """Manage your gear inventory."""


# ── inv list ────────────────────────────────────────────────────────────────


@inv_group.command("list")
@click.option("--slot", default=None, help="Filter by slot (helmet, body, etc.).")
@click.option(
    "--type", "item_type", default=None, help="Filter by type (unique, set, runeword, etc.)."
)
@click.pass_context
def inv_list(ctx: click.Context, slot: str | None, item_type: str | None) -> None:
    """List items in the inventory."""
    session = ensure_db(ctx.obj["db_path"])
    try:
        stmt = select(Item)
        if slot:
            stmt = stmt.where(Item.slot == slot)
        if item_type:
            stmt = stmt.where(Item.item_type == item_type)

        items = session.exec(stmt).all()

        if not items:
            console.print("[dim]No items in inventory.[/dim]")
            return

        table = Table(title="Inventory")
        table.add_column("UID", style="cyan", no_wrap=True)
        table.add_column("Name", style="bold")
        table.add_column("Type")
        table.add_column("Slot")
        table.add_column("Base")
        table.add_column("Sockets", justify="right")
        table.add_column("Key Affixes", style="green")
        table.add_column("Location")

        key_stats = {"mf", "fcr", "all_skills", "fhr", "ed", "ias"}

        for item in items:
            affixes = session.exec(
                select(Affix).where(Affix.item_id == item.id)
            ).all()
            key_affix_strs = [
                f"{a.stat}={a.value:g}" for a in affixes if a.stat in key_stats
            ]

            table.add_row(
                item.uid,
                item.name,
                item.item_type,
                item.slot,
                item.base or "",
                str(item.socket_count),
                ", ".join(key_affix_strs) if key_affix_strs else "",
                item.location or "",
            )

        console.print(table)
    finally:
        session.close()


# ── inv add ─────────────────────────────────────────────────────────────────


@inv_group.command("add")
@click.option("--name", prompt="Item name", help="Display name of the item.")
@click.option("--slot", prompt="Slot", help="Equipment slot (helmet, body, weapon, etc.).")
@click.option("--type", "item_type", prompt="Type", help="Item type (unique, set, runeword, etc.).")
@click.option("--base", default=None, help="Base item name (e.g. Shako, Monarch).")
@click.option(
    "--affix", multiple=True, help="Affix as stat=value (repeatable, e.g. --affix mf=50)."
)
@click.option("--sockets", default=0, type=int, help="Number of sockets.")
@click.option("--socket-fill", multiple=True, help="Socket fillings in order (repeatable).")
@click.option("--location", default=None, help="Where the item is stored (stash, equipped, mule1).")
@click.option("--ethereal", is_flag=True, help="Mark item as ethereal.")
@click.pass_context
def inv_add(
    ctx: click.Context,
    name: str,
    slot: str,
    item_type: str,
    base: str | None,
    affix: tuple[str, ...],
    sockets: int,
    socket_fill: tuple[str, ...],
    location: str | None,
    ethereal: bool,
) -> None:
    """Add an item to the inventory."""
    session = ensure_db(ctx.obj["db_path"])
    try:
        try:
            affixes = _parse_affix_args(affix)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            session.rollback()
            return

        item = _create_inventory_item(
            session,
            name=name,
            slot=slot,
            item_type=item_type,
            base=base,
            affixes=affixes,
            socket_count=sockets,
            socket_fillings=socket_fill,
            location=location,
            ethereal=ethereal,
        )

        session.commit()
        console.print(f"[green]Added:[/green] {item.name} [cyan]({item.uid})[/cyan]")
    finally:
        session.close()


@inv_group.command("edit")
@click.argument("uid")
@click.option("--name", default=None, help="Updated display name.")
@click.option("--slot", default=None, help="Updated equipment slot.")
@click.option("--type", "item_type", default=None, help="Updated item type.")
@click.option("--base", default=None, help="Updated base item name.")
@click.option("--affix", multiple=True, help="Replacement affix set as stat=value.")
@click.option("--clear-affixes", is_flag=True, help="Remove all affixes from the item.")
@click.option("--sockets", default=None, type=int, help="Updated socket count.")
@click.option("--socket-fill", multiple=True, help="Replacement socket fillings in order.")
@click.option(
    "--clear-socket-fill",
    is_flag=True,
    help="Clear all socket fillings while keeping the socket count.",
)
@click.option("--location", default=None, help="Updated storage location.")
@click.option("--notes", default=None, help="Updated notes.")
@click.option("--ethereal/--non-ethereal", default=None, help="Set the ethereal flag.")
@click.pass_context
def inv_edit(
    ctx: click.Context,
    uid: str,
    name: str | None,
    slot: str | None,
    item_type: str | None,
    base: str | None,
    affix: tuple[str, ...],
    clear_affixes: bool,
    sockets: int | None,
    socket_fill: tuple[str, ...],
    clear_socket_fill: bool,
    location: str | None,
    notes: str | None,
    ethereal: bool | None,
) -> None:
    """Edit an existing inventory item by UID."""
    session = ensure_db(ctx.obj["db_path"])
    try:
        item = session.exec(select(Item).where(Item.uid == uid)).first()
        if item is None:
            console.print(f"[red]Item not found:[/red] {uid}")
            ctx.exit(1)
            return

        if clear_affixes and affix:
            console.print("[red]Use either --affix or --clear-affixes, not both.[/red]")
            ctx.exit(1)
            return

        if clear_socket_fill and socket_fill:
            console.print("[red]Use either --socket-fill or --clear-socket-fill, not both.[/red]")
            ctx.exit(1)
            return

        item.name = name if name is not None else item.name
        item.slot = slot if slot is not None else item.slot
        item.item_type = item_type if item_type is not None else item.item_type
        item.base = base if base is not None else item.base
        item.location = location if location is not None else item.location
        item.notes = notes if notes is not None else item.notes
        if ethereal is not None:
            item.ethereal = ethereal

        if clear_affixes or affix:
            try:
                affixes = _parse_affix_args(affix) if affix else {}
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
                ctx.exit(1)
                return
            _replace_item_affixes(session, item, affixes)

        existing_sockets = session.exec(
            select(Socket).where(Socket.item_id == item.id).order_by(Socket.socket_index)
        ).all()
        if sockets is not None or socket_fill or clear_socket_fill:
            target_socket_count = sockets if sockets is not None else item.socket_count
            if target_socket_count < 0:
                console.print("[red]Socket count cannot be negative.[/red]")
                ctx.exit(1)
                return

            if clear_socket_fill:
                new_fillings: list[str] = []
            elif socket_fill:
                new_fillings = list(socket_fill)
            else:
                new_fillings = [
                    sock.filled_with
                    for sock in existing_sockets[:target_socket_count]
                    if sock.filled_with is not None
                ]

            if len(new_fillings) > target_socket_count:
                console.print("[red]More socket fillings supplied than sockets available.[/red]")
                ctx.exit(1)
                return

            item.socket_count = target_socket_count
            _replace_item_sockets(session, item, target_socket_count, new_fillings)

        item.updated_at = utcnow()
        session.add(item)
        session.commit()
        console.print(f"[green]Updated:[/green] {item.name} [cyan]({item.uid})[/cyan]")
    finally:
        session.close()


@inv_group.command("add-from-screenshot")
@click.argument("image", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--provider",
    type=click.Choice(["auto", "gemini", "openai"]),
    default="auto",
    show_default=True,
    help="Vision backend to use.",
)
@click.option("--model", default=None, help="Model override for the selected provider.")
@click.option("--location", default=None, help="Where the item is stored after import.")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Parse and print the item without writing to the database.",
)
@click.option("--yes", is_flag=True, help="Skip confirmation before adding the parsed item.")
@click.pass_context
def inv_add_from_screenshot(
    ctx: click.Context,
    image: Path,
    provider: str,
    model: str | None,
    location: str | None,
    dry_run: bool,
    yes: bool,
) -> None:
    """Parse an item screenshot and add the detected item to the inventory."""
    try:
        parsed = parse_item_screenshot(image, provider=provider, model=model)
    except ScreenshotParserError as exc:
        console.print(f"[red]Screenshot parse failed:[/red] {exc}")
        ctx.exit(1)
        return

    _print_parsed_screenshot_item(parsed, image)

    required_fields = {
        "name": parsed.name.strip(),
        "slot": parsed.slot.strip(),
        "type": parsed.item_type.strip(),
    }
    missing = [label for label, value in required_fields.items() if not value]
    if not parsed.parse_ok or missing:
        for warning in parsed.warnings:
            console.print(f"[yellow]Warning:[/yellow] {warning}")
        console.print(
            "[red]Screenshot parser could not confidently extract a complete item.[/red]"
        )
        if missing:
            console.print(f"[dim]Missing fields: {', '.join(missing)}[/dim]")
        ctx.exit(1)
        return

    if dry_run:
        return

    if not yes:
        click.confirm("Add this parsed item to the inventory?", abort=True)

    session = ensure_db(ctx.obj["db_path"])
    try:
        item = _create_inventory_item(
            session,
            name=parsed.name.strip(),
            slot=parsed.slot.strip(),
            item_type=parsed.item_type.strip(),
            base=parsed.base,
            affixes=parsed.affixes,
            socket_count=max(parsed.socket_count, len(parsed.socket_fill)),
            socket_fillings=parsed.socket_fill,
            location=location,
            ethereal=parsed.ethereal,
            notes=parsed.notes,
        )
        session.commit()
        console.print(f"[green]Added:[/green] {item.name} [cyan]({item.uid})[/cyan]")
    finally:
        session.close()


# ── inv remove ──────────────────────────────────────────────────────────────


@inv_group.command("remove")
@click.argument("uid")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def inv_remove(ctx: click.Context, uid: str, yes: bool) -> None:
    """Remove an item by its UID."""
    session = ensure_db(ctx.obj["db_path"])
    try:
        item = session.exec(select(Item).where(Item.uid == uid)).first()
        if item is None:
            console.print(f"[red]Item not found:[/red] {uid}")
            ctx.exit(1)
            return

        if not yes:
            click.confirm(f"Remove {item.name} ({uid})?", abort=True)

        # Remove dependent rows first
        _delete_item_dependents(session, item)
        session.delete(item)
        session.commit()
        console.print(f"[green]Removed:[/green] {item.name} ({uid})")
    finally:
        session.close()


# ── inv import ──────────────────────────────────────────────────────────────


@inv_group.command("import")
@click.argument("file", type=click.Path(exists=True))
@click.pass_context
def inv_import(ctx: click.Context, file: str) -> None:
    """Bulk import items from a YAML file."""
    path = Path(file)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        console.print(f"[red]Cannot read file:[/red] {exc}")
        ctx.exit(1)
        return

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        console.print(f"[red]Invalid YAML:[/red] {exc}")
        ctx.exit(1)
        return

    if not isinstance(data, dict) or "items" not in data:
        console.print("[red]YAML must contain a top-level 'items' list.[/red]")
        ctx.exit(1)
        return

    session = ensure_db(ctx.obj["db_path"])
    count = 0
    required = {"name", "slot", "type"}
    try:
        for idx, entry in enumerate(data.get("items", [])):
            if not isinstance(entry, dict):
                console.print(f"[yellow]Skipping entry {idx}: not a mapping[/yellow]")
                continue
            missing = required - entry.keys()
            if missing:
                label = entry.get("name", f"#{idx}")
                console.print(f"[yellow]Skipping '{label}': missing {sorted(missing)}[/yellow]")
                continue

            name = entry.get("name", "unknown")
            slug = _slugify(name)
            uid = _next_uid(session, slug)

            item = Item(
                uid=uid,
                name=name,
                slot=entry.get("slot", "unknown"),
                item_type=entry.get("type", "unknown"),
                base=entry.get("base"),
                socket_count=entry.get("sockets", 0),
                location=entry.get("location"),
                ethereal=entry.get("ethereal", False),
            )
            session.add(item)
            session.flush()

            affixes = entry.get("affixes", {})
            if not isinstance(affixes, dict):
                console.print(
                    f"[yellow]Warning: affixes for '{name}' is not a mapping"
                    " — skipping affixes[/yellow]"
                )
                affixes = {}

            for stat, value in affixes.items():
                try:
                    session.add(Affix(item_id=item.id, stat=stat, value=float(value)))
                except (ValueError, TypeError):
                    console.print(
                        f"[yellow]Warning: skipping affix {stat}={value!r}"
                        f" on '{name}' (not numeric)[/yellow]"
                    )

            for i in range(item.socket_count):
                fills = entry.get("socket_fill", [])
                fill = fills[i] if i < len(fills) else None
                session.add(Socket(item_id=item.id, socket_index=i, filled_with=fill))

            count += 1

        session.commit()
        console.print(f"[green]Imported {count} item(s).[/green]")
    finally:
        session.close()


# ── inv export ──────────────────────────────────────────────────────────────


@inv_group.command("export")
@click.option("--format", "fmt", default="yaml", type=click.Choice(["yaml"]), help="Output format.")
@click.pass_context
def inv_export(ctx: click.Context, fmt: str) -> None:
    """Export the entire inventory to stdout."""
    session = ensure_db(ctx.obj["db_path"])
    try:
        items = session.exec(select(Item)).all()

        if not items:
            console.print("[dim]No items to export.[/dim]")
            return

        export_items = []
        for item in items:
            entry: dict = {
                "name": item.name,
                "slot": item.slot,
                "type": item.item_type,
            }
            if item.base:
                entry["base"] = item.base
            if item.ethereal:
                entry["ethereal"] = item.ethereal
            if item.socket_count:
                entry["sockets"] = item.socket_count
            if item.location:
                entry["location"] = item.location

            affixes = session.exec(
                select(Affix).where(Affix.item_id == item.id)
            ).all()
            if affixes:
                entry["affixes"] = {a.stat: a.value for a in affixes}

            sockets = session.exec(
                select(Socket).where(Socket.item_id == item.id).order_by(Socket.socket_index)
            ).all()
            fills = [s.filled_with for s in sockets if s.filled_with]
            if fills:
                entry["socket_fill"] = fills

            export_items.append(entry)

        output = yaml.dump({"items": export_items}, default_flow_style=False, sort_keys=False)
        click.echo(output)
    finally:
        session.close()


# ── inv add-rune ────────────────────────────────────────────────────────────


@inv_group.command("add-rune")
@click.argument("rune_type")
@click.option("--quantity", default=1, type=int, help="Number of runes to add.")
@click.pass_context
def inv_add_rune(ctx: click.Context, rune_type: str, quantity: int) -> None:
    """Add runes to the pool."""
    session = ensure_db(ctx.obj["db_path"])
    try:
        existing = session.exec(
            select(Rune).where(Rune.rune_type == rune_type)
        ).first()
        if existing:
            existing.quantity += quantity
            session.add(existing)
        else:
            session.add(Rune(rune_type=rune_type, quantity=quantity))
        session.commit()
        total = existing.quantity if existing else quantity
        console.print(
            f"[green]Added {quantity}x {rune_type} rune(s).[/green] "
            f"Total: {total}"
        )
    finally:
        session.close()


# ── inv add-gem ─────────────────────────────────────────────────────────────


@inv_group.command("add-gem")
@click.argument("gem_type")
@click.option("--grade", default="Perfect", help="Gem grade (for example Perfect).")
@click.option("--quantity", default=1, type=int, help="Number of gems to add.")
@click.pass_context
def inv_add_gem(
    ctx: click.Context,
    gem_type: str,
    grade: str,
    quantity: int,
) -> None:
    """Add gems to the pool."""
    session = ensure_db(ctx.obj["db_path"])
    try:
        name = f"{grade.strip()} {gem_type.strip()}".strip()
        existing = session.exec(
            select(Gem).where(Gem.name == name)
        ).first()
        if existing:
            existing.quantity += quantity
            session.add(existing)
        else:
            session.add(
                Gem(
                    name=name,
                    gem_type=gem_type.strip(),
                    grade=grade.strip(),
                    quantity=quantity,
                )
            )
        session.commit()
        total = existing.quantity if existing else quantity
        console.print(
            f"[green]Added {quantity}x {name} gem(s).[/green] "
            f"Total: {total}"
        )
    finally:
        session.close()


# ── inv add-jewel ───────────────────────────────────────────────────────────


@inv_group.command("add-jewel")
@click.option("--name", prompt="Jewel name", help="Display name / description.")
@click.option("--quality", default="magic", help="Quality (magic, rare, crafted).")
@click.option("--affix", multiple=True, help="Affix as stat=value (repeatable).")
@click.pass_context
def inv_add_jewel(
    ctx: click.Context,
    name: str,
    quality: str,
    affix: tuple[str, ...],
) -> None:
    """Add a jewel with affixes."""
    session = ensure_db(ctx.obj["db_path"])
    try:
        slug = _slugify(name)
        # Generate unique uid for jewels
        existing = session.exec(
            select(Jewel.uid).where(Jewel.uid.startswith(slug))
        ).all()
        if not existing:
            uid = f"{slug}_001"
        else:
            max_counter = 0
            for u in existing:
                match = re.search(r"_(\d+)$", u)
                if match:
                    max_counter = max(max_counter, int(match.group(1)))
            uid = f"{slug}_{max_counter + 1:03d}"

        jewel = Jewel(uid=uid, quality=quality, notes=name)
        session.add(jewel)
        session.flush()

        for affix_str in affix:
            if "=" not in affix_str:
                console.print(f"[red]Invalid affix format: {affix_str!r}[/red]")
                session.rollback()
                return
            stat, _, val_str = affix_str.partition("=")
            try:
                value = float(val_str)
            except ValueError:
                console.print(f"[red]Invalid affix value: {val_str!r}[/red]")
                session.rollback()
                return
            session.add(JewelAffix(jewel_id=jewel.id, stat=stat.strip(), value=value))

        session.commit()
        console.print(f"[green]Added jewel:[/green] {name} [cyan]({uid})[/cyan]")
    finally:
        session.close()
