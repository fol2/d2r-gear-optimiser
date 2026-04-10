"""CLI commands: optimise validate — record measurements and check deviations."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from d2r_optimiser.cli._db_helpers import ensure_db
from d2r_optimiser.core.validation import check_all_validations, record_live_measurement

console = Console(width=120)


@click.group("validate")
@click.pass_context
def validate_group(ctx: click.Context) -> None:
    """Validate formula predictions against live measurements."""


@validate_group.command("record")
@click.argument("gear_set_id")
@click.option("--build", "build_name", default="unknown", help="Build definition name.")
@click.option("--actual-damage", type=float, default=None, help="Measured damage value.")
@click.option("--actual-mf", type=float, default=None, help="Measured magic find value.")
@click.option("--actual-hp", type=float, default=None, help="Measured HP value.")
@click.option("--actual-fcr", type=float, default=None, help="Measured FCR value.")
@click.option(
    "--predicted-damage", type=float, default=None, help="Predicted damage from formula."
)
@click.option("--predicted-mf", type=float, default=None, help="Predicted MF from formula.")
@click.option("--predicted-hp", type=float, default=None, help="Predicted HP from formula.")
@click.option("--predicted-fcr", type=float, default=None, help="Predicted FCR from formula.")
@click.option("--notes", default="", help="Free-text notes about this measurement.")
@click.pass_context
def record_cmd(
    ctx: click.Context,
    gear_set_id: str,
    build_name: str,
    actual_damage: float | None,
    actual_mf: float | None,
    actual_hp: float | None,
    actual_fcr: float | None,
    predicted_damage: float | None,
    predicted_mf: float | None,
    predicted_hp: float | None,
    predicted_fcr: float | None,
    notes: str,
) -> None:
    """Record live in-game measurement for formula calibration."""
    session = ensure_db(ctx.obj["db_path"])
    try:
        predicted: dict[str, float] = {}
        actual: dict[str, float] = {}

        if predicted_damage is not None:
            predicted["damage"] = predicted_damage
        if predicted_mf is not None:
            predicted["mf"] = predicted_mf
        if predicted_hp is not None:
            predicted["hp"] = predicted_hp
        if predicted_fcr is not None:
            predicted["fcr"] = predicted_fcr

        if actual_damage is not None:
            actual["damage"] = actual_damage
        if actual_mf is not None:
            actual["mf"] = actual_mf
        if actual_hp is not None:
            actual["hp"] = actual_hp
        if actual_fcr is not None:
            actual["fcr"] = actual_fcr

        record = record_live_measurement(
            session=session,
            gear_set_id=gear_set_id,
            build_def=build_name,
            predicted=predicted,
            actual=actual,
            notes=notes,
        )
        console.print(
            f"[green]Recorded:[/green] gear_set={gear_set_id}  "
            f"max_deviation={record.deviation_max:.1f}%"
        )
    finally:
        session.close()


@validate_group.command("check")
@click.option("--build", "build_name", default=None, help="Filter by build name.")
@click.pass_context
def check_cmd(ctx: click.Context, build_name: str | None) -> None:
    """Run all validation checks and show deviation report."""
    session = ensure_db(ctx.obj["db_path"])
    try:
        records = check_all_validations(session, build_def=build_name)

        if not records:
            console.print("[dim]No validation records found.[/dim]")
            return

        table = Table(title="Validation Report")
        table.add_column("ID", justify="right", width=4)
        table.add_column("Gear Set", style="cyan")
        table.add_column("Build")
        table.add_column("Pred DMG", justify="right")
        table.add_column("Act DMG", justify="right")
        table.add_column("Pred MF", justify="right")
        table.add_column("Act MF", justify="right")
        table.add_column("Pred HP", justify="right")
        table.add_column("Act HP", justify="right")
        table.add_column("Max Dev%", justify="right")
        table.add_column("Status", justify="center")

        for rec in records:
            dev = rec.get("deviation_max", 0.0) or 0.0

            # Colour code by deviation severity
            if dev < 5.0:
                style = "green"
                status = "PASS"
            elif dev < 10.0:
                style = "yellow"
                status = "WARN"
            else:
                style = "red"
                status = "FAIL"

            def _fmt(val):
                return f"{val:.1f}" if val is not None else "-"

            table.add_row(
                str(rec.get("id", "")),
                rec.get("gear_set_id", ""),
                rec.get("build_def", ""),
                _fmt(rec.get("predicted_damage")),
                _fmt(rec.get("actual_damage")),
                _fmt(rec.get("predicted_mf")),
                _fmt(rec.get("actual_mf")),
                _fmt(rec.get("predicted_hp")),
                _fmt(rec.get("actual_hp")),
                f"[{style}]{dev:.1f}%[/{style}]",
                f"[{style}]{status}[/{style}]",
            )

        console.print(table)

        # Summary
        pass_count = sum(1 for r in records if r.get("pass", False))
        total = len(records)
        console.print(
            f"\n[bold]{pass_count}/{total}[/bold] records within 5% tolerance."
        )
    finally:
        session.close()
