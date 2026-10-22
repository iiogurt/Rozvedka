"""The coverage grid: every state in scope against the national agency types – what the library has, what was checked
and found not to be published, and what is still open.

A cell is
- covered – the registry has agencies of that type for the state: how many, their listed reports (each number opens the
  Documents list), the newest report year, and whether they are collected by hand (bot-protected sites);
- checked – no regular public report was found (sources/coverage_gaps.yaml, with the date of the check and what was
  found); a source of the type in the registry always wins over such an entry;
- open – neither: a slot to research.
Other official bodies and the think tanks and commercial analysts of a state are counted in columns of their own,
never mixed with the agency types.
"""
import datetime as dt
from functools import lru_cache

import yaml

from . import countries, db, trends
from .config import ROOT

FILE = ROOT / "sources" / "coverage_gaps.yaml"
TYPES = {"intelligence-civil": "Civil intelligence", "intelligence-military": "Military / foreign intelligence",
         "cyber": "Cyber security", "civil-protection": "Civil protection & crisis", "police-ct": "Police / counter-terrorism"}
STALE = 3               # years: a newest report older than this is marked stale
BODIES = ("EU", "NATO", "OTHER")


@lru_cache(maxsize=1)
def checked() -> dict[tuple[str, str], dict]:
    if not FILE.exists():
        return {}
    rows = yaml.safe_load(FILE.read_text(encoding="utf-8")) or []
    return {(r["country"], r["type"]): {**r, "checked": str(r.get("checked") or "")} for r in rows
            if isinstance(r, dict) and r.get("type") in TYPES}


def grid() -> dict:
    names = countries.names()
    now = dt.date.today().year
    with db.session() as con:
        cells: dict[tuple[str, str], dict] = {}
        for r in con.execute(
                f"""SELECT s.country, s.type, COALESCE(s.publisher, 'official') pub, COUNT(DISTINCT s.id) agencies,
                           SUM(s.access = 'manual') manual,
                           (SELECT COUNT(*) FROM documents d JOIN sources s2 ON s2.id=d.source_id
                             WHERE s2.country=s.country AND s2.type=s.type AND {trends.LISTED.replace('s.', 's2.')}) n,
                           (SELECT MAX(d.year) FROM documents d JOIN sources s2 ON s2.id=d.source_id
                             WHERE s2.country=s.country AND s2.type=s.type AND {trends.LISTED.replace('s.', 's2.')}) newest
                    FROM sources s WHERE s.active=1 GROUP BY s.country, s.type"""):
            cells[(r["country"], r["type"])] = dict(r)
    gaps = checked()
    rows = []
    for code in sorted({c for c, _t in cells} | {c for c, _t in gaps} | set(names), key=lambda c: (countries.region_of(c), names.get(c, c))):
        if code in BODIES:
            continue
        row = {"code": code, "name": names.get(code, code), "region": countries.region_of(code)[1], "cells": [],
               }
        for t in TYPES:
            c = cells.get((code, t))
            if c:
                row["cells"].append({"state": "covered" if c["n"] else "empty", "type": t, "agencies": c["agencies"], "manual": c["manual"] or 0,
                                     "n": c["n"], "newest": c["newest"],
                                     "stale": bool(c["newest"]) and now - c["newest"] > STALE,
                                     "link": f"/documents?country={code}&type={t}", "sources": f"/sources#c-{code}"})
            elif (code, t) in gaps:
                g = gaps[(code, t)]
                row["cells"].append({"state": "checked", "type": t, "checked": g["checked"], "note": g.get("note", ""),
                                     "retry": bool(g.get("retry"))})
            else:
                row["cells"].append({"state": "open", "type": t})
        row["other"] = [{"type": t, "agencies": c["agencies"], "n": c["n"], "link": f"/documents?country={code}&type={t}"}
                        for (cc, t), c in sorted(cells.items()) if cc == code and t not in TYPES and c["pub"] == "official"]
        row["independent"] = [{"type": t, "mark": "◆" if t == "think-tank" else "■", "agencies": c["agencies"], "n": c["n"],
                               "link": f"/documents?country={code}&type={t}"}
                              for (cc, t), c in sorted(cells.items()) if cc == code and c["pub"] != "official"]
        rows.append(row)
    cols = []
    for i, (t, name) in enumerate(TYPES.items()):
        states = [r["cells"][i]["state"] for r in rows]
        cols.append({"type": t, "name": name, "covered": states.count("covered"), "empty": states.count("empty"),
                     "checked": states.count("checked"), "open": states.count("open")})
    open_slots = [{"code": r["code"], "name": r["name"], "type": c["type"], "type_name": TYPES[c["type"]]}
                  for r in rows for c in r["cells"] if c["state"] == "open"]
    return {"rows": rows, "cols": cols, "open": open_slots, "types": TYPES, "stale": STALE, "file": "sources/coverage_gaps.yaml",
            "n_checked": sum(c["checked"] for c in cols), "n_covered": sum(c["covered"] for c in cols),
            "empty": [{"code": r["code"], "name": r["name"], **c, "type_name": TYPES[c["type"]]} for r in rows for c in r["cells"]
                      if c["state"] == "empty"],
            "retry": [{"code": r["code"], "name": r["name"], **c} for r in rows for c in r["cells"] if c.get("retry")]}


def figures() -> list[tuple[str, int, str]]:
    """(label, number, Documents link) of every covered cell, for tools/check_links.py."""
    return [(f"grid {r['code']} {c['type']}", c["n"], c["link"]) for r in grid()["rows"] for c in r["cells"]
            if c["state"] in ("covered", "empty")] + \
           [(f"grid {r['code']} {o['type']}", o["n"], o["link"]) for r in grid()["rows"] for o in r["other"] + r["independent"]]
