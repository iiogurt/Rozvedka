"""Dated events of one actor, each with its source: what the library's data says happened when.

  founded / dissolved   – Wikidata (inception P571, dissolved P576)
  designated (Wikidata) – "designated as terrorist by" statements with a start date (P3461)
  designated (list)     – entries of the EU, UK, UN and US sanctions lists with a date (the OFAC file has none)
  attributed            – official statements naming the actor (sources/attributions.yaml)
  threat level          – for a country: the official announcements of changes of its terrorism threat level
  first / last named    – the earliest and latest year a report in the library names the actor
Only dated facts are listed; nothing is inferred and nothing is estimated."""
import json

from . import actors, attributions, db, sanctions, threat_levels, trends


def _sortable(date: str) -> str:
    return (str(date) + "-00-00")[:10] if len(str(date)) < 10 else str(date)[:10]


def of_actor(key: str) -> list[dict]:
    out: list[dict] = []
    with db.session() as con:
        actors.init()
        row = con.execute("SELECT key, label, kind, iso, data FROM actors WHERE key=?", (key,)).fetchone()
        if not row:
            return []
        data = json.loads(row["data"] or "{}")
        wd = (data.get("wikidata") or {})
        wd_url = wd.get("url")
        wd_src = {"source": "Wikidata", "source_url": wd_url}
        if data.get("inception"):
            out.append({"date": data["inception"], "kind": "founded", "title": "Founded", "detail": "Wikidata: inception (P571).", **wd_src})
        if data.get("dissolved"):
            out.append({"date": data["dissolved"], "kind": "dissolved", "title": "Dissolved", "detail": "Wikidata: dissolved (P576).", **wd_src})
        for d in data.get("designations") or []:
            if d.get("start"):
                out.append({"date": d["start"], "kind": "designated", "title": f"Designated as terrorist by {d.get('by_label') or d.get('by')}",
                            "detail": "Wikidata: designated as terrorist by (P3461)" + (f", until {d['end']}" if d.get("end") else "") + ".",
                            **wd_src})
        where, args, _ = trends.scope()
        r = con.execute(
            f"""SELECT MIN(d.year) y0, MAX(d.year) y1 FROM doc_actors da JOIN documents d ON d.id=da.doc_id
                JOIN sources s ON s.id=d.source_id JOIN doc_index i ON i.doc_id=d.id
                WHERE da.actor_key=? AND {where} AND {actors.NOT_BEFORE_FOUNDED.replace('a.since_year', '(SELECT since_year FROM actors WHERE key=da.actor_key)')}
                AND d.year >= ?""", (key, *args, trends.MIN_YEAR)).fetchone()
        if r and r["y0"]:
            for which, y in (("first", r["y0"]), ("last", r["y1"])):
                if which == "last" and r["y1"] == r["y0"]:
                    continue
                out.append({"date": str(y), "kind": which, "title": f"{'First' if which == 'first' else 'Latest'} year named in a report of the library",
                            "detail": "Reports of that year naming the actor.", "source": "this library",
                            "source_url": trends.docs_url({"actor": key}, year=y)})
        iso = row["iso"] if row["kind"] == "country" else None
    for s in sanctions.of_actor(key):
        if s.get("date"):
            out.append({"date": s["date"], "kind": "listed", "title": f"Listed on the {sanctions.LISTS[s['list']]['name']}",
                        "detail": f"{s['entry']} ({s['ref']}), matched by {s['via']}: {s['matched']}." + (f" {s['programme']}." if s.get("programme") else ""),
                        "source": sanctions.LISTS[s["list"]]["issuer"], "source_url": s["url"]})
    for a in attributions.of_actor(key):
        out.append({"date": a["date"], "kind": "attributed", "title": a["title"], "detail": a["says"],
                    "source": a["by"], "source_url": a["url"], "quote": a["quote"], "confirmed": a["confirmed"]})
    if iso:
        for e in threat_levels.load():
            if e["kind"] == "announcement" and e["country"] == iso:
                out.append({"date": str(e["as_of"]), "kind": "threat-level",
                            "title": f"Terrorism threat level {e['change']} to {e['label']}", "detail": f"{e['system']}: {e['says']}",
                            "source": e["agency"], "source_url": e["url"], "quote": e["quote"]})
    # a year without a day sorts to the start of the year – except "latest year", which goes to its end
    out.sort(key=lambda e: ((e["date"] + "-99-99") if e["kind"] == "last" else _sortable(e["date"]), e["kind"]))
    return out
