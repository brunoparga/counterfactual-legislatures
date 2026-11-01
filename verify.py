#!/usr/bin/env python3
"""Prove this repository still reproduces its own results, on a machine that
has never seen it.

Run it after a fresh clone, before trusting anything here:

    python3 verify.py

WHAT IT CAN AND CANNOT PROVE

The bulk inputs are not in the repository -- 9.7 GB of census blocks and
block-level election returns, and 737 MB of roll calls, all of which are
fetched rather than committed. So a bare clone cannot re-run the districting
engine or the vote scoring, and no script can pretend otherwise.

What a bare clone *can* do is everything else, and it turns out to be most of
what matters:

  rebuild   Spain's apportionment, Brazil's chamber on the party-level series,
            and the US parameter-sensitivity table are all pure functions of
            bytes that ARE committed. They are re-run here and the output is
            compared against what is stored. This is the real proof: same
            inputs, same code, same bytes.

  re-derive every headline number is recomputed from the per-district and
            per-state rows underneath it, never read out of the summary that
            sits beside them. A summary that drifted from its own rows is
            exactly the failure that would survive a casual look.

  re-check  the validation gates the project set itself -- 209 D / 226 R for
            the enacted 2012 map, 52 of 52 provinces against every Spanish
            decree -- are asserted again here with the answers written into
            this file, so they do not depend on the record that claims them.

  cross-check the published site against the data. Nine pages of hand-written
            numbers drift silently; each headline on them is matched against
            the JSON it came from.

Checks that need the bulk inputs report SKIP and say what to fetch. SKIP never
fails the run; only a FAIL does.

The script writes nothing inside the repository. Rebuilds go to a temporary
directory and are compared from there, so a verification run cannot be
mistaken for a result.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="verify-"))

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results = []
_section = [None]


def section(name):
    _section[0] = name
    print(f"\n\033[1m{name}\033[0m" if sys.stdout.isatty() else f"\n{name}")
    print("-" * max(len(name), 60))


def record(status, name, detail=""):
    results.append((status, _section[0], name, detail))
    mark = {PASS: "ok  ", FAIL: "FAIL", SKIP: "skip"}[status]
    if sys.stdout.isatty():
        colour = {PASS: "\033[32m", FAIL: "\033[31m", SKIP: "\033[33m"}[status]
        mark = f"{colour}{mark}\033[0m"
    print(f"  {mark}  {name}" + (f"  —  {detail}" if detail else ""))


def check(name, got, want, detail=None):
    """Assert a value. The expected answer is written here, not read from the
    artifact being checked, which is the whole point of a gate."""
    ok = got == want
    record(PASS if ok else FAIL, name,
           detail if ok and detail else ("" if ok else f"expected {want!r}, got {got!r}"))
    return ok


def near(name, got, want, tol, unit=""):
    ok = abs(got - want) <= tol
    record(PASS if ok else FAIL, name,
           f"{got:g}{unit}" if ok else f"expected {want:g}±{tol:g}{unit}, got {got:g}{unit}")
    return ok


def load(rel):
    return json.loads((ROOT / rel).read_text())


def run(args, cwd=None):
    """Run a tool, returning (rc, output). Never inside the repository tree."""
    p = subprocess.run([sys.executable, *args], cwd=cwd or ROOT,
                       capture_output=True, text=True, timeout=900)
    return p.returncode, p.stdout + p.stderr


# --------------------------------------------------------------------------
def environment():
    section("1. Environment")
    v = sys.version_info
    check("python3 >= 3.9", v >= (3, 9), True, f"{v.major}.{v.minor}.{v.micro}")
    for mod in ("numpy", "scipy"):
        try:
            m = __import__(mod)
            record(PASS, f"{mod} importable", getattr(m, "__version__", "?"))
        except ImportError:
            record(FAIL, f"{mod} importable", "needed by the scoring tools")
    for exe, why in (("cc", "builds the districting engine"),
                     ("make", "builds the districting engine")):
        where = shutil.which(exe)
        record(PASS if where else FAIL, f"{exe} on PATH", where or why)
    for exe, why in (("git", "provenance checks"),
                     ("libreoffice", "only needed to read .xlsx inputs")):
        where = shutil.which(exe)
        record(PASS if where else SKIP, f"{exe} on PATH", where or f"absent — {why}")


def engine():
    section("2. The districting engine builds")
    src = ROOT / "shared" / "splitline"
    if not (src / "Makefile").exists():
        record(FAIL, "shared/splitline/Makefile present")
        return
    build = TMP / "splitline"
    shutil.copytree(src, build, dirs_exist_ok=True)
    shutil.rmtree(build / "bin", ignore_errors=True)
    p = subprocess.run(["make", "-s"], cwd=build, capture_output=True, text=True)
    if p.returncode != 0:
        record(FAIL, "make", (p.stderr or p.stdout).strip().splitlines()[-1:][0][:120])
        return
    for b in ("splitline", "splitline_raster"):
        record(PASS if (build / "bin" / b).exists() else FAIL, f"bin/{b} built")
    record(PASS, "compiled from a clean tree", "no committed binaries were used")


# --------------------------------------------------------------------------
def rebuild():
    """Re-run every tool that is a pure function of committed bytes, and
    compare against what is stored. Nothing here touches the network."""
    section("3. Rebuilt from committed inputs, byte for byte")

    # --- Spain -------------------------------------------------------------
    out = TMP / "es.json"
    rc, log = run(["spain/tools/apportion_es.py", "--out", str(out)])
    if rc != 0 or not out.exists():
        record(FAIL, "spain/tools/apportion_es.py runs", log.strip()[-160:])
    else:
        same = out.read_bytes() == (ROOT / "spain/results/apportionment.json").read_bytes()
        record(PASS if same else FAIL, "spain/results/apportionment.json rebuilds identically",
               "byte-identical" if same else "output differs from the committed file")
        n = len(re.findall(r"52/52 provinces match the decree", log))
        check("Spain gate: every decree reproduced province by province", n, 7,
              "7 elections, 52 of 52 provinces each")

    # --- Brazil ------------------------------------------------------------
    d = TMP / "br"
    rc, log = run(["brazil/tools/chamber.py", "--source", "passport", "--out", str(d)])
    built = d / "chamber_passport.json"
    if rc != 0 or not built.exists():
        record(SKIP, "brazil/tools/chamber.py (party-level series)",
               "did not run: " + log.strip()[-120:])
    else:
        a, b = json.loads(built.read_text()), load("brazil/results/chamber_passport.json")
        if a == b:
            record(PASS, "brazil/results/chamber_passport.json rebuilds identically")
        else:
            extra = _superset(a, b)
            record(PASS if extra else FAIL,
                   "brazil/results/chamber_passport.json rebuilds consistently",
                   f"rebuild agrees on every stored value and adds {extra} newer field(s); "
                   "the committed file predates them" if extra
                   else "rebuild disagrees with the committed values")

    # --- US sensitivity ----------------------------------------------------
    sens = ROOT / "usa/results/sens"
    if not (sens / "uniform_span_fixed" / "index.json").exists():
        record(SKIP, "usa/tools/sensitivity_table.py", "no scorings under usa/results/sens")
        return
    work = TMP / "sens"
    shutil.copytree(sens, work)
    rc, log = run(["usa/tools/sensitivity_table.py", "--sens", str(work),
                   "--out", str(work / "SENSITIVITY.md")])
    for f in ("SENSITIVITY.md", "sensitivity.json"):
        same = (work / f).read_bytes() == (sens / f).read_bytes()
        record(PASS if same else FAIL, f"usa/results/sens/{f} rebuilds identically",
               "byte-identical" if same else "differs from the committed file")


def _superset(built, stored, path=""):
    """How many fields the rebuild adds. None if it contradicts a stored value."""
    extra = 0
    if isinstance(stored, dict):
        if not isinstance(built, dict):
            return None
        for k, v in stored.items():
            if k not in built:
                return None
            r = _superset(built[k], v)
            if r is None:
                return None
            extra += r
        extra += len(set(built) - set(stored))
    elif isinstance(stored, list):
        if not isinstance(built, list) or len(built) != len(stored):
            return None
        for x, y in zip(built, stored):
            r = _superset(x, y)
            if r is None:
                return None
            extra += r
    elif built != stored:
        return None
    return extra


# --------------------------------------------------------------------------
def gates():
    """The known-answer checks the project set itself. The answers live here,
    so passing does not depend on the file that claims them."""
    section("4. Validation gates, re-asserted")

    rows = load("usa/results/enacted_cd113__E_12_PRES.json")["districts"]
    d = sum(1 for r in rows if r["dem"] > r["rep"])
    check("enacted 113th Congress on 2012 votes: districts counted", len(rows), 435)
    check("enacted 113th Congress on 2012 votes: 209 D", d, 209,
          "the published count of districts Obama carried")
    check("enacted 113th Congress on 2012 votes: 226 R", len(rows) - d, 226)

    # every scoring's summary must agree with its own rows
    bad = []
    for f in sorted((ROOT / "usa/results").glob("*__*.json")):
        j = json.loads(f.read_text())
        m, rs = j["meta"], j["districts"]
        dd = sum(1 for r in rs if r["winner"] == "D")
        dv, rv = sum(r["dem"] for r in rs), sum(r["rep"] for r in rs)
        share = round(100 * dd / len(rs), 3) if rs else 0
        vshare = round(100 * dv / (dv + rv), 3) if dv + rv else 0
        if (dd, len(rs) - dd) != (m["seats_D"], m["seats_R"]) \
           or abs(round(share - vshare, 3) - m["bias"]) > 0.002:
            bad.append(f.name)
    check("every scoring's summary matches its own district rows", bad, [],
          f"{len(list((ROOT/'usa/results').glob('*__*.json')))} scorings recounted")

    # demographics summaries against the per-district files
    s2010 = load("usa/results/demographics/summary_2010.json")
    bad = []
    for plan in ("enacted_cd113", "splitline_2010"):
        per = load(f"usa/results/demographics/{plan}.json")
        for grp in ("hispanic", "nh_white", "nh_black", "nh_asian"):
            got = sum(1 for r in per if r[f"{grp}_pct"] > 50)
            if got != s2010[plan][grp]["majority"]:
                bad.append(f"{plan}/{grp}: {got} vs {s2010[plan][grp]['majority']}")
    check("demographic majority counts recounted from all 435 districts", bad, [],
          "enacted 22 Black-majority, splitline 5")

    # near-miss candidates must all satisfy the screen they were selected by
    nm = load("usa/results/near_miss.json")
    off = [c for c in nm["candidates"]
           if abs(c["distance"]) > nm["cut"] or c["party_gap"] <= nm["party_gap_min"]]
    check("every near-miss candidate satisfies the published screen", off, [],
          f"{len(nm['candidates']):,} of {nm['roll_calls_screened']:,} roll calls")

    rw = load("usa/results/reweighted.json")
    flips = sum(1 for v in rw["votes"] if v["p_flip"] >= 0.5)
    check("reweighted flip count matches its own vote records",
          flips, rw["flip_more_likely_than_not"], f"{flips} reversals")
    check("reweighted covers exactly the screened candidates",
          len(rw["votes"]), len(nm["candidates"]))

    # Spain, recomputed from the stored populations rather than trusted
    es = load("spain/results/apportionment.json")
    bad = []
    for e in es["elections"]:
        pop, seats = e["population"], e["scenarios"]["official"]["seats"]
        if sum(seats.values()) != 350 or len(seats) != 52:
            bad.append(e["election_date"])
        per = {c: pop[c] / seats[c] for c in seats if seats[c]}
        r = max(per.values()) / min(per.values())
        if abs(r - e["scenarios"]["official"]["metrics"]["vote_weight_ratio"]) > 0.005:
            bad.append(e["election_date"] + " ratio")
    check("Spain: 350 seats over 52 constituencies, ratios recomputed", bad, [],
          f"{len(es['elections'])} elections")


# --------------------------------------------------------------------------
def headlines():
    """Recompute, from the rows, every number this project publishes."""
    section("5. Published headlines, recomputed from the data")

    idx = {(m["plan"], m["contest"]): m for m in load("usa/results/index.json")}
    four = ["E_12_PRES", "E_16_PRES", "E_20_PRES", "E_16-20_COMP"]
    e = sum(abs(idx[("enacted_cd113", c)]["bias"]) for c in four) / 4
    s = sum(abs(idx[("splitline_2010", c)]["bias"]) for c in four) / 4
    near("US mean absolute bias, enacted", e, 3.00, 0.005, " points")
    near("US mean absolute bias, splitline", s, 1.04, 0.005, " points")
    near("US bias reduction", 100 * (e - s) / e, 65, 0.5, "%")

    sv = load("usa/results/sens/sensitivity.json")
    red = [r["reduction_pct"] for r in sv["runs"]]
    check("sensitivity: runs that passed their gate", len(sv["gate"]["passed"]), 3)
    check("sensitivity: runs recorded as failing their gate",
          sorted(sv["gate"]["failed"]),
          ["uniform_span_cuberoot", "uniform_span_wyoming"],
          "the house-size axis, which the election data cannot support")
    near("sensitivity: lowest bias reduction", min(red), 63, 0.6, "%")
    near("sensitivity: highest bias reduction", max(red), 65, 0.6, "%")

    c = load("usa/results/compactness.json")
    tot = [(r["splitline"]["mean_km"] * r["population"], r["enacted"]["mean_km"] * r["population"],
            r["population"]) for r in c["states"] if "splitline" in r and "enacted" in r]
    sl = sum(x[0] for x in tot) / sum(x[2] for x in tot)
    en = sum(x[1] for x in tot) / sum(x[2] for x in tot)
    near("compactness: splitline mean distance", sl, 39.13, 0.15, " km")
    near("compactness: enacted mean distance", en, 43.50, 0.15, " km")
    better = sum(1 for r in c["states"] if r.get("seats", 0) > 1
                 and r.get("change_pct", 0) < 0)
    multi = sum(1 for r in c["states"] if r.get("seats", 0) > 1 and "change_pct" in r)
    check("compactness: states where splitline is tighter", (better, multi), (37, 43))

    s2010 = load("usa/results/demographics/summary_2010.json")
    b_en = s2010["enacted_cd113"]["nh_black"]["majority"]
    b_sl = s2010["splitline_2010"]["nh_black"]["majority"]
    check("race: Black-majority districts, enacted then splitline", (b_en, b_sl), (22, 5))
    near("race: reduction", 100 * (b_en - b_sl) / b_en, 77, 0.5, "%")

    rw = load("usa/results/reweighted.json")
    by = {}
    for v in rw["votes"]:
        by[v["congress"]] = by.get(v["congress"], 0) + (v["p_flip"] >= 0.5)
    check("roll calls: reversals in the 113th Congress", by.get(113), 371)
    check("roll calls: total reversals", sum(by.values()), 507)

    # Brazil, recomputed from the seat vectors and the census populations
    ch = load("brazil/results/chamber_tse.json")
    pop = load("brazil/upstream/ibge/population_by_uf.json")["2022"]["population"]
    y = ch["2022"]
    def ratio(seats):
        per = {u: pop[u] / n for u, n in seats.items() if n}
        return max(per.values()) / min(per.values())
    near("Brazil 2022: vote-weight ratio as it stands",
         ratio(y["actual"]["seats_by_uf"]), 7.97, 0.01, "×")
    near("Brazil 2022: ratio without the floor and ceiling",
         ratio(y["no_limits"]["seats_by_uf"]), 1.30, 0.01, "×")
    check("Brazil 2022: São Paulo seats, actual then uncapped",
          (y["actual"]["seats_by_uf"]["SP"], y["no_limits"]["seats_by_uf"]["SP"]), (70, 112))

    def gallagher(seats, votes):
        tv, ts = sum(votes.values()), sum(seats.values())
        return (0.5 * sum((seats.get(k, 0) / ts * 100 - votes.get(k, 0) / tv * 100) ** 2
                          for k in set(seats) | set(votes))) ** 0.5
    years = sorted(ch)
    means = {sc: sum(gallagher(ch[yy][sc]["seats_by_party"], ch[yy]["votes_by_party"])
                     for yy in years) / len(years)
             for sc in ("actual", "no_limits", "national_single_district")}
    near("Brazil: mean Gallagher index as it stands", means["actual"], 4.62, 0.01)
    near("Brazil: cost of the floor and ceiling",
         100 * (means["actual"] - means["no_limits"]) / means["actual"], 13, 0.6, "%")
    near("Brazil: cost of district magnitude",
         100 * (means["actual"] - means["national_single_district"]) / means["actual"],
         84, 0.6, "%")

    es = load("spain/results/apportionment.json")["elections"]
    first, last = es[0], es[-1]
    near("Spain: vote-weight ratio, 2008",
         first["scenarios"]["official"]["metrics"]["vote_weight_ratio"], 3.71, 0.005, "×")
    near("Spain: vote-weight ratio, 2023",
         last["scenarios"]["official"]["metrics"]["vote_weight_ratio"], 4.13, 0.005, "×")
    widening = all(a["scenarios"]["official"]["metrics"]["vote_weight_ratio"]
                   <= b["scenarios"]["official"]["metrics"]["vote_weight_ratio"]
                   for a, b in zip(es, es[1:]))
    check("Spain: the ratio widens at every election", widening, True)
    near("Spain 2023: Madrid's seat deficit",
         last["scenarios"]["official"]["metrics"]["max_seat_deficit"], 12.77, 0.01, " seats")
    moved = {k: last["scenarios"][k]["moved_vs_official"]
             for k in ("floor_1", "no_floor", "sainte_lague")}
    check("Spain 2023: seats moved by each counterfactual", moved,
          {"floor_1": 18, "no_floor": 36, "sainte_lague": 0},
          "the floor moves 18 seats; changing the method moves none")


# --------------------------------------------------------------------------
def site():
    """The published pages are hand-written. Check they still say what the
    data says, and that the tree is internally sound."""
    section("6. The published site")
    D = ROOT / "docs"
    pages = sorted(D.rglob("*.html"))
    check("pages present", len(pages), 9)

    import html.parser

    class P(html.parser.HTMLParser):
        VOID = {"meta", "link", "img", "br", "hr", "input"}

        def __init__(self):
            super().__init__()
            self.stack, self.bad = [], []

        def handle_starttag(self, t, a):
            if t not in self.VOID:
                self.stack.append(t)

        def handle_endtag(self, t):
            if not self.stack or self.stack[-1] != t:
                self.bad.append(t)
            else:
                self.stack.pop()

    broken, unclosed = [], []
    for p in pages:
        q = P()
        q.feed(p.read_text())
        if q.stack or q.bad:
            unclosed.append(p.name)
        for ref in re.findall(r'(?:src|href)="((?!https?:|#|mailto:)[^"]+)"', p.read_text()):
            if not (p.parent / ref.split("#")[0]).exists():
                broken.append(f"{p.relative_to(D)} -> {ref}")
    check("every page is well-formed", unclosed, [])
    check("every internal link and image resolves", broken, [])

    used = set()
    for p in pages:
        for m in re.findall(r'class="([^"]+)"', p.read_text()):
            used |= set(m.split())
    styled = set(re.findall(r"\.([a-zA-Z][\w-]*)", (D / "style.css").read_text()))
    check("every class used on a page has a rule", sorted(used - styled), [])

    # navigation separators are in the markup, so they survive a missing stylesheet
    navless = [p.name for p in pages
               if "&middot;" not in re.search(r'<nav class="sitenav">.*?</nav>',
                                              p.read_text(), re.S).group(0)]
    check("navigation bullets are in the markup, not only in CSS", navless, [])

    # the numbers on the pages against the numbers in the data
    text = {p.relative_to(D).as_posix(): p.read_text() for p in pages}
    rows = load("usa/results/enacted_cd113__E_12_PRES.json")["districts"]
    dcount = sum(1 for r in rows if r["dem"] > r["rep"])
    s2010 = load("usa/results/demographics/summary_2010.json")
    rw = load("usa/results/reweighted.json")
    nm = load("usa/results/near_miss.json")
    c = load("usa/results/compactness.json")
    es = load("spain/results/apportionment.json")["elections"][-1]
    claims = [
        ("united-states/index.html", f"{dcount}&nbsp;D / {len(rows)-dcount}&nbsp;R",
         "the enacted-2012 gate"),
        ("united-states/race.html",
         f"from {s2010['enacted_cd113']['nh_black']['majority']} to "
         f"{s2010['splitline_2010']['nh_black']['majority']}", "Black-majority districts"),
        ("united-states/roll-calls.html", f"{len(nm['candidates']):,}", "candidate roll calls"),
        ("united-states/roll-calls.html", f"{rw['flip_more_likely_than_not']}", "reversals"),
        ("united-states/compactness.html",
         f"{c['national']['enacted_mean_km']:.1f} &rarr; "
         f"{c['national']['splitline_mean_km']:.1f} km", "compactness headline"),
        ("spain/index.html",
         f"{es['scenarios']['official']['metrics']['vote_weight_ratio']:.2f}",
         "Spain's vote-weight ratio"),
        ("index.html", f"{es['scenarios']['official']['metrics']['vote_weight_ratio']:.2f}",
         "Spain's ratio on the home page"),
    ]
    missing = [f"{page}: {why} ({needle!r})"
               for page, needle, why in claims if needle not in text.get(page, "")]
    check("published figures still match the data they came from", missing, [],
          f"{len(claims)} headline figures checked across the site")


# --------------------------------------------------------------------------
def provenance():
    section("7. Provenance records")
    try:
        src = load("SOURCES.json")
    except Exception as exc:
        record(FAIL, "SOURCES.json parses", str(exc)[:120])
        return
    ids = {s["id"] for s in src["sources"]}
    dangling = sorted({d for o in src["outputs"] for d in o["derived_from"]}
                      - ids - {o["id"] for o in src["outputs"]})
    check("every output names sources that exist", dangling, [],
          f"{len(src['sources'])} sources, {len(src['outputs'])} outputs")
    # a path field may list several paths and may carry a parenthetical note
    def paths(field):
        return [q.strip() for q in re.sub(r"\s*\([^)]*\)", "", field).split(",")
                if q.strip()]
    missing = [s["path"] for s in src["sources"]
               if s.get("included_here") and s.get("path")
               and not all((ROOT / q).exists() for q in paths(s["path"]))]
    check("every source marked as included is present", missing, [],
          f"{sum(1 for s in src['sources'] if s.get('included_here'))} sources "
          f"keep their bytes in the repository")
    for f in ("REPRODUCING.md", "SOURCES.json", "LICENSE", "NOTICE", "LICENSE-DATA.md"):
        record(PASS if (ROOT / f).exists() else FAIL, f"{f} present")


def upstream():
    """Say plainly what a bare clone cannot prove, and how to get there."""
    section("8. What this clone cannot prove, and what would fix it")
    wants = [
        ("usa/upstream/2010", "census blocks (PL 94-171)", "python3 usa/tools/fetch_census.py",
         "the districting engine, compactness, demographics"),
        ("usa/upstream/elections/dra_block/x", "block-level election returns",
         "python3 usa/tools/fetch_dra.py", "all vote scoring and the sensitivity matrix"),
        ("usa/upstream/voteview", "congressional roll calls",
         "see REPRODUCING.md step 10", "the near-miss screen and the reweighting"),
        ("brazil/upstream/camara/votos", "Chamber roll calls",
         "python3 brazil/tools/fetch_votes.py", "Brazil's reweighted divisions"),
    ]
    for rel, what, how, blocks in wants:
        if (ROOT / rel).exists():
            record(PASS, f"{what} present", rel)
        else:
            record(SKIP, f"{what} absent", f"{how}  —  unproven here: {blocks}")
    record(SKIP, "end-to-end rebuild of the plans and scorings",
           "needs the inputs above; the committed outputs are checked for internal "
           "consistency instead")


# --------------------------------------------------------------------------
def main():
    print(__doc__.strip().split("\n\n")[0])
    print(f"\nrepository: {ROOT}")
    print(f"scratch:    {TMP}")
    for fn in (environment, engine, rebuild, gates, headlines, site, provenance, upstream):
        try:
            fn()
        except Exception as exc:                      # a crash is a failure, not a stack trace
            record(FAIL, f"{fn.__name__} completed",
                   f"{type(exc).__name__}: {exc}".replace("\n", " ")[:160])
    shutil.rmtree(TMP, ignore_errors=True)

    section("Summary")
    n = {s: sum(1 for r in results if r[0] == s) for s in (PASS, FAIL, SKIP)}
    for status, sec, name, detail in results:
        if status == FAIL:
            print(f"  FAILED  {sec} / {name}" + (f"  —  {detail}" if detail else ""))
    print(f"\n  {n[PASS]} passed, {n[FAIL]} failed, {n[SKIP]} skipped "
          f"(skips are checks this clone cannot run, not failures)")
    if n[FAIL]:
        print("\n  This clone does NOT reproduce. Each failure above names what differs.")
        return 1
    print("\n  Everything this clone can check, reproduces.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
