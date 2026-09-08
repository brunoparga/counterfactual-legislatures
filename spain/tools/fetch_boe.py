#!/usr/bin/env python3
"""Fetch the convoking decrees and the article that governs them, from BOE.

LOREG art. 162.4 requires the decree that convokes an election to state the
number of Diputados for each circunscripcion. That annex is the *official*
apportionment -- the thing an implementation of art. 162 has to reproduce
before any counterfactual built on it is worth reading. It is also the only
published form of it: INE publishes populations and the Junta Electoral
publishes results, but nobody else publishes the seat vector.

WHERE THE NUMBERS COME FROM

  legislacion-consolidada API   LOREG art. 162, the rule itself
  diario_boe/txt.php            one decree per election, annex included

Both are BOE's own endpoints and both are stable by document id. The decree
ids are discovered from the daily sumario rather than typed in, so the record
of how each was found survives with it.

WHAT IS NOT DONE HERE

The decree does not say which padron revision it used, and no decree ever has.
That is settled in apportion_es.py by trying each revision and keeping the one
that reproduces the annex exactly -- an empirical answer rather than an
assumed one.
"""

import argparse
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "upstream" / "boe"
UA = {"User-Agent": "counterfactual-legislatures/0.1 (research; github.com/brunoparga)"}
LOREG = "BOE-A-1985-11672"
ART162 = "acientosesentaydos"
SUMARIO = "https://www.boe.es/datosabiertos/api/boe/sumario/{d}"
DOC = "https://www.boe.es/diario_boe/txt.php?id={i}"
CONSOLIDADA = ("https://www.boe.es/datosabiertos/api/legislacion-consolidada/"
               "id/{i}/texto/bloque/{b}")

# BOE issue carrying each dissolution decree, 2008 onward. The date is the
# lookup key; the decree id is read out of that day's sumario, never typed.
ISSUES = ["20080115", "20110927", "20151027", "20160503",
          "20190305", "20190924", "20230530"]

MONTHS = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5,
          "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9,
          "octubre": 10, "noviembre": 11, "diciembre": 12}
# "se celebrarán el domingo 23 de julio de 2023"
ELECTION_RE = re.compile(
    r"celebrar[áa]n?\s+el\s+\w+\s+(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", re.I)


def get(url, accept=None):
    h = dict(UA)
    if accept:
        h["Accept"] = accept
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=h), timeout=120).read().decode("utf-8")


def plain(markup):
    """Tags to newlines, entities decoded, blank lines dropped."""
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", markup, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", "\n", t)
    return [l.strip() for l in html.unescape(t).split("\n") if l.strip()]


def find_decree(day):
    """(id, title) of the dissolution decree in one day's BOE."""
    xml = get(SUMARIO.format(d=day), "application/xml")
    for m in re.finditer(r"<item[^>]*>(.*?)</item>", xml, re.S):
        b = m.group(1)
        t = re.search(r"<titulo>(.*?)</titulo>", b, re.S)
        i = re.search(r"<identificador>(.*?)</identificador>", b, re.S)
        if not (t and i):
            continue
        title = html.unescape(re.sub(r"\s+", " ", t.group(1))).strip()
        if title.lower().startswith("real decreto") and "disoluci" in title.lower():
            return i.group(1).strip(), title
    return None, None


# The seat count is written in words in every decree before 2023 and in
# digits in 2023. Both forms appear as a line of their own after the province.
UNITS = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete",
         "ocho", "nueve", "diez", "once", "doce", "trece", "catorce", "quince",
         "dieciseis", "diecisiete", "dieciocho", "diecinueve", "veinte",
         "veintiuno", "veintidos", "veintitres", "veinticuatro", "veinticinco",
         "veintiseis", "veintisiete", "veintiocho", "veintinueve", "treinta"]
TENS = {"treinta": 30, "cuarenta": 40}
ACCENTS = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")


def spanish_number(s):
    """"Treinta y seis." -> 36. None if the line is not a number word."""
    w = s.translate(ACCENTS).lower().strip().rstrip(".").strip()
    if w.isdigit():
        return int(w)
    if w in UNITS:
        return UNITS.index(w)
    m = re.fullmatch(r"(treinta|cuarenta)\s+y\s+(\w+)", w)
    if m and m.group(2) in UNITS[1:10]:
        return TENS[m.group(1)] + UNITS.index(m.group(2))
    return None


def parse_annex(lines):
    """{province name: seats} from the seat table, plus the election date.

    The table flattens to alternating lines -- a province name, then its seat
    count -- and is anchored on its own two-line header, "Circunscripcion"
    then "Diputados". The header is the anchor rather than the word ANEXO
    because the 2008 decree puts the table inline in article 3 and has no
    annex at all, while later ones do. Article 3's prose also contains
    numbers, which is why nothing before the header is read.
    """
    date = None
    for l in lines:
        m = ELECTION_RE.search(l)
        if m:
            date = (f"{int(m.group(3)):04d}-{MONTHS[m.group(2).lower()]:02d}-"
                    f"{int(m.group(1)):02d}")
            break

    def norm(s):
        return s.translate(ACCENTS).lower().strip().rstrip(".").strip()

    start = None
    for i in range(len(lines) - 1):
        if norm(lines[i]) == "circunscripcion" and norm(lines[i + 1]) == "diputados":
            start = i + 2
            break
    if start is None:
        return date, {}

    seats, pending = {}, None
    for l in lines[start:]:
        n = spanish_number(l)
        if n is not None:
            if pending is not None:
                seats[pending] = n
                pending = None
            continue
        if len(seats) >= 52:
            break
        s = l.strip().rstrip(".").strip()
        pending = s if 3 <= len(s) <= 60 and not any(ch.isdigit() for ch in s) else None
    return date, seats


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--issues", nargs="*", default=ISSUES)
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    art = " ".join(plain(get(CONSOLIDADA.format(i=LOREG, b=ART162),
                             "application/xml"))[2:])
    (OUT / "loreg_art162.txt").write_text(art)
    print(f"LOREG art. 162 ({len(art)} chars) -> {OUT/'loreg_art162.txt'}\n")

    out = []
    for day in a.issues:
        did, title = find_decree(day)
        if not did:
            print(f"{day}: no dissolution decree found")
            continue
        lines = plain(get(DOC.format(i=did)))
        date, seats = parse_annex(lines)
        total = sum(seats.values())
        print(f"{day}  {did}  election {date}  {len(seats)} circunscripciones  "
              f"{total} seats" + ("" if total == 350 and len(seats) == 52
                                  else "   <-- CHECK"))
        out.append({"boe_issue": day, "boe_id": did, "title": title,
                    "url": DOC.format(i=did), "election_date": date,
                    "seats_total": total, "seats": seats})

    p = OUT / "convoking_decrees.json"
    p.write_text(json.dumps({"loreg_id": LOREG, "decrees": out},
                            indent=1, ensure_ascii=False))
    bad = [d for d in out if d["seats_total"] != 350 or len(d["seats"]) != 52]
    print(f"\nwrote {p}")
    if bad:
        print(f"GATE FAILED: {len(bad)} decrees did not parse to 52 "
              f"circunscripciones summing to 350")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
