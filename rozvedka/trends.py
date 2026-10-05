"""Statistics behind the Trends pages.

Every number is a count of documents in the library, never an estimate, and every result carries the filter that
reproduces its documents on the Documents page (`docs_url`), so each point of a chart can be traced back to the
reports it counts.

Scope ("in scope" documents): listed on the Documents page (not hidden, not missing/duplicate/skipped), with a
year, and with extracted text that has been topic-classified. Undated and unclassified documents are reported as
excluded, not silently dropped.
"""
import datetime as dt
from urllib.parse import urlencode

import yaml

from . import countries, db, topics
from .config import ROOT

EVENTS = ROOT / "sources" / "events.yaml"
MIN_YEAR = 2000
LOW_SAMPLE = 30      # years with fewer documents in scope are marked as unreliable
MATRIX_MIN_DOCS = 5  # rows (agencies/countries) with fewer documents in the period are left out of the matrix

LISTED = "d.hidden=0 AND s.active=1 AND d.status NOT IN ('missing','duplicate','skipped')"
CLASSIFIED = "d.id IN (SELECT doc_id FROM doc_index WHERE taxonomy_hash IS NOT NULL AND error IS NULL)"


def scope(country: str = "", coalition: str = "", type: str = "") -> tuple[str, list, dict]:
    """SQL condition for the filtered document set, its arguments, and the matching Documents-page parameters."""
    where, args, params = [LISTED], [], {}
    if coalition in countries.coalitions():
        codes = sorted(countries.scope(coalition))
        where.append(f"s.country IN ({','.join('?' * len(codes))})"); args += codes
        params["coalition"] = coalition
    if country:
        where.append("s.country=?"); args.append(country.upper()); params["country"] = country.upper()
    if type:
        where.append("s.type=?"); args.append(type); params["type"] = type
    return " AND ".join(where), args, params


def docs_url(params: dict, **extra) -> str:
    """Documents-page link listing exactly the counted documents (indexed=1 limits it to classified ones)."""
    merged = {**params, "indexed": 1, **extra}
    return "/documents?" + urlencode({k: v for k, v in merged.items() if v not in ("", None, [])}, doseq=True)


def _years(con, where: str, args: list) -> list[int]:
    now = dt.date.today().year
    row = con.execute(f"""SELECT MIN(d.year), MAX(d.year) FROM documents d JOIN sources s ON s.id=d.source_id
                          WHERE {where} AND {CLASSIFIED} AND d.year BETWEEN ? AND ?""",
                      (*args, MIN_YEAR, now)).fetchone()
    return list(range(row[0], row[1] + 1)) if row[0] else []


def _excluded(con, where: str, args: list) -> dict:
    r = con.execute(f"""SELECT COUNT(*) listed, SUM(d.year IS NULL) undated,
                               SUM(d.year_source IS NOT NULL AND d.year_source != 'set by hand') estimated,
                               SUM(d.year IS NOT NULL AND d.id NOT IN (SELECT doc_id FROM doc_index
                                   WHERE taxonomy_hash IS NOT NULL AND error IS NULL)) unclassified,
                               SUM(d.year < ?) before
                        FROM documents d JOIN sources s ON s.id=d.source_id WHERE {where}""",
                    (MIN_YEAR, *args)).fetchone()
    return {"listed": r["listed"], "undated": r["undated"] or 0, "unclassified": r["unclassified"] or 0,
            "estimated": r["estimated"] or 0,
            "before_min_year": r["before"] or 0}


def _denominators(con, where: str, args: list, years: list[int]) -> tuple[dict, dict]:
    docs, agencies = {}, {}
    for r in con.execute(f"""SELECT d.year, COUNT(*) n, COUNT(DISTINCT d.source_id) a
                             FROM documents d JOIN sources s ON s.id=d.source_id
                             WHERE {where} AND {CLASSIFIED} AND d.year BETWEEN ? AND ? GROUP BY d.year""",
                         (*args, years[0], years[-1])):
        docs[r["year"]], agencies[r["year"]] = r["n"], r["a"]
    return docs, agencies


def _provenance(con, how: str, filters: dict, years: list[int], where: str, args: list) -> dict:
    tax = topics.taxonomy()
    return {"how": how, "filters": filters, "years": [years[0], years[-1]] if years else [],
            "excluded": _excluded(con, where, args), "low_sample": LOW_SAMPLE,
            "taxonomy": {"file": "sources/topics.yaml", "hash": tax["hash"]},
            "generated": dt.datetime.now().isoformat(timespec="seconds")}


def _series(years, per_year_docs, per_year_agencies, den_docs, den_agencies, link) -> dict:
    def share(num, den):
        return [round(num.get(y, 0) / den[y], 4) if den.get(y) else None for y in years]
    return {"docs": [per_year_docs.get(y, 0) for y in years],
            "agencies": [per_year_agencies.get(y, 0) for y in years],
            "share_docs": share(per_year_docs, den_docs),
            "share_agencies": share(per_year_agencies, den_agencies),
            "links": [link(y) for y in years]}


