#!/usr/bin/env python3
"""House apportionment by state for the 2000, 2010 and 2020 censuses.

Stored as a 2000 base plus the per-cycle changes, because the changes are what
anyone actually remembers or can check against a news report. The totals are
asserted at import, so a typo in a delta fails loudly rather than quietly
producing a map with the wrong number of districts.

The 50 states, DC and Puerto Rico. All carry zero seats except the states.

DC and PR are here for different reasons and neither is apportioned: DC
because its territory sits inside the lower-48 hull, so the nationwide map has
to know about it; PR because the counterfactual apportionments include
variants where it is seated, and those need its map drawn. The other
territories -- Guam, the US Virgin Islands, American Samoa, the Northern
Marianas -- are not here, because no output path reaches them.
"""

HOUSE_SIZE = 435

# Apportionment following the 2000 census, as used by the original autodistrict
# run_dir/gen_images script.
BASE_2000 = {
    "AL": 7, "AK": 1, "AZ": 8, "AR": 4, "CA": 53, "CO": 7, "CT": 5, "DE": 1,
    "DC": 0, "FL": 25, "GA": 13, "HI": 2, "ID": 2, "IL": 19, "IN": 9, "IA": 5,
    "KS": 4, "KY": 6, "LA": 7, "ME": 2, "MD": 8, "MA": 10, "MI": 15, "MN": 8,
    "MS": 4, "MO": 9, "MT": 1, "NE": 3, "NV": 3, "NH": 2, "NJ": 13, "NM": 3,
    "NY": 29, "NC": 13, "ND": 1, "OH": 18, "OK": 5, "OR": 5, "PA": 19, "RI": 2,
    "SC": 6, "SD": 1, "TN": 9, "TX": 32, "UT": 3, "VT": 1, "VA": 11, "WA": 9,
    "WV": 3, "WI": 8, "WY": 1, "PR": 0,
}

# 2010 relative to 2000.
DELTA_2010 = {
    "TX": +4, "FL": +2,
    "WA": +1, "NV": +1, "UT": +1, "AZ": +1, "GA": +1, "SC": +1,
    "NY": -2, "OH": -2,
    "MA": -1, "NJ": -1, "PA": -1, "MI": -1, "IL": -1, "IA": -1, "MO": -1,
    "LA": -1,
}

# 2020 relative to 2010.
DELTA_2020 = {
    "TX": +2,
    "OR": +1, "MT": +1, "CO": +1, "FL": +1, "NC": +1,
    "NY": -1, "PA": -1, "WV": -1, "OH": -1, "MI": -1, "IL": -1, "CA": -1,
}

FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08",
    "CT": "09", "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15",
    "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56", "PR": "72",
}

NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida",
    "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico",
}

# Not on the contiguous map: the two detached states, and PR, which is neither
# contiguous nor a state. DC *is* in the lower 48 geographically, so the
# nationwide map has to deal with it; see contiguous() and national_seats().
NON_CONTIGUOUS = {"AK", "HI", "PR"}


def _apply(base, delta):
    out = dict(base)
    for st, d in delta.items():
        out[st] += d
    return out


SEATS = {
    2000: BASE_2000,
    2010: _apply(BASE_2000, DELTA_2010),
    2020: _apply(_apply(BASE_2000, DELTA_2010), DELTA_2020),
}

for _year, _tab in SEATS.items():
    _total = sum(_tab.values())
    assert _total == HOUSE_SIZE, f"{_year} apportionment sums to {_total}, not {HOUSE_SIZE}"
    assert all(v >= 0 for v in _tab.values()), f"{_year} has a negative seat count"
for _d in (DELTA_2010, DELTA_2020):
    assert sum(_d.values()) == 0, "apportionment deltas must be zero-sum"


def seats(year, state):
    """Seats for one state in a given census year."""
    return SEATS[year][state.upper()]


def mapped_states(year):
    """States that get their own state-by-state map, in FIPS order.

    Anything with no seats gets no map: there is nothing to split. That drops
    DC and leaves the 50 states.
    """
    return sorted(
        (st for st in SEATS[year] if SEATS[year][st] > 0),
        key=lambda s: FIPS[s],
    )


def contiguous(year):
    """Areas drawn on the nationwide all-in-one-go map, in FIPS order.

    DC appears here and only here. Its territory sits inside the lower-48 hull,
    so omitting its outline would punch a hole in the map -- but it has no
    seats, so its population is zeroed. It is drawn, not represented.
    """
    return sorted(
        (st for st in SEATS[year] if st not in NON_CONTIGUOUS),
        key=lambda s: FIPS[s],
    )


def national_seats(year, dc_seat=False):
    """Districts for the all-48-in-one-go map.

    The detached states keep their own apportionment and are drawn separately,
    so the contiguous map gets whatever is left: 435 - AK - HI = 432. DC is
    drawn but contributes no seats and no population, matching its real lack of
    House representation.

    dc_seat=True is the counterfactual: DC's population is included and the map
    gets one more district for it. Since a national splitline map ignores state
    lines entirely, the only thing that changes is the population field and the
    district count -- but that is enough to move every cut downstream of DC.

    The +1 here is the rough version: DC's population is close to one quota, so
    it earns about one seat. Deciding whether the House stays at 435 (some
    state losing a seat) or grows to 436 is a Huntington-Hill question, and the
    main repo already has an implementation to answer it properly.
    """
    total = HOUSE_SIZE - seats(year, "AK") - seats(year, "HI") - seats(year, "DC")
    return total + 1 if dc_seat else total


def _main():
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("year", type=int, choices=sorted(SEATS), nargs="?", default=2020)
    ap.add_argument("--changes", action="store_true", help="show change from the previous cycle")
    args = ap.parse_args()

    tab = SEATS[args.year]
    prev = {2010: SEATS[2000], 2020: SEATS[2010]}.get(args.year)

    for st in sorted(tab, key=lambda s: (-tab[s], s)):
        line = f"{st}  {FIPS[st]}  {tab[st]:3d}  {NAMES[st]}"
        if args.changes and prev:
            d = tab[st] - prev[st]
            if d:
                line += f"   ({d:+d})"
        print(line)
    drawn = contiguous(args.year)
    print(f"\ntotal {sum(tab.values())}")
    print(f"contiguous map ({len(drawn) - 1} states + DC): "
          f"{national_seats(args.year)} seats "
          f"({national_seats(args.year, dc_seat=True)} in the DC-seat counterfactual)")


if __name__ == "__main__":
    _main()
