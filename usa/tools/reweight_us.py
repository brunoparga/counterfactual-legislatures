#!/usr/bin/env python3
"""How likely was a close House vote to go the other way under splitline?

THE US MODEL IS NOT BRAZIL'S, AND THE DIFFERENCE IS THE WHOLE POINT

In Brazil the counterfactual changes how many seats a state has, so a
delegation is resized and the chamber's composition follows. In the US the
apportionment is untouched: splitline redraws districts *within* a state, and
the state sends exactly as many members either way. What changes is which
party wins them.

So each state's delegation is resampled at constant size. Where splitline
gives Democrats k more districts than the enacted map did, k Republicans are
drawn out of that state's delegation and k members are drawn in from that
state's observed Democrats -- their votes, their absences, their defections.
Nothing else moves.

231 IS NOT A SEAT COUNT

The 231-vs-209 figures are districts carried by the Democratic presidential
candidate, and the real 2012 House was 201 D. Reading 231 as a seat count
would silently import an eight-seat gap between "the district leans D" and
"the D candidate wins it" into every roll call. What is transferable is the
*difference*, +22, so the difference is what is applied to the delegation that
actually sat.

Each congress is paired with the presidential election it most recently
followed: the 113th and 114th with 2012, the 115th and 116th with 2016, the
117th with 2020.

DRAWING THE REPLACEMENTS

  leaving   a multivariate hypergeometric draw over the losing party's
            observed yea / nay / absent counts in that state -- who leaves is
            not independent of how many voted each way
  arriving  a multinomial draw over the receiving party's observed positions
            in the same state, absences included. A new member is as capable
            of missing the vote as the ones we can see; treating every
            arrival as a voter would inflate the winning side on every roll
            call, and for a majority bar that is exactly the wrong direction.

Where a state has no observed members of the receiving party -- Arkansas has
no Democrats to draw from and splitline gives it one -- the draw falls back to
that party's national distribution for that roll call, and the number of times
that happens is reported rather than buried.

WHY IT IS HONEST WHEN NOTHING MOVES

With an all-zero delta vector no state is resampled and the model returns the
true tally with zero variance. That is checked, not asserted: --gate runs it
and stops if any roll call's reconstructed tally differs from the recorded one.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from near_miss_us import STATES, YEA, NAY, load  # noqa: E402

# Each congress takes the delta from the presidential election it followed.
PAIRING = {113: "E_12_PRES", 114: "E_12_PRES", 115: "E_16_PRES",
           116: "E_16_PRES", 117: "E_20_PRES"}


def deltas(results, contest):
    """{state: splitline D districts - enacted D districts} for one contest."""
    def won(plan):
        c = Counter()
        for r in json.loads((results / f"{plan}__{contest}.json").read_text())["districts"]:
            c[r["state"]] += r["winner"] == "D"
        return c
    e, s = won("enacted_cd113"), won("splitline_2010")
    return {st: s[st] - e[st] for st in set(e) | set(s)}


def counts(pos, members):
    """(yea, nay, other) per party and per state, for one roll call."""
    out = defaultdict(lambda: np.zeros(3, dtype=np.int64))
    for k, v in enumerate(pos):
        _ic, st, party, _d = members[k]
        col = 0 if v == YEA else 1 if v == NAY else 2
        out[("all", None)][col] += 1
        if party is None:
            out[("fixed", None)][col] += 1
        else:
            out[(st, party)][col] += 1
            out[("nat", party)][col] += 1
    return out


def resample(rng, c, delta, reps, national):
    """(yea, nay) arrays for one state after converting `delta` members.

    Returns the state's own contribution, so the caller adds it to the members
    the counterfactual does not touch.
    """
    gain, lose = ("D", "R") if delta > 0 else ("R", "D")
    k = abs(delta)
    stay_g, stay_l = c[gain].copy(), c[lose].copy()
    n_l = int(stay_l.sum())
    k = min(k, n_l)                       # cannot convert more than exist
    fallback = False
    if k == 0:
        tot = stay_g + stay_l
        return (np.full(reps, tot[0]), np.full(reps, tot[1]), 0, False)

    left = rng.multivariate_hypergeometric(stay_l, k, size=reps)
    src = stay_g
    if src.sum() == 0:
        src, fallback = national[gain], True
    p = src / src.sum()
    arrived = rng.multinomial(k, p, size=reps)

    yea = stay_g[0] + stay_l[0] - left[:, 0] + arrived[:, 0]
    nay = stay_g[1] + stay_l[1] - left[:, 1] + arrived[:, 1]
    return yea, nay, k, fallback


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    up = ROOT / "upstream" / "voteview"
    ap.add_argument("--votes", default=str(up / "HSall_votes.csv"))
    ap.add_argument("--rollcalls", default=str(up / "HSall_rollcalls.csv"))
    ap.add_argument("--members", default=str(up / "HSall_members.csv"))
    ap.add_argument("--results", default=str(ROOT / "results"))
    ap.add_argument("--near-miss", default=str(ROOT / "results" / "near_miss.json"))
    ap.add_argument("--reps", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=20260908)
    ap.add_argument("--gate", action="store_true",
                    help="also run with an all-zero delta, which must be exact")
    ap.add_argument("--out", default=str(ROOT / "results" / "reweighted.json"))
    a = ap.parse_args()

    nm = json.loads(Path(a.near_miss).read_text())
    want = {(c["congress"], c["rollnumber"]): c for c in nm["candidates"]}
    cs = nm["congresses"]
    rolls, members = load(a.votes, a.rollcalls, a.members, cs)
    res = Path(a.results)
    delta = {c: deltas(res, PAIRING[c]) for c in cs}
    print(f"{len(want):,} candidate roll calls, {a.reps:,} draws each")
    for c in cs:
        d = {k: v for k, v in delta[c].items() if v}
        print(f"  {c}th <- {PAIRING[c]}: {sum(delta[c].values()):+d} seats "
              f"across {len(d)} states")

    rng = np.random.default_rng(a.seed)
    out, fallbacks, capped = [], 0, 0

    def run(zero):
        exact = []
        for (c, rn), meta in sorted(want.items()):
            row = rolls.get((c, rn))
            if row is None:
                continue
            cnt = counts(row["pos"], members[c])
            nat = {p: cnt[("nat", p)] for p in ("D", "R")}
            base = cnt[("fixed", None)].astype(np.int64)
            yea = np.full(a.reps, base[0], dtype=np.int64)
            nay = np.full(a.reps, base[1], dtype=np.int64)
            moved, fb = 0, 0
            # sorted, not set order: the draws must land on the same states in
            # the same sequence every run, or the seed guarantees nothing.
            for st in sorted(STATES):
                cst = {p: cnt[(st, p)] for p in ("D", "R")}
                if not cst["D"].sum() and not cst["R"].sum():
                    continue
                d = 0 if zero else delta[c].get(st, 0)
                y, n, k, f = resample(rng, cst, d, a.reps, nat)
                yea += y
                nay += n
                moved += k
                fb += f
            exact.append({"key": (c, rn), "meta": meta, "yea": yea, "nay": nay,
                          "moved": moved, "fallback": fb})
        return exact

    if a.gate:
        bad = 0
        for e in run(zero=True):
            m = e["meta"]
            if (e["yea"].min() != e["yea"].max() or e["nay"].min() != e["nay"].max()
                    or int(e["yea"][0]) != m["yea"] or int(e["nay"][0]) != m["nay"]):
                bad += 1
        print(f"\nGATE 3  zero-delta reconstruction: {bad} roll calls differ "
              f"from the recorded tally")
        if bad:
            print("        STOP -- the resampling is not exact at zero")
            return 1

    for e in run(zero=False):
        m, yea, nay = e["meta"], e["yea"], e["nay"]
        # The bar moves with the resampled turnout: a state that converts a
        # member converts its absences too, so the majority line is not fixed.
        two_thirds = m["bar"] == "two thirds"
        need = -(-2 * (yea + nay) // 3) if two_thirds else (yea + nay) // 2 + 1
        p_pass = float((yea >= need).mean())
        fallbacks += e["fallback"]
        capped += e["moved"] != sum(abs(v) for v in delta[e["key"][0]].values())
        out.append({
            "congress": m["congress"], "rollnumber": m["rollnumber"],
            "date": m["date"], "bill": m["bill"], "question": m["question"],
            "desc": m["desc"], "bar": m["bar"],
            "actual_yea": m["yea"], "actual_nay": m["nay"],
            "actual_needed": m["needed"], "actual_distance": m["distance"],
            "actual_outcome": "passed" if m["passed"] else "failed",
            "party_gap": m["party_gap"],
            "mean_yea": round(float(yea.mean()), 1),
            "mean_nay": round(float(nay.mean()), 1),
            "p05": int(np.percentile(yea, 5)), "p95": int(np.percentile(yea, 95)),
            "p_pass": round(p_pass, 4),
            "p_flip": round(p_pass if not m["passed"] else 1 - p_pass, 4),
            "seats_converted": e["moved"],
            "states_using_national_fallback": e["fallback"]})

    flips = [r for r in out if r["p_flip"] >= 0.5]
    likely = [r for r in out if r["p_flip"] >= 0.9]
    out.sort(key=lambda r: (-r["p_flip"], abs(r["actual_distance"])))
    Path(a.out).write_text(json.dumps(
        {"reps": a.reps, "seed": a.seed, "pairing": PAIRING,
         "deltas": {str(c): {k: v for k, v in sorted(delta[c].items()) if v}
                    for c in cs},
         "candidates": len(out),
         "state_draws_using_national_fallback": fallbacks,
         "roll_calls_with_a_state_short_of_members": capped,
         "flip_more_likely_than_not": len(flips),
         "flip_probability_over_90pct": len(likely),
         "votes": out}, indent=1))
    print(f"\n{len(out):,} roll calls reweighted")
    print(f"  outcome more likely than not to reverse: {len(flips):,}")
    print(f"  reverses with probability over 90%:      {len(likely):,}")
    print(f"  state draws falling back to the national pool: {fallbacks:,}")
    print(f"  roll calls where a state had too few members to convert: {capped:,}")
    by = defaultdict(int)
    for r in flips:
        by[r["congress"]] += 1
    print("  reversals by congress: " +
          (", ".join(f"{k}: {v}" for k, v in sorted(by.items())) or "none"))
    print(f"\n{'date':12}{'roll':10}{'actual':>10}{'mean yea':>10}"
          f"{'90% band':>13}{'P(flip)':>9}  outcome")
    for r in out[:20]:
        band = f"{r['p05']}-{r['p95']}"
        print(f"{r['date']:12}{r['congress']}-{r['rollnumber']:<6}"
              f"{r['actual_yea']:5}-{r['actual_nay']:<4}{r['mean_yea']:10.1f}"
              f"{band:>13}{r['p_flip']:9.3f}  {r['actual_outcome']}")
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
