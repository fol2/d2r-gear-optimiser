"""Build definition CLI commands."""

from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from d2r_optimiser.loader import LoaderError, list_builds, load_build

console = Console(width=120)

# Resolve the data/builds/ directory relative to the project root.
# Walk up from this file: cli/build.py -> cli -> d2r_optimiser -> src -> project root
_PACKAGE_DIR = Path(__file__).resolve().parent.parent.parent.parent
_BUILDS_DIR = _PACKAGE_DIR / "data" / "builds"


@click.group("build")
@click.pass_context
def build_group(ctx: click.Context) -> None:
    """Browse and inspect build definitions."""


@build_group.command("list")
@click.pass_context
def build_list(ctx: click.Context) -> None:
    """Show available build definitions."""
    builds_dir = _BUILDS_DIR
    if not builds_dir.exists():
        console.print(f"[red]Builds directory not found:[/red] {builds_dir}")
        ctx.exit(1)
        return

    try:
        names = list_builds(builds_dir)
    except (FileNotFoundError, LoaderError) as exc:
        console.print(f"[red]Error listing builds:[/red] {exc}")
        ctx.exit(1)
        return

    if not names:
        console.print("[dim]No build definitions found.[/dim]")
        return

    table = Table(title="Available Builds")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Class")
    table.add_column("Description")

    for name in names:
        yaml_path = builds_dir / f"{name}.yaml"
        try:
            build = load_build(yaml_path)
            desc = build.description.strip()
            # Truncate long descriptions
            if len(desc) > 80:
                desc = desc[:77] + "..."
            table.add_row(name, build.character_class, desc)
        except Exception:
            table.add_row(name, "?", "[dim]Error loading[/dim]")

    console.print(table)


@build_group.command("show")
@click.argument("name")
@click.pass_context
def build_show(ctx: click.Context, name: str) -> None:
    """Show full details for a build definition."""
    builds_dir = _BUILDS_DIR
    yaml_path = builds_dir / f"{name}.yaml"

    if not yaml_path.exists():
        console.print(f"[red]Build not found:[/red] {name}")
        console.print(f"[dim]Expected at: {yaml_path}[/dim]")
        ctx.exit(1)
        return

    try:
        build = load_build(yaml_path)
    except Exception as exc:
        console.print(f"[red]Error loading build:[/red] {exc}")
        ctx.exit(1)
        return

    # Header panel
    header = Text()
    header.append(f"{build.display_name}\n", style="bold")
    header.append(f"Class: {build.character_class}\n")
    header.append(f"Formula module: {build.formula_module}\n\n")
    header.append(build.description.strip())
    console.print(Panel(header, title=f"[bold]{name}[/bold]", border_style="blue"))

    # Skill points
    skill_table = Table(title="Skill Points")
    skill_table.add_column("Skill", style="cyan")
    skill_table.add_column("Points", justify="right")
    for skill, points in build.skill_points.items():
        skill_table.add_row(skill, str(points))
    console.print(skill_table)

    # Objectives
    obj = build.objectives
    obj_table = Table(title="Default Objectives")
    obj_table.add_column("Dimension", style="cyan")
    obj_table.add_column("Weight", justify="right")
    obj_table.add_row("Damage", f"{obj.damage:.2f}")
    obj_table.add_row("Magic Find", f"{obj.magic_find:.2f}")
    obj_table.add_row("Effective HP", f"{obj.effective_hp:.2f}")
    obj_table.add_row("Breakpoint Score", f"{obj.breakpoint_score:.2f}")
    console.print(obj_table)

    # Constraints
    if build.constraints:
        con_table = Table(title="Hard Constraints")
        con_table.add_column("Stat", style="cyan")
        con_table.add_column("Operator")
        con_table.add_column("Value", justify="right")
        for c in build.constraints:
            con_table.add_row(c.stat, c.operator, f"{c.value:g}")
        console.print(con_table)

    # Presets
    if build.presets:
        preset_table = Table(title="Weight Presets")
        preset_table.add_column("Preset", style="cyan")
        preset_table.add_column("Damage", justify="right")
        preset_table.add_column("MF", justify="right")
        preset_table.add_column("EHP", justify="right")
        preset_table.add_column("BP", justify="right")
        for pname, weights in build.presets.items():
            preset_table.add_row(
                pname,
                f"{weights.damage:.2f}",
                f"{weights.magic_find:.2f}",
                f"{weights.effective_hp:.2f}",
                f"{weights.breakpoint_score:.2f}",
            )
        console.print(preset_table)
