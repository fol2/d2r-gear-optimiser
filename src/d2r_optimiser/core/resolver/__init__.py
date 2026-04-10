"""Resource resolver — expand inventory into candidate equipment combinations."""

from d2r_optimiser.core.resolver.runewords import enumerate_craftable_runewords
from d2r_optimiser.core.resolver.sockets import enumerate_socket_options

__all__ = ["enumerate_craftable_runewords", "enumerate_socket_options"]
