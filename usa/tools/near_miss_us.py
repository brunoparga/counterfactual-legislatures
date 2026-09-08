#!/usr/bin/env python3
"""Which House votes were close enough that the districting could decide them?

The counterfactual moves 22 seats at most, and a bill passed 380-40 does not
care how the lines were drawn. So the screen comes first and only what
survives it is worth a Monte Carlo. This is the US analogue of
brazil/tools/near_miss.py, and it differs from it in one structural way that
runs through everything downstream:

  Brazil   the apportionment changes how many seats a state has
  US       apportionment is fixed; the districting changes only *which*
           districts, so a state's delegation size never moves

TWO BARS

  ordinary            a simple majority of those voting, so a vote is close
                      when yea - nay is small
  suspension of the   two thirds of those voting. A suspension motion carried
  rules, veto         290-140 fails, and treating it as a 150-vote win would
  override            put dozens of comfortable losses in the candidate set

Distance is therefore measured from the bar that actually applied, not from
the other side's total.

PARTY-DIVIDED, OR IT DOES NOT RESPOND

A vote where both parties split evenly does not move when the party
composition changes, however close it was. The second screen is on the gap
between the two parties' yea shares: below 50 points the roll call is not a
party-line vote and its outcome is not a function of the seat count.

THE PRESIDENT IS IN THE VOTES FILE

Voteview records presidential position-taking as cast votes on House roll
calls -- 574 of the 5,679 here. Counting them shifts a tally by one and it is
silent, because it looks exactly like a member. Only members whose row in the
members file says chamber House are counted, which is what makes the
recomputed yea/nay reproduce Voteview's published counts on every roll call.
"""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM = ROOT / "upstream" / "voteview"

STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI "
             "MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT "
             "VT VA WA WV WI WY".split())
PARTY = {100: "D", 200: "R"}      # everyone else votes but cannot be converted
# Voteview cast codes: 1-3 yea, 4-6 nay, 7-8 present, 9 absent, 0 not a member.
YEA, NAY, OTHER = 1, 2, 0
TWO_THIRDS_RE = re.compile(
    r"suspend the rules|objections of the president|overriding the veto", re.I)

# Published composition at the start of each congress, for the gate. The 116th
# is 235 D / 199 R with NC-9 vacant until a September 2019 special election
# filled it for the Republicans, so counting the whole congress gives 200 R.
PUBLISHED = {113: (201, 234), 114: (188, 247), 115: (194, 241),
             116: (235, 200), 117: (222, 213)}


def I(x):
    """Voteview writes some integer columns as floats. '10713.0' -> 10713."""
    return int(float(x))


def load(votes, rollcalls, members, congresses):
    """(rolls, member_index) for the requested congresses.

    member_index[c] is the list of that congress's House members as
    (icpsr, state, party); a roll call's positions are a bytearray parallel to
    it, so the whole five-congress position matrix is under three megabytes and
    the per-state slices the reweighting needs are a plain index lookup.
    """
    lo, hi = min(congresses), max(congresses)
    idx, meta = {}, defaultdict(list)
    for r in csv.DictReader(open(members, newline="")):
        c = I(r["congress"])
        if r["chamber"] != "House" or not lo <= c <= hi:
            continue
        party = PARTY.get(I(r["party_code"]))
        st = r["state_abbrev"]
        idx[(c, I(r["icpsr"]))] = len(meta[c])
        meta[c].append((I(r["icpsr"]), st, party if st in STATES else None,
                        I(r["district_code"])))

    rolls = {}
    for r in csv.DictReader(open(rollcalls, newline="")):
        c = I(r["congress"])
        if r["chamber"] != "House" or not lo <= c <= hi:
            continue
        rolls[(c, I(r["rollnumber"]))] = {
            "congress": c, "rollnumber": I(r["rollnumber"]), "date": r["date"],
            "bill": r["bill_number"], "question": r["vote_question"],
            "result": r["vote_result"], "desc": (r["vote_desc"] or "")[:300],
            "published_yea": I(r["yea_count"]), "published_nay": I(r["nay_count"]),
            "pos": bytearray(len(meta[c]))}

    with open(votes, newline="") as f:
        rd = csv.reader(f)
        next(rd)
        for c, ch, rn, ic, cc, _p in rd:
            if ch != "House":
                continue
            c = I(c)
            if not lo <= c <= hi:
                continue
            k = idx.get((c, I(ic)))
            if k is None:                      # the President, or a delegate
                continue
            row = rolls.get((c, I(rn)))
            if row is None:
                continue
            v = I(cc)
            row["pos"][k] = YEA if 1 <= v <= 3 else NAY if 4 <= v <= 6 else OTHER
    return rolls, meta


def tally(row, meta_c):
    """yea/nay overall and by party."""
    by = {"D": [0, 0], "R": [0, 0]}
    yea = nay = 0
    for k, v in enumerate(row["pos"]):
        if v not in (YEA, NAY):
            continue
        side = 0 if v == YEA else 1
        yea, nay = (yea + 1, nay) if side == 0 else (yea, nay + 1)
        p = meta_c[k][2]
        if p:
            by[p][side] += 1
    return yea, nay, by


