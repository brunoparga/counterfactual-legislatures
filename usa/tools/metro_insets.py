#!/usr/bin/env python3
"""Metro areas worth magnifying, and the geometry to do it.

District size follows population, so a metro collapses into a knot of slivers
that is noise at national scale while the countryside is a handful of enormous
districts. The map shows those knots as a single grey block -- saying "not
readable here" rather than pretending a smear carries information -- and draws
each one properly in a panel placed in the empty ocean.

Spans are the width in degrees of longitude, chosen to contain the districts
of the metro rather than the built-up area: the point is to show every district
that is invisible on the main map, including the large one that reaches in from
outside.
"""

METROS = [
    # Chosen by measurement, not by naming the big cities: these are the
    # clusters of adjacent districts falling below the 25th percentile of
    # rendered area, i.e. the knots that are actually illegible at national
    # scale. Centres are the measured cluster centroids.
    #
    # A span is the box width in degrees of longitude. Too wide and the panel
    # fills with the countryside it was meant to escape; too narrow and the
    # large district reaching in from outside is clipped, which hides the fact
    # that it reaches in at all. New York and Los Angeles get more room
    # because they hold 20 and 17 districts -- at the standard size the inset
    # becomes a knot of its own.
    #
    # Held in reserve, 3 districts each, no room in the oceans for them:
    # Tampa, Atlanta, San Diego, Boston, Detroit.
    ("New York",        -73.85, 40.75, 3.1),   # 20 districts
    ("Los Angeles",    -118.13, 34.02, 3.2),   # 17
    ("Chicago",         -87.93, 41.89, 1.6),   #  9
    ("Miami",           -80.23, 26.36, 1.4),   #  6
    ("Washington",      -76.88, 39.10, 1.8),   #  5
    ("Philadelphia",    -75.07, 40.07, 1.5),   #  5
    ("San Francisco",  -122.26, 37.70, 1.6),   #  4
    ("Dallas",          -97.00, 32.85, 1.3),   #  4
    ("Houston",         -95.45, 29.80, 1.2),   #  4
]


def windows(lon0, lat0, shift, fwd, names=None):
    """[(name, (x0, x1, y0, y1))] in the projected degrees of a given panel."""
    out = []
    for name, lon, lat, span in METROS:
        if names and name not in names:
            continue
        half = span / 2.0
        # project the corners rather than the centre plus a span: the
        # projection is not uniform across the country, and a box specified in
        # degrees of longitude is narrower on the ground in Boston than Miami
        xs, ys = fwd([lon - half, lon + half, lon - half, lon + half],
                     [lat - half * 0.75, lat - half * 0.75,
                      lat + half * 0.75, lat + half * 0.75],
                     lon0, lat0, shift)
        out.append((name, (min(xs), max(xs), min(ys), max(ys))))
    return out
