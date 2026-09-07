#!/usr/bin/env python3
"""How likely was a close vote to go the other way under a fair apportionment?

WEIGHTING BY STATE, NOT BY PARTY

The finer cell would be (state, party): a state's seat count sets its district
magnitude and magnitude decides which parties win there, so Sao Paulo at 112
seats is not simply 60% more of the delegation it had at 70. That refinement is
unusable here. Brazilian deputies change party mid-term, and between switching
and renaming, 20-30% of the deputies recorded on a division sit in a (state,
party) cell that did not exist when the house was elected. A deputy's *state*
never changes, so the state is the cell that survives contact with the data.

The cost is that the within-state party effect of magnitude goes unmodelled.
That is a real limitation and it is not small; it is simply smaller than
mismatching a quarter of the chamber.

THE MODEL

Each state's delegation is resampled to its counterfactual size:

  seats gained   keep every observed deputy, then draw the extra ones from that
                 state's own observed distribution of positions
  seats lost     drop deputies at random from the state's delegation
  unchanged      leave it alone

The distribution drawn from includes **absences**. A state with 8 seats and 6
recorded votes had two deputies who did not vote, and a ninth seat is as
capable of being empty as the others; ignoring that would inflate every added
delegation by the turnout rate, which for a 308-of-513 bar is exactly the wrong
direction to be wrong in.

This construction is exact when the apportionment does not change: no state
moves, nothing is resampled, and the model returns the true tally with zero
variance. So all the spread reported below comes from seats that actually
moved, not from the machinery.

WHAT IT DOES AND DOES NOT SAY

It answers "with the same electorate voting the same way, how often does a
chamber apportioned by population reach the bar?" It does not predict how named
individuals would have voted, and it cannot: the deputies in the counterfactual
seats do not exist. Probabilities near 50% mean the vote was genuinely on a
knife edge, not that we have pinned down an answer.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from near_miss import AMENDMENT_BAR, term  # noqa: E402


def draw(rng, positions, n_new, reps):
    """(sim, nao) count arrays when a delegation is resized to n_new.

    Both sides are resampled together. Resampling only the Yes count and
    comparing it against a fixed half of the actual turnout is wrong: a state
    that gains seats gains No votes and abstentions too, so the majority line
    moves with the chamber.

    Positions are coded 1 Sim, 2 Nao, 0 anything else including absence.
    """
    base = np.asarray(positions, dtype=np.int8)
    n = len(base)
    if n == 0:
        return np.zeros(reps, np.int64), np.zeros(reps, np.int64)
    if n_new == n:
        return (np.full(reps, int((base == 1).sum()), np.int64),
                np.full(reps, int((base == 2).sum()), np.int64))
    if n_new < n:
        idx = rng.random((reps, n)).argsort(1)[:, :n_new]
    else:
        # keep all, then draw the extra from this state's own mix, absences
        # included -- a new seat is as capable of being empty as the others
        extra = rng.integers(0, n, size=(reps, n_new - n))
        idx = np.concatenate(
            [np.tile(np.arange(n), (reps, 1)), extra], axis=1)
    picked = base[idx]
    return (picked == 1).sum(1).astype(np.int64), (picked == 2).sum(1).astype(np.int64)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default="no_limits")
    ap.add_argument("--reps", type=int, default=40000)
    ap.add_argument("--seed", type=int, default=20260907)
    ap.add_argument("--out", default=str(ROOT / "results" / "reweighted.json"))
    a = ap.parse_args()

    ch = json.loads((ROOT / "results" / "chamber_tse.json").read_text())
    rng = np.random.default_rng(a.seed)
    out = []
    for f in sorted((ROOT / "upstream" / "camara" / "votos").glob("*.json")):
        d = json.loads(f.read_text())
        year = term(d["date"])
        if not year or str(year) not in ch:
            continue
        act = ch[str(year)]["actual"]["seats_by_uf"]
        cf = ch[str(year)][a.scenario]["seats_by_uf"]

        # positions per state, 1 for Sim and 0 for anything else, padded with
        # absences up to the state's seat count
        pos = defaultdict(list)
        for v in d["votes"]:
            if v["uf"] in act:
                pos[v["uf"]].append(
                    1 if v["vote"] == "Sim" else 2 if v["vote"] in ("Não", "Nao") else 0)
        for uf, n in act.items():
            pos[uf] += [0] * max(0, n - len(pos[uf]))

        sims = np.zeros(a.reps, dtype=np.int64)
        naos = np.zeros(a.reps, dtype=np.int64)
        for uf in act:
            s_, n_ = draw(rng, pos[uf], cf.get(uf, 0), a.reps)
            sims += s_
            naos += n_

        # find this vote's screen record for its bar
        meta = next((c for c in json.loads(
            (ROOT / "results" / "near_miss.json").read_text())["candidates"]
            if c["id"] == d["id"]), None)
        if meta is None:
            continue
        actual_sim = d["tally_sim"]
        if meta["pec"]:
            bar_desc = f"Sim >= {AMENDMENT_BAR}"
            passed = actual_sim >= AMENDMENT_BAR
            p = float((sims >= AMENDMENT_BAR).mean())
        else:
            nao = d["tally_nao"]
            bar_desc = "Sim > Nao"
            passed = actual_sim > nao
            p = float((sims > naos).mean())
        out.append({
            "id": d["id"], "date": d["date"], "term": year, "pec": meta["pec"],
            "bar": bar_desc, "actual_sim": actual_sim, "actual_nao": d["tally_nao"],
            "actual_outcome": "passed" if passed else "failed",
            "mean_sim": round(float(sims.mean()), 1),
            "mean_nao": round(float(naos.mean()), 1),
            "p05": int(np.percentile(sims, 5)), "p95": int(np.percentile(sims, 95)),
            "p_pass": round(p, 3),
            "p_flip": round(p if not passed else 1 - p, 3),
            "text": meta["text"][:200]})

    out.sort(key=lambda r: -r["p_flip"])
    Path(a.out).write_text(json.dumps(
        {"scenario": a.scenario, "reps": a.reps, "seed": a.seed, "votes": out},
        indent=1, ensure_ascii=False))
    print(f"{len(out)} divisions reweighted under '{a.scenario}', "
          f"{a.reps:,} draws each\n")
    print(f"{'date':12}{'bar':13}{'actual':>8}{'mean':>8}{'90% band':>13}"
          f"{'P(flip)':>9}  outcome")
    for r in out[:20]:
        band = f"{r['p05']}-{r['p95']}"
        print(f"{r['date']:12}{r['bar']:13}{r['actual_sim']:8}{r['mean_sim']:8.1f}"
              f"{band:>13}{r['p_flip']:9.3f}  {r['actual_outcome']}")
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
