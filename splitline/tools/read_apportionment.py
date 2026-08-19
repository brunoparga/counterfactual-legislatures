#!/usr/bin/env python3
"""Read the Census apportionment-population tables into a plain dict.

These are the small published tables giving, per state, the population
actually used to apportion the House: resident population plus federal
employees serving overseas allocated back to their home state.

Formats differ by census, so each gets its own reader:

  2020  .xlsx  -- a zip of XML, so zipfile plus the stdlib XML parser is enough
  2010  .xlsx  -- overseas counts only, added to our resident populations
  2000  .html  -- the published results page

No third-party spreadsheet library: an xlsx worksheet is just
xl/worksheets/sheet1.xml with values either inline or indexed into
xl/sharedStrings.xml, which is a few lines to walk.
"""

import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apportionment import NAMES  # noqa: E402

BY_NAME = {v.lower(): k for k, v in NAMES.items()}


def xlsx_rows(path):
    """Yield each row of the first worksheet as a list of cell strings."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{NS}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
        name = next(n for n in z.namelist()
                    if re.fullmatch(r"xl/worksheets/sheet1\.xml", n))
        root = ET.fromstring(z.read(name))
        for row in root.iter(f"{NS}row"):
            out = []
            for cell in row.findall(f"{NS}c"):
                v = cell.find(f"{NS}v")
                txt = "" if v is None else (v.text or "")
                if cell.get("t") == "s" and txt.isdigit():
                    txt = shared[int(txt)]
                elif cell.get("t") == "inlineStr":
                    txt = "".join(t.text or "" for t in cell.iter(f"{NS}t"))
                out.append(txt.strip())
            yield out


def _num(s):
    s = re.sub(r"[,\s]", "", s or "")
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_state_table(rows, want_cols=2):
    """Pull {state abbrev: number} out of rows shaped 'name ... number'."""
    out = {}
    for r in rows:
        if not r:
            continue
        label = None
        for cell in r:
            key = re.sub(r"[^a-z ]", "", (cell or "").lower()).strip()
            if key in BY_NAME:
                label = BY_NAME[key]
                break
        if label is None:
            continue
        nums = [_num(c) for c in r]
        nums = [n for n in nums if n is not None and n > 1000]
        if nums:
            out[label] = max(nums) if want_cols == 1 else nums[0]
    return out


def parse_html_table(path):
    """The 2000 results page: rows of <td>State</td><td>pop</td><td>seats</td>."""
    html = Path(path).read_text(errors="replace")
    cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", html, re.S | re.I)
    cells = [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ").strip() for c in cells]
    out = {}
    for i, c in enumerate(cells):
        key = re.sub(r"[^a-z ]", "", c.lower()).strip()
        if key in BY_NAME:
            for nxt in cells[i + 1:i + 4]:
                n = _num(nxt)
                if n and n > 1000:
                    out[BY_NAME[key]] = n
                    break
    return out


def parse_fixed_text(path):
    """The 2000 table: 'State   Apportionment Population   Seats   Change'."""
    out, seats = {}, {}
    for line in Path(path).read_text(errors="replace").splitlines():
        m = re.match(r"\s{2,}([A-Za-z][A-Za-z .]+?)\s{2,}([\d,]+)\s+(\d+)\s", line)
        if not m:
            continue
        key = re.sub(r"[^a-z ]", "", m.group(1).lower()).strip()
        if key in BY_NAME:
            out[BY_NAME[key]] = _num(m.group(2))
            seats[BY_NAME[key]] = int(m.group(3))
    return out, seats


DATA = Path(__file__).resolve().parent.parent / "data" / "apportionment"


def apportionment_population(year, resident=None):
    """{state: apportionment population} -- resident plus overseas.

    Each census published this differently, so each year has its own route:

      2000  a plain-text table carrying the population directly
      2010  only the overseas counts are machine-readable without an old-BIFF
            reader, so they are added to the resident populations we already
            have; the result is checked against the official seat counts
      2020  an xlsx table carrying the population directly

    `resident` is required for 2010 only.
    """
    if year == 2000:
        pops, _ = parse_fixed_text(DATA / "2000_tab01.txt")
        return pops
    if year == 2020:
        return parse_state_table(list(xlsx_rows(DATA / "apportionment-2020-table01.xlsx")))
    if year == 2010:
        if resident is None:
            raise ValueError("2010 needs resident populations to add overseas to")
        over = parse_state_table(list(xlsx_rows(DATA / "2010CensusOverseasCounts.xlsx")))
        return {s: resident[s] + over.get(s, 0) for s in resident}
    raise ValueError(year)


def official_seats_2000():
    _, seats = parse_fixed_text(DATA / "2000_tab01.txt")
    return seats


def main():
    d = Path(__file__).resolve().parent.parent / "data" / "apportionment"
    for f in sorted(d.glob("*")):
        print(f"== {f.name}")
        try:
            if f.suffix == ".xlsx":
                rows = list(xlsx_rows(f))
                print(f"   {len(rows)} rows; first non-empty:")
                for r in rows[:8]:
                    if any(r):
                        print("     ", r[:6])
                got = parse_state_table(rows)
                print(f"   parsed {len(got)} states, e.g. "
                      + ", ".join(f"{k}={v:,}" for k, v in list(got.items())[:3]))
            elif f.suffix in (".html", ".htm"):
                got = parse_html_table(f)
                print(f"   parsed {len(got)} states, e.g. "
                      + ", ".join(f"{k}={v:,}" for k, v in list(got.items())[:3]))
            else:
                print(f"   ({f.suffix} not parsed here)")
        except Exception as e:
            print(f"   ERROR {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
