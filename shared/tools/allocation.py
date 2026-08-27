#!/usr/bin/env python3
"""Turning populations and votes into whole seats.

Nothing here knows about any country. A divisor method takes a mapping of
unit -> population (or party -> votes) and a house size, and returns whole
seats; the units can be American states, Brazilian states, or parties on a
national list.

The rounding rule is the whole substance of these methods, and the choice
between them changes real legislatures: D'Hondt systematically favours large
parties over Sainte-Lague, and Huntington-Hill's geometric mean sits between
the two while guaranteeing every unit its floor of one seat.

House size is a separate question from allocation, and only some of the ways
of setting it are country-neutral. A fixed size is a bare number and belongs
with whoever chose it; the cube-root and smallest-unit rules are general and
live here.
"""

import math
from heapq import heappop, heappush


def huntington_hill(pops, size, floor=1):
    """Allocate `size` seats over {unit: population} by the method of equal
    proportions.

    Every unit gets `floor` seats first, then the rest go one at a time to
    whichever unit currently has the largest priority P / sqrt(n(n+1)).

    The floor is what makes this method distinct in practice rather than in
    theory: it is why Wyoming has a seat at all.
    """
    units = list(pops)
    need = floor * len(units)
    if size < need:
        raise ValueError(f"{size} seats cannot give {len(units)} units "
                         f"{floor} each")
    seats = {u: floor for u in units}

    heap = []
    for u in units:
        n = floor
        heappush(heap, (-pops[u] / math.sqrt(n * (n + 1)), u))
    for _ in range(size - need):
        _, u = heappop(heap)
        seats[u] += 1
        n = seats[u]
        heappush(heap, (-pops[u] / math.sqrt(n * (n + 1)), u))
    return seats


def divisor_method(votes, size, divisor, floor=0):
    """Generic highest-averages allocation.

    `divisor(n)` is the denominator applied to a unit already holding n seats:

        D'Hondt         n + 1
        Sainte-Lague    2n + 1
        modified S-L    0.7 if n == 0 else 2n + 1

    D'Hondt rounds down and so rewards large parties; Sainte-Lague rounds to
    nearest and is close to proportional. Which one a country picks is not a
    technicality -- it routinely moves several seats.
    """
    units = list(votes)
    need = floor * len(units)
    if size < need:
        raise ValueError(f"{size} seats cannot give {len(units)} units "
                         f"{floor} each")
    seats = {u: floor for u in units}
    heap = []
    for u in units:
        heappush(heap, (-votes[u] / divisor(seats[u]), u))
    for _ in range(size - need):
        _, u = heappop(heap)
        seats[u] += 1
        heappush(heap, (-votes[u] / divisor(seats[u]), u))
    return seats


def dhondt(votes, size, floor=0):
    return divisor_method(votes, size, lambda n: n + 1, floor)


def sainte_lague(votes, size, floor=0):
    return divisor_method(votes, size, lambda n: 2 * n + 1, floor)


def cube_root_size(pops):
    """House size as the cube root of the total population.

    A widely proposed rule of thumb, and roughly what most legislatures
    actually do -- the US House is the conspicuous exception, frozen at 435
    since 1929 while the population tripled.
    """
    return round(sum(pops.values()) ** (1 / 3))


def smallest_unit_size(pops):
    """House size such that a seat holds about as many people as the smallest
    unit does.

    Known in the US as the Wyoming rule, but the rule says "smallest state"
    and which state that is has changed before and will again -- so the name
    here describes the rule rather than the current answer.
    """
    return round(sum(pops.values()) / min(pops.values()))