def bar(row, yea, nay):
    """(name, votes needed) for the threshold this roll call actually faced."""
    t = yea + nay
    if TWO_THIRDS_RE.search(row["question"] or ""):
        return "two thirds", -(-2 * t // 3)
    return "simple majority", t // 2 + 1


def composition(meta_c, rolls_c):
    """Seats by party, taking the first member to vote in each seat.

    A congress has more members than seats -- resignations, deaths, special
    elections -- so counting rows overstates both parties. The seat is
    attributed to whoever held it first, which is the published
    start-of-congress composition.
    """
    first = {}
    for (c, rn), row in sorted(rolls_c.items(), key=lambda kv: kv[0][1]):
        for k, v in enumerate(row["pos"]):
            if v and k not in first:
                first[k] = rn
    seats = {}
    for k, (icpsr, st, party, dist) in enumerate(meta_c):
        if party is None:
            continue
        seat = (st, dist)
        rn = first.get(k, 10 ** 9)
        if seat not in seats or rn < seats[seat][1]:
            seats[seat] = (party, rn)
    out = {"D": 0, "R": 0}
    for party, _ in seats.values():
        out[party] += 1
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--votes", default=str(UPSTREAM / "HSall_votes.csv"))
    ap.add_argument("--rollcalls", default=str(UPSTREAM / "HSall_rollcalls.csv"))
    ap.add_argument("--members", default=str(UPSTREAM / "HSall_members.csv"))
    ap.add_argument("--congresses", nargs=2, type=int, default=[113, 117])
    ap.add_argument("--cut", type=int, default=25,
                    help="distance from the bar to call a vote a candidate")
    ap.add_argument("--divide", type=float, default=50.0,
                    help="minimum gap in points between the parties' yea shares")
    ap.add_argument("--out", default=str(ROOT / "results" / "near_miss.json"))
    a = ap.parse_args()

    cs = list(range(a.congresses[0], a.congresses[1] + 1))
    rolls, meta = load(a.votes, a.rollcalls, a.members, cs)
    print(f"{len(rolls):,} House roll calls, congresses {cs[0]}-{cs[-1]}\n")

    # GATE 1: the recomputed tallies must equal Voteview's published counts.
    off = 0
    recs = []
    for (c, rn), row in sorted(rolls.items()):
        yea, nay, by = tally(row, meta[c])
        if yea != row["published_yea"] or nay != row["published_nay"]:
            off += 1
            continue
        name, need = bar(row, yea, nay)
        ds = by["D"][0] / (by["D"][0] + by["D"][1]) * 100 if sum(by["D"]) else 0.0
        rs = by["R"][0] / (by["R"][0] + by["R"][1]) * 100 if sum(by["R"]) else 0.0
        recs.append({"congress": c, "rollnumber": rn, "date": row["date"],
                     "bill": row["bill"], "question": row["question"],
                     "result": row["result"], "desc": row["desc"],
                     "bar": name, "needed": need, "yea": yea, "nay": nay,
                     "passed": yea >= need, "distance": yea - need,
                     "dem_yea": by["D"][0], "dem_nay": by["D"][1],
                     "rep_yea": by["R"][0], "rep_nay": by["R"][1],
                     "dem_yea_pct": round(ds, 1), "rep_yea_pct": round(rs, 1),
                     "party_gap": round(abs(ds - rs), 1)})
    print(f"GATE 1  recomputed yea/nay vs Voteview's published counts: "
          f"{off} mismatches of {len(rolls):,}")
    if off:
        print("        STOP -- the vote join is wrong")
        return 1

    # GATE 2: seats by party must match the published composition.
    comp, bad = {}, []
    for c in cs:
        rc = {k: v for k, v in rolls.items() if k[0] == c}
        got = composition(meta[c], rc)
        comp[c] = got
        want = PUBLISHED.get(c)
        ok = want is None or (got["D"], got["R"]) == want
        bad += [] if ok else [c]
        print(f"GATE 2  {c}th: {got['D']} D / {got['R']} R" +
              (f"   published {want[0]} D / {want[1]} R   "
               f"{'OK' if ok else 'MISMATCH'}" if want else ""))
    if bad:
        print(f"        STOP -- composition wrong for {bad}")
        return 1

    close = [r for r in recs if abs(r["distance"]) <= a.cut]
    divided = [r for r in recs if r["party_gap"] > a.divide]
    cand = [r for r in recs
            if abs(r["distance"]) <= a.cut and r["party_gap"] > a.divide]
    print(f"\n{'|distance from bar|':22}{'all':>9}{'party-divided':>15}")
    for lo, hi, lab in ((0, 5, "0-5"), (6, 10, "6-10"), (11, 25, "11-25"),
                        (26, 50, "26-50"), (51, 10 ** 6, "51+")):
        n = sum(1 for r in recs if lo <= abs(r["distance"]) <= hi)
        d = sum(1 for r in recs
                if lo <= abs(r["distance"]) <= hi and r["party_gap"] > a.divide)
        print(f"{lab:22}{n:9,}{d:15,}")
    print(f"\nwithin {a.cut} of the bar: {len(close):,}")
    print(f"party-divided by more than {a.divide:.0f} points: {len(divided):,}")
    print(f"both -- the candidate set: {len(cand):,}")
    two = sum(1 for r in cand if r["bar"] == "two thirds")
    print(f"  of which two-thirds bar: {two:,}")
    by_c = defaultdict(int)
    for r in cand:
        by_c[r["congress"]] += 1
    print("  by congress: " + ", ".join(f"{k}: {v}" for k, v in sorted(by_c.items())))

    cand.sort(key=lambda r: (abs(r["distance"]), r["congress"], r["rollnumber"]))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(
        {"congresses": cs, "cut": a.cut, "party_gap_min": a.divide,
         "roll_calls_screened": len(recs),
         "composition": {str(k): v for k, v in comp.items()},
         "candidates": cand}, indent=1))
    print(f"\nclosest, most party-divided:")
    for r in cand[:12]:
        print(f"  {r['date']}  {r['congress']}-{r['rollnumber']:<4} "
              f"{r['yea']:3}-{r['nay']:3} need {r['needed']:3} "
              f"({r['distance']:+3})  gap {r['party_gap']:5.1f}  "
              f"{(r['bill'] or ''):10} {r['desc'][:60]}")
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
