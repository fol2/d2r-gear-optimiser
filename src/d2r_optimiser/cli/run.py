"""CLI command: optimise run — execute the gear optimiser for a build."""

from __future__ import annotations

import json as json_lib

import click
import pydantic
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from d2r_optimiser.core.orchestrator import (
    BuildNotFoundError,
    EmptyInventoryError,
    InvalidBuildModeError,
    optimise,
)
from d2r_optimiser.loader import LoaderError

console = Console(width=140)
_WEIGHT_ALIASES = {
    "damage": "damage",
    "mf": "magic_find",
    "magic_find": "magic_find",
    "ehp": "effective_hp",
    "effective_hp": "effective_hp",
    "bp": "breakpoint_score",
    "breakpoint": "breakpoint_score",
    "breakpoint_score": "breakpoint_score",
}


@click.command("run")
@click.argument("build_name")
@click.option(
    "--mode",
    type=str,
    default=None,
    help="Build-defined weight preset to use (for example starter, standard, or mf).",
)
@click.option(
    "--weight",
    "weight_values",
    multiple=True,
    help="Override a weight as key=value (repeatable).",
)
@click.option("--top-k", default=5, type=int, help="Number of top results to return.")
@click.option("--workers", default=None, type=int, help="Parallel workers (default: auto).")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON instead of a table.")
@click.option(
    "--progress/--no-progress",
    "show_progress",
    default=True,
    help="Show live search progress in interactive terminals.",
)
@click.pass_context
def run_cmd(
    ctx: click.Context,
    build_name: str,
    mode: str | None,
    weight_values: tuple[str, ...],
    top_k: int,
    workers: int | None,
    output_json: bool,
    show_progress: bool,
) -> None:
    """Run the gear optimiser for a build.

    Finds the top-K gear loadouts from your inventory that maximise the
    build's scoring formula while respecting all hard constraints.
    """
    db_path = ctx.obj["db_path"]
    try:
        weight_overrides = _parse_weight_overrides(weight_values)
    except ValueError as exc:
        console.print(f"[red]Invalid weight override:[/red] {exc}")
        ctx.exit(1)
        return

    try:
        results = _run_optimise(
            db_path=db_path,
            build_name=build_name,
            mode=mode,
            weight_overrides=weight_overrides or None,
            top_k=top_k,
            workers=workers,
            show_progress=show_progress and not output_json,
        )
    except BuildNotFoundError as exc:
        console.print(f"[red]Build not found:[/red] {exc}")
        ctx.exit(1)
        return
    except EmptyInventoryError as exc:
        console.print(f"[red]Empty inventory:[/red] {exc}")
        ctx.exit(1)
        return
    except InvalidBuildModeError as exc:
        console.print(f"[red]Invalid mode:[/red] {exc}")
        ctx.exit(1)
        return
    except (LoaderError, pydantic.ValidationError) as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        ctx.exit(1)
        return
    except ImportError as exc:
        console.print(f"[red]Formula module error:[/red] {exc}")
        ctx.exit(1)
        return

    if not results:
        console.print("[yellow]No valid loadouts found.[/yellow]")
        console.print(
            "[dim]Check that your inventory has items for all required slots "
            "and that hard constraints can be satisfied.[/dim]"
        )
        return

    if output_json:
        _output_json(results)
    else:
        _output_table(results)


def _parse_weight_overrides(weight_values: tuple[str, ...]) -> dict[str, float]:
    """Parse repeatable ``--weight key=value`` arguments."""
    overrides: dict[str, float] = {}
    for weight_str in weight_values:
        if "=" not in weight_str:
            msg = f"{weight_str!r} is missing '='"
            raise ValueError(msg)

        raw_key, _, raw_value = weight_str.partition("=")
        key = _WEIGHT_ALIASES.get(raw_key.strip().lower())
        if key is None:
            supported = ", ".join(sorted(_WEIGHT_ALIASES))
            msg = f"unsupported key {raw_key!r}; use one of: {supported}"
            raise ValueError(msg)

        try:
            overrides[key] = float(raw_value)
        except ValueError as exc:
            msg = f"{raw_value!r} is not a valid number for {raw_key!r}"
            raise ValueError(msg) from exc
    return overrides


