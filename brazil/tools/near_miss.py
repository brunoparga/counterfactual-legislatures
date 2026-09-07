#!/usr/bin/env python3
"""Which Chamber votes were close enough that the apportionment could decide them?

Reweighting every roll call by a counterfactual apportionment would be
expensive and almost entirely wasted: a vote decided 400 to 60 does not care
how the seats were distributed. The screen comes first, and only what survives
it is worth the per-deputy data.

TWO BARS, AND THEY ARE NOT THE SAME

  ordinary matters   a simple majority of those voting, so the margin is
                     |sim - nao| and a near miss is a small margin
  constitutional     three fifths of the whole house -- 308 of 513 -- in each
  amendments (PEC)   of two rounds, so the margin is sim - 308 and a vote can
                     fail with a crushing majority in favour

The second bar is where Brazilian agendas actually die, and it behaves quite
differently: a PEC with 300 votes to 20 loses. So closeness to 308 is measured
against the yes count alone, not against the opposition.

WHAT COUNTS AS DECIDABLE BY THE APPORTIONMENT

The counterfactual moves no party by more than about eight seats and the
centrao by about four, so the honest screen is narrow. Votes are bucketed by
distance from their bar rather than filtered at one arbitrary cut, so the
reader can see how quickly the candidate set thins.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PEC_RE = re.compile(r"\bPEC\b|Emenda\s+(?:a|à)\s+Constitui", re.I)
# Mentioning a PEC is not the same as being subject to its three-fifths bar. A
# motion to bring one forward, to waive an interval or to set an order of
# business is an ordinary matter and passes on a simple majority. Scoring those
# against 308 would invent dozens of near-misses that never existed.
PROCEDURAL_RE = re.compile(
    r"requerimento|prefer[êe]ncia|interst[íi]cio|urg[êe]ncia|"
    r"quest[ãa]o de ordem|recurso|inclus[ãa]o na ordem do dia|"
    r"encerramento|adiamento|retirada de pauta", re.I)
# Votes that do decide the constitutional text.
SUBSTANTIVE_RE = re.compile(
    r"mantido o texto|suprimid|aprovad[oa] o texto|rejeitad|"
    r"aprovada a reda|\b[12]º?\s*turno\b|em segundo turno|em primeiro turno", re.I)
AMENDMENT_BAR = 308

# Which election produced the house sitting on a given date.
TERMS = [("2003-02-01", "2007-01-31", 2002), ("2007-02-01", "2011-01-31", 2006),
         ("2011-02-01", "2015-01-31", 2010), ("2015-02-01", "2019-01-31", 2014),
         ("2019-02-01", "2023-01-31", 2018), ("2023-02-01", "2027-01-31", 2022)]


def term(date):
    for a, b, y in TERMS:
        if a <= date <= b:
            return y
    return None


def text(r):
    return " ".join(filter(None, [
        r.get("descricao", ""),
        (r.get("ultimaAberturaVotacao") or {}).get("descricao", ""),
        (r.get("ultimaApresentacaoProposicao") or {}).get("descricao", "")]))


def load(dirpath):
    out = []
    for f in sorted(Path(dirpath).glob("votacoes-*.json")):
        d = json.loads(f.read_text())
        for r in (d["dados"] if isinstance(d, dict) else d):
            if r.get("siglaOrgao") != "PLEN":
                continue            # committee votes cannot pass a PEC
            s, n = r.get("votosSim") or 0, r.get("votosNao") or 0
            if s + n < 100:
                continue            # symbolic or near-empty; not a real division
            t = text(r)
            head = r.get("descricao", "")
            mentions_pec = bool(PEC_RE.search(t))
            procedural = bool(PROCEDURAL_RE.search(head))
            substantive = bool(SUBSTANTIVE_RE.search(head))
            out.append({"id": r["id"], "date": r["data"], "sim": s, "nao": n,
                        "outros": r.get("votosOutros") or 0,
                        "approved": r.get("aprovacao"),
                        "mentions_pec": mentions_pec, "procedural": procedural,
                        # subject to 308 only if it decides constitutional text
                        "pec": mentions_pec and substantive and not procedural,
                        "term": term(r["data"]), "text": t})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camara", default=str(ROOT / "upstream" / "camara"))
    ap.add_argument("--out", default=str(ROOT / "results" / "near_miss.json"))
    ap.add_argument("--cut", type=int, default=10,
                    help="distance from the bar to call a vote a candidate")
    a = ap.parse_args()

    votes = load(a.camara)
    for v in votes:
        # distance from the bar that actually applied
        v["bar"] = "3/5 (308)" if v["pec"] else "simple majority"
        v["distance"] = (v["sim"] - AMENDMENT_BAR) if v["pec"] else (v["sim"] - v["nao"])
    print(f"{len(votes):,} plenary divisions with 100+ votes, 2003-2024")
    print(f"  mentioning a PEC anywhere:            "
          f"{sum(1 for v in votes if v['mentions_pec']):,}")
    print(f"  of those, procedural (simple majority): "
          f"{sum(1 for v in votes if v['mentions_pec'] and v['procedural']):,}")
    print(f"  actually subject to the 3/5 bar:       "
          f"{sum(1 for v in votes if v['pec']):,}\n")

    print(f"{'|distance from bar|':22}{'PEC votes':>11}{'other votes':>13}")
    for lo, hi, label in ((0, 5, "0-5"), (6, 10, "6-10"), (11, 20, "11-20"),
                          (21, 50, "21-50"), (51, 10**6, "51+")):
        p = sum(1 for v in votes if v["pec"] and lo <= abs(v["distance"]) <= hi)
        o = sum(1 for v in votes if not v["pec"] and lo <= abs(v["distance"]) <= hi)
        print(f"{label:22}{p:11,}{o:13,}")

    cand = [v for v in votes if abs(v["distance"]) <= a.cut]
    print(f"\n{len(cand):,} candidates within {a.cut} of their bar "
          f"({sum(1 for v in cand if v['pec']):,} PEC)")
    by = defaultdict(int)
    for v in cand:
        by[v["term"]] += 1
    print("  by election that produced the house: " +
          ", ".join(f"{k}: {v}" for k, v in sorted(by.items(), key=lambda x: (x[0] or 0))))

    print(f"\nclosest PEC votes (yes count against the 308 bar):")
    for v in sorted([v for v in votes if v["pec"]],
                    key=lambda v: abs(v["distance"]))[:12]:
        print(f"  {v['date']}  sim {v['sim']:3} nao {v['nao']:3}  "
              f"{v['distance']:+4} from 308  {v['text'][:95]}")
    Path(a.out).write_text(json.dumps(
        {"cut": a.cut, "total_divisions": len(votes),
         "candidates": sorted(cand, key=lambda v: abs(v["distance"]))},
        indent=1, ensure_ascii=False))
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
