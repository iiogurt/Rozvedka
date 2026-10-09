"""Actor timeline: when each agency first and last named an actor, reports per year by reporting country,
and how the actors named beside it changed over the years. Same document base as the actor page."""
import json

from . import actors, db, trends

PARTNERS = 15       # actors named in the same passage, shown as rows
COUNTRIES = 25      # reporting countries, shown as rows (the rest is counted in "other")
RECENT = 3          # a partner is "new" when it first appears in the last RECENT years of the actor's span


def detail(key: str) -> dict | None:
    where, args, _ = trends.scope()
    with db.session() as con:
        actors.init()
        row = con.execute("SELECT key, label, kind, since_year FROM actors WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        docs = [dict(r) for r in con.execute(
            f"""SELECT da.doc_id, d.title, d.year, s.id source_id, s.agency, s.country, s.name_en
                FROM doc_actors da JOIN documents d ON d.id=da.doc_id JOIN sources s ON s.id=d.source_id
                JOIN doc_index i ON i.doc_id=d.id
                WHERE da.actor_key=? AND {where}
                  AND (? IS NULL OR d.year IS NULL OR d.year >= ?)""",
            (key, *args, row["since_year"], row["since_year"]))]
        dated = [d for d in docs if d["year"] and d["year"] >= trends.MIN_YEAR]
        years = list(range(min(d["year"] for d in dated), max(d["year"] for d in dated) + 1)) if dated else []

        # first and last report per agency
        by_agency: dict[int, dict] = {}
        for d in sorted(dated, key=lambda d: (d["year"], d["doc_id"])):
            a = by_agency.setdefault(d["source_id"], {"source_id": d["source_id"], "agency": d["agency"],
                                                     "country": d["country"], "docs": 0, "first": d, "years": set()})
            a["docs"] += 1; a["last"] = d; a["years"].add(d["year"])
        agencies = sorted(by_agency.values(), key=lambda a: (a["first"]["year"], -a["docs"], a["agency"]))
        for a in agencies:
            a["n_years"] = len(a.pop("years"))
            a["link"] = trends.docs_url({"actor": key, "source": a["source_id"]})

        # reports per year by reporting country
        per_country: dict[str, dict[int, int]] = {}
        for d in dated:
            per_country.setdefault(d["country"], {}).setdefault(d["year"], 0)
            per_country[d["country"]][d["year"]] += 1
        ranked = sorted(per_country, key=lambda c: (-sum(per_country[c].values()), c))
        countries = [{"country": c, "total": sum(per_country[c].values()),
                      "cells": [{"year": y, "n": per_country[c].get(y, 0),
                                 "link": trends.docs_url({"actor": key, "country": c}, year=y)} for y in years]}
                     for c in ranked[:COUNTRIES]]
        peak = max((x["n"] for c in countries for x in c["cells"]), default=0)

        # actors named in the same passage, per year
        ids = [d["doc_id"] for d in dated]
        partners = []
        if ids:
            year_of = {d["doc_id"]: d["year"] for d in dated}
            marks = ",".join("?" * len(ids))
            rows = con.execute(
                f"""SELECT CASE WHEN p.a=? THEN p.b ELSE p.a END other, p.doc_id
                    FROM actor_pairs p JOIN documents d ON d.id=p.doc_id
                    JOIN actors a1 ON a1.key=p.a JOIN actors a2 ON a2.key=p.b
                    WHERE (p.a=? OR p.b=?) AND p.doc_id IN ({marks}) AND {actors.PAIR_FOUNDED}""",
                (key, key, key, *ids)).fetchall()
            seen: dict[str, dict[int, set]] = {}
            for r in rows:
                seen.setdefault(r["other"], {}).setdefault(year_of[r["doc_id"]], set()).add(r["doc_id"])
            info = {r["key"]: (r["label"], r["kind"]) for r in con.execute(
                f"SELECT key, label, kind FROM actors WHERE key IN ({','.join('?' * len(seen))})", list(seen))} if seen else {}
            ordered = sorted((k for k in seen if info.get(k, ("", "country"))[1] != "country"),
                             key=lambda k: -sum(len(v) for v in seen[k].values()))[:PARTNERS]
            recent_from = years[-1] - RECENT + 1
            for k in ordered:
                by_year = {y: len(v) for y, v in seen[k].items()}
                y0, y1 = min(by_year), max(by_year)
                partners.append({
                    "key": k, "label": info[k][0], "kind": info[k][1], "total": sum(by_year.values()),
                    "first": y0, "last": y1,
                    "status": "new" if y0 >= recent_from and len(years) > RECENT else
                              "gone" if y1 < recent_from and len(years) > RECENT else "",
                    "cells": [{"year": y, "n": by_year.get(y, 0),
                               "link": trends.docs_url({"cluster": f"{key},{k}"}, year=y)} for y in years]})
        pmax = max((c["n"] for p in partners for c in p["cells"]), default=0)
    return {"actor": dict(row), "years": years, "docs": len(dated), "agencies": agencies, "countries": countries,
            "n_countries": len(ranked), "peak": peak, "partners": partners, "pmax": pmax, "recent": RECENT,
            "undated": len(docs) - len(dated)}