def _run_optimise(
    *,
    db_path: str,
    build_name: str,
    mode: str | None,
    weight_overrides: dict[str, float] | None,
    top_k: int,
    workers: int | None,
    show_progress: bool,
) -> list[dict]:
    """Run the optimiser with optional live progress reporting."""
    if not (show_progress and console.is_terminal):
        return optimise(
            db_path=db_path,
            build_name=build_name,
            mode=mode,
            weight_overrides=weight_overrides,
            top_k=top_k,
            workers=workers,
        )

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TextColumn("{task.completed:,} evaluations"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task("Searching loadouts", total=None, completed=0)

        def _on_progress(evaluated: int) -> None:
            progress.update(task_id, completed=evaluated)

        return optimise(
            db_path=db_path,
            build_name=build_name,
            mode=mode,
            weight_overrides=weight_overrides,
            top_k=top_k,
            workers=workers,
            progress_callback=_on_progress,
        )


def _output_json(results: list[dict]) -> None:
    """Serialise results to JSON and print to stdout."""
    serialisable = []
    for r in results:
        entry = {
            "slots": r["slots"],
            "socket_fillings": r.get("socket_fillings", {}),
            "total_score": r["total_score"],
            "stats": r["stats"],
        }
        # ScoreBreakdown to dict
        score = r.get("score")
        if score and hasattr(score, "model_dump"):
            entry["score_breakdown"] = score.model_dump()
        elif score and hasattr(score, "__dict__"):
            entry["score_breakdown"] = {
                "damage": score.damage,
                "magic_find": score.magic_find,
                "effective_hp": score.effective_hp,
                "breakpoint_score": score.breakpoint_score,
            }
        serialisable.append(entry)

    click.echo(json_lib.dumps(serialisable, indent=2, default=str))


def _output_table(results: list[dict]) -> None:
    """Render results as a Rich table."""
    table = Table(title=f"Top {len(results)} Loadouts")
    table.add_column("Rank", justify="right", style="bold", width=4)
    table.add_column("Score", justify="right", style="green", width=7)
    table.add_column("Weapon", style="cyan", no_wrap=True)
    table.add_column("Shield", style="cyan", no_wrap=True)
    table.add_column("Helm", style="cyan", no_wrap=True)
    table.add_column("Body", style="cyan", no_wrap=True)
    table.add_column("Gloves", style="cyan", no_wrap=True)
    table.add_column("Belt", style="cyan", no_wrap=True)
    table.add_column("Boots", style="cyan", no_wrap=True)
    table.add_column("Amulet", style="cyan", no_wrap=True)
    table.add_column("Ring1", style="cyan", no_wrap=True)
    table.add_column("Ring2", style="cyan", no_wrap=True)
    table.add_column("MF", justify="right", width=5)
    table.add_column("FCR", justify="right", width=5)

    slot_cols = [
        "weapon", "shield", "helmet", "body", "gloves",
        "belt", "boots", "amulet", "ring1", "ring2",
    ]

    for rank, result in enumerate(results, 1):
        slots = result.get("slots", {})
        stats = result.get("stats", {})

        row = [
            str(rank),
            f"{result['total_score']:.3f}",
        ]
        for slot in slot_cols:
            uid = slots.get(slot, "-")
            # Truncate long uids for display
            if len(uid) > 20:
                uid = uid[:17] + "..."
            row.append(uid)

        row.append(f"{stats.get('mf', 0):.0f}")
        row.append(f"{stats.get('fcr', 0):.0f}")

        table.add_row(*row)

    console.print(table)

    # Print a summary of the best result's key stats
    best = results[0]
    stats = best.get("stats", {})
    summary_parts = []
    for stat_name, label in [
        ("mf", "MF"),
        ("fcr", "FCR"),
        ("all_skills", "+Skills"),
        ("resistance_all", "All Res"),
        ("ed", "ED%"),
    ]:
        val = stats.get(stat_name, 0)
        if val:
            summary_parts.append(f"{label}: {val:g}")

    if summary_parts:
        console.print(f"\n[bold]Best loadout stats:[/bold] {' | '.join(summary_parts)}")

    # Print score breakdown
    score = best.get("score")
    if score:
        console.print(
            f"[dim]Score breakdown: "
            f"Damage={score.damage:.3f} "
            f"MF={score.magic_find:.3f} "
            f"EHP={score.effective_hp:.3f} "
            f"BP={score.breakpoint_score:.3f}[/dim]"
        )
