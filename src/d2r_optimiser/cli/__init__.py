"""CLI package — register all command groups."""

from d2r_optimiser.cli.build import build_group
from d2r_optimiser.cli.inv import inv_group
from d2r_optimiser.cli.main import cli
from d2r_optimiser.cli.run import run_cmd
from d2r_optimiser.cli.validate import validate_group

cli.add_command(inv_group)
cli.add_command(build_group)
cli.add_command(run_cmd)
cli.add_command(validate_group)

__all__ = ["cli"]
