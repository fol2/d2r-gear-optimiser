"""Search engine — exhaustive gear optimisation with hard-constraint pruning."""

from d2r_optimiser.core.search.engine import search
from d2r_optimiser.core.search.parallel import parallel_search

__all__ = ["search", "parallel_search"]
