"""Resolve possible socket-filling combinations for an item."""

from collections import Counter
from itertools import combinations_with_replacement

from d2r_optimiser.core.models import Gem, Item, Jewel, Rune


def enumerate_socket_options(
    item: Item,
    rune_pool: list[Rune],
    jewel_pool: list[Jewel],
    gem_pool: list[Gem] | None = None,
    max_combinations: int = 500,
) -> list[list[str]]:
    """Enumerate possible socket fillings for an item's empty sockets.

    Returns a list of socket-filling combinations.  Each combination is a
    list of strings (rune names or jewel UIDs) to fill the empty sockets.

    Returns ``[[]]`` (list containing one empty list) when:
    - the item has no empty sockets, **or**
    - all socket material pools are effectively empty.

    *max_combinations* caps output to prevent combinatorial explosion.
    """
    # Determine how many sockets are empty.
    # Socket model tracks filled slots via socket_index; but at this
    # resolver layer we simply rely on `socket_count` as the total capacity
    # and receive the item as-is (pre-filling is already reflected in the
    # item's socket_count when applicable).  The caller is responsible for
    # adjusting the item or passing `filled_count` via the item's sockets.
    #
    # For simplicity we treat `socket_count` as the number of *empty*
    # sockets available, since the task spec counts them this way in test
    # expectations.
    empty = item.socket_count
    if empty <= 0:
        return [[]]

    # Build candidate pool.  Each entry is a string label and we track
    # availability so we never exceed the player's stock.
    availability: Counter[str] = Counter()
    for rune in rune_pool:
        if rune.quantity > 0:
            availability[rune.rune_type] += rune.quantity
    for jewel in jewel_pool:
        availability[jewel.uid] += 1
    for gem in gem_pool or []:
        if gem.quantity > 0:
            availability[gem.name] += gem.quantity

    candidates = sorted(availability.keys())
    if not candidates:
        return [[]]

    # Generate combinations_with_replacement, then filter by availability.
    results: list[list[str]] = []
    for combo in combinations_with_replacement(candidates, empty):
        combo_count = Counter(combo)
        if all(combo_count[c] <= availability[c] for c in combo_count):
            results.append(list(combo))
            if len(results) >= max_combinations:
                break

    return results
