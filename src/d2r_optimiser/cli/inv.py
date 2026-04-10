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
from d2r_optimiser.core.models.rune import Jewel, JewelAffix, Rune

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
        slug = _slugify(name)
        uid = _next_uid(session, slug)

        item = Item(
            uid=uid,
            name=name,
            slot=slot,
            item_type=item_type,
            base=base,
            socket_count=sockets,
            location=location,
            ethereal=ethereal,
        )
        session.add(item)
        session.flush()  # get item.id

        # Parse and add affixes
        for affix_str in affix:
            if "=" not in affix_str:
                msg = f"[red]Invalid affix format: {affix_str!r} (expected stat=value)[/red]"
                console.print(msg)
                session.rollback()
                return
            stat, _, val_str = affix_str.partition("=")
            try:
                value = float(val_str)
            except ValueError:
                console.print(f"[red]Invalid affix value: {val_str!r} in {affix_str!r}[/red]")
                session.rollback()
                return
            session.add(Affix(item_id=item.id, stat=stat.strip(), value=value))

        # Create socket records
        for i in range(sockets):
            fill = socket_fill[i] if i < len(socket_fill) else None
            session.add(Socket(item_id=item.id, socket_index=i, filled_with=fill))

        session.commit()
        console.print(f"[green]Added:[/green] {item.name} [cyan]({uid})[/cyan]")
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
        for affix in session.exec(select(Affix).where(Affix.item_id == item.id)).all():
            session.delete(affix)
        for socket in session.exec(select(Socket).where(Socket.item_id == item.id)).all():
            session.delete(socket)
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
