"""CLI entry point for the D2R Gear Optimiser."""

import logging

import click

from d2r_optimiser import __version__


@click.group()
@click.option(
    "--db",
    default="stash.db",
    help="Path to SQLite database.",
    envvar="D2R_DB_PATH",
)
@click.option("--verbose", is_flag=True, help="Enable debug logging.")
@click.version_option(version=__version__)
@click.pass_context
def cli(ctx: click.Context, db: str, verbose: bool) -> None:
    """D2R Gear Optimiser — find the best loadout for your build."""
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db
    ctx.obj["verbose"] = verbose

    if verbose:
        logging.basicConfig(level=logging.DEBUG)
