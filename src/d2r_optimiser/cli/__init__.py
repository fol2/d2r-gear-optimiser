"""CLI package — register all command groups."""

from d2r_optimiser.cli.build import build_group
from d2r_optimiser.cli.inv import inv_group
from d2r_optimiser.cli.main import cli

cli.add_command(inv_group)
cli.add_command(build_group)

__all__ = ["cli"]