def topic_trends(chosen: list[str], country: str = "", coalition: str = "", type: str = "") -> dict:
    tax = topics.taxonomy()["topics"]
    chosen = [t for t in chosen if t in tax]
    where, args, params = scope(country, coalition, type)
    with db.session() as con:
        topics.init()
        years = _years(con, where, args)
        out = {"years": years, "series": [], "denominator": {}, "events": events(years),
               "provenance": _provenance(
                   con, "For each year: documents tagged with the topic ÷ all documents in scope that year "
                        "(share of reports), or agencies with at least one such document ÷ agencies that published "
                        "in scope that year (share of agencies). Topic tags come from the keyword index "
                        "(sources/topics.yaml).", params, years, where, args)}
        if not years:
            return out
        den_docs, den_agencies = _denominators(con, where, args, years)
        out["denominator"] = {"docs": [den_docs.get(y, 0) for y in years],
                              "agencies": [den_agencies.get(y, 0) for y in years],
                              "links": [docs_url(params, year=y) for y in years]}
        for t in chosen:
            nd, na = {}, {}
            for r in con.execute(f"""SELECT d.year, COUNT(*) n, COUNT(DISTINCT d.source_id) a
                                     FROM doc_topics t JOIN documents d ON d.id=t.doc_id JOIN sources s ON s.id=d.source_id
                                     WHERE t.topic=? AND {where} AND {CLASSIFIED} AND d.year BETWEEN ? AND ?
                                     GROUP BY d.year""", (t, *args, years[0], years[-1])):
                nd[r["year"]], na[r["year"]] = r["n"], r["a"]
            out["series"].append({"key": t, "name": tax[t]["name"],
                                  **_series(years, nd, na, den_docs, den_agencies,
                                            lambda y, t=t: docs_url(params, topic=t, year=y))})
    return out


def rising(country: str = "", coalition: str = "", type: str = "", limit: int = 10) -> dict:
    """Topics whose share of reports changed most between two periods (percentage points)."""
    tax = topics.taxonomy()["topics"]
    now = dt.date.today().year
    recent, earlier = (now - 2, now - 1), (now - 5, now - 3)    # the current, incomplete year is left out
    where, args, params = scope(country, coalition, type)
    with db.session() as con:
        topics.init()

        def period(y0, y1):
            den = con.execute(f"""SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                                  WHERE {where} AND {CLASSIFIED} AND d.year BETWEEN ? AND ?""",
                              (*args, y0, y1)).fetchone()[0]
            num = dict(con.execute(f"""SELECT t.topic, COUNT(*) FROM doc_topics t JOIN documents d ON d.id=t.doc_id
                                       JOIN sources s ON s.id=d.source_id
                                       WHERE {where} AND {CLASSIFIED} AND d.year BETWEEN ? AND ? GROUP BY t.topic""",
                                   (*args, y0, y1)).fetchall())
            return den, num
        den_r, num_r = period(*recent)
        den_e, num_e = period(*earlier)
    rows = []
    if den_r and den_e:
        for t, info in tax.items():
            if info.get("meta"):
                continue
            a, b = num_e.get(t, 0) / den_e, num_r.get(t, 0) / den_r
            rows.append({"key": t, "name": info["name"], "earlier": round(a, 4), "recent": round(b, 4),
                         "change_pp": round((b - a) * 100, 1), "n_earlier": num_e.get(t, 0), "n_recent": num_r.get(t, 0),
                         "link_earlier": docs_url(params, topic=t, year_from=earlier[0], year_to=earlier[1]),
                         "link_recent": docs_url(params, topic=t, year_from=recent[0], year_to=recent[1])})
    rows.sort(key=lambda r: r["change_pp"])
    return {"recent": recent, "earlier": earlier, "docs_recent": den_r, "docs_earlier": den_e,
            "rising": rows[::-1][:limit], "falling": [r for r in rows if r["change_pp"] < 0][:limit],
            "how": f"Share of reports tagged with the topic in {recent[0]}–{recent[1]} minus its share in "
                   f"{earlier[0]}–{earlier[1]}, in percentage points. {now} is incomplete and left out."}


def or_query(series: str) -> str:
    """'drone OR Drohne OR "bezpilotní letoun"' → one FTS5 query matching any alternative."""
    alts = [topics.fts_query(a) for a in series.split(" OR ")]
    alts = [a for a in alts if a]
    return " OR ".join(f"({a})" for a in alts)


def term_trends(terms: list[str], country: str = "", coalition: str = "", type: str = "") -> dict:
    where, args, params = scope(country, coalition, type)
    with db.session() as con:
        topics.init()
        years = _years(con, where, args)
        out = {"years": years, "series": [], "denominator": {}, "events": events(years),
               "provenance": _provenance(
                   con, "For each year: documents whose full text contains the term (any of the OR alternatives; "
                        "words match by prefix, accents ignored, quoted phrases exactly) ÷ all documents in scope "
                        "that year. A document counts once however often it uses the term. Terms are matched "
                        "literally, in the language typed – add translations with OR.", params, years, where, args)}
        if not years:
            return out
        den_docs, den_agencies = _denominators(con, where, args, years)
        out["denominator"] = {"docs": [den_docs.get(y, 0) for y in years],
                              "agencies": [den_agencies.get(y, 0) for y in years],
                              "links": [docs_url(params, year=y) for y in years]}
        for term in terms:
            q = or_query(term)
            if not q:
                continue
            nd, na = {}, {}
            for r in con.execute(f"""SELECT d.year, COUNT(*) n, COUNT(DISTINCT d.source_id) a
                                     FROM documents d JOIN sources s ON s.id=d.source_id
                                     WHERE d.id IN (SELECT rowid FROM doc_text WHERE doc_text MATCH ?)
                                       AND {where} AND {CLASSIFIED} AND d.year BETWEEN ? AND ? GROUP BY d.year""",
                                 (q, *args, years[0], years[-1])):
                nd[r["year"]], na[r["year"]] = r["n"], r["a"]
            out["series"].append({"key": term, "name": term, "fts": q,
                                  **_series(years, nd, na, den_docs, den_agencies,
                                            lambda y, term=term: docs_url(params, q=term, year=y))})
    return out


def matrix(year_from: int, year_to: int, by: str = "country", coalition: str = "", type: str = "",
           include_meta: bool = False) -> dict:
    """Rows (countries or agencies) × topics: share of the row's documents in the period tagged with each topic."""
    tax = topics.taxonomy()
    where, args, params = scope("", coalition, type)
    names = countries.names()
    with db.session() as con:
        topics.init()
        period = f"{where} AND {CLASSIFIED} AND d.year BETWEEN ? AND ?"
        pargs = (*args, year_from, year_to)
        key = "s.country" if by == "country" else "s.id"
        rows = {}
        for r in con.execute(f"""SELECT {key} k, s.country, s.agency, COUNT(*) n FROM documents d
                                 JOIN sources s ON s.id=d.source_id WHERE {period} GROUP BY {key}""", pargs):
            if r["n"] < MATRIX_MIN_DOCS:
                continue
            label = names.get(r["country"], r["country"]) if by == "country" else f"{r['agency']} ({r['country']})"
            link_params = {"country": r["country"]} if by == "country" else {"source": r["k"]}
            rows[r["k"]] = {"key": r["k"], "label": label, "country": r["country"], "docs": r["n"],
                            "params": link_params}
        cols = [t for c in tax["categories"].values() for t in c["topics"]
                if include_meta or not tax["topics"][t].get("meta")]
        cells = []
        for r in con.execute(f"""SELECT {key} k, t.topic, COUNT(*) n FROM doc_topics t JOIN documents d ON d.id=t.doc_id
                                 JOIN sources s ON s.id=d.source_id WHERE {period} GROUP BY {key}, t.topic""", pargs):
            if r["k"] in rows and r["topic"] in cols:
                row = rows[r["k"]]
                cells.append({"row": r["k"], "topic": r["topic"], "n": r["n"], "share": round(r["n"] / row["docs"], 4),
                              "link": docs_url({**params, **row["params"]}, topic=r["topic"],
                                               year_from=year_from, year_to=year_to)})
        prov = _provenance(con, f"Each cell: documents of the {'country' if by == 'country' else 'agency'} from "
                                f"{year_from}–{year_to} tagged with the topic ÷ all its documents in that period. "
                                f"Rows with fewer than {MATRIX_MIN_DOCS} documents are left out. Countries publish "
                                "different kinds of reports, so a low share can mean a topic is covered elsewhere.",
                           params, [year_from, year_to], where, args)
    for row in rows.values():
        row["link"] = docs_url({**params, **row.pop("params")}, year_from=year_from, year_to=year_to)
    return {"rows": sorted(rows.values(), key=lambda r: r["label"]),
            "topics": [{"key": t, "name": tax["topics"][t]["name"],
                        "category": next(c["name"] for c in tax["categories"].values() if t in c["topics"])}
                       for t in cols],
            "cells": cells, "year_from": year_from, "year_to": year_to, "by": by, "provenance": prov}


def events(years: list[int] | None = None) -> list[dict]:
    """Reference events with their Wikidata/Wikipedia source (see tools/build_events.py)."""
    try:
        data = yaml.safe_load(EVENTS.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return []
    out = []
    for e in data.get("events", []):
        if not e.get("date"):
            continue
        year = int(str(e["date"])[:4])
        if years and not (years[0] <= year <= years[-1]):
            continue
        out.append({"label": e["label"], "date": str(e["date"]), "year": year, "wikidata": e["wikidata"],
                    "date_property": e["date_property"], "wikipedia_url": e["wikipedia_url"],
                    "wikidata_url": e["wikidata_url"], "retrieved": str(e["retrieved"])})
    return out
