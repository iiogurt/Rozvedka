"""Data behind the Network, Geography and topic mind-map views.

Like the Trends pages, every node, link and country carries the link that lists exactly the documents (or
passages) it counts, and every result says how it was computed.
"""
import datetime as dt
from urllib.parse import urlencode

from . import actors, countries, db, topics, trends
from .actors import NOT_BEFORE_FOUNDED, PAIR_FOUNDED


def _scope(year_from=None, year_to=None, coalition="", type="", topic="", country=""):
    where, args, params = trends.scope(country, coalition, type)
    where += f" AND {trends.CLASSIFIED}"
    if year_from:
        where += " AND d.year >= ?"; args.append(int(year_from)); params["year_from"] = int(year_from)
    if year_to:
        where += " AND d.year <= ?"; args.append(int(year_to)); params["year_to"] = int(year_to)
    if topic:
        where += " AND d.id IN (SELECT doc_id FROM doc_topics WHERE topic=?)"; args.append(topic); params["topic"] = topic
    return where, args, params


def _qs(params: dict) -> str:
    return urlencode({k: v for k, v in params.items() if v not in ("", None)})


def network(year_from=None, year_to=None, coalition="", type="", topic="", kinds: list[str] | None = None,
            include_countries=False, max_nodes=80, min_link=2) -> dict:
    """Actors (nodes, sized by reports) linked when named in the same passage (links, weighted by reports)."""
    where, args, params = _scope(year_from, year_to, coalition, type, topic)
    kinds = [k for k in (kinds or []) if k in actors.KINDS]
    kind_sql, kind_args = "", []
    if kinds:
        kind_sql = f" AND a.kind IN ({','.join('?' * len(kinds))})"; kind_args = kinds
    elif not include_countries:
        kind_sql = " AND a.kind != 'country'"
    with db.session() as con:
        actors.init()
        nodes = [dict(r) for r in con.execute(
            f"""SELECT a.key, a.label, a.kind, COUNT(DISTINCT da.doc_id) docs
                FROM doc_actors da JOIN actors a ON a.key=da.actor_key JOIN documents d ON d.id=da.doc_id
                JOIN sources s ON s.id=d.source_id
                WHERE {where} AND {NOT_BEFORE_FOUNDED}{kind_sql}
                GROUP BY a.key ORDER BY docs DESC, a.label LIMIT ?""", (*args, *kind_args, max_nodes))]
        keys = [n["key"] for n in nodes]
        links = []
        if keys:
            marks = ",".join("?" * len(keys))
            links = [dict(r) for r in con.execute(
                f"""SELECT p.a, p.b, COUNT(DISTINCT p.doc_id) docs FROM actor_pairs p
                    JOIN documents d ON d.id=p.doc_id JOIN sources s ON s.id=d.source_id
                    JOIN actors a1 ON a1.key=p.a JOIN actors a2 ON a2.key=p.b
                    WHERE p.a IN ({marks}) AND p.b IN ({marks}) AND {where} AND {PAIR_FOUNDED}
                    GROUP BY p.a, p.b HAVING docs >= ?""", (*keys, *keys, *args, min_link))]
        excluded = trends._excluded(con, *trends.scope("", coalition, type)[:2])
    qs = _qs({k: params.get(k) for k in ("year_from", "year_to", "coalition", "type", "topic")})
    for n in nodes:
        n["link"] = f"/actors/{n['key']}"
        n["docs_link"] = trends.docs_url({k: v for k, v in params.items()}, actor=n["key"])
    for lk in links:
        lk["link"] = f"/actors/{lk['a']}/with/{lk['b']}" + (f"?{qs}" if qs else "")
    return {"nodes": nodes, "links": links, "filters": params, "kinds": actors.KINDS,
            "provenance": {
                "how": f"Nodes: the {len(nodes)} actors named in the most reports in scope (size = reports). Links: two "
                       f"actors named within {actors.WINDOW} characters of each other – roughly the same paragraph – "
                       f"in at least {min_link} reports (width = reports). Being named together is not evidence of a "
                       "connection: open a link to read the passages.",
                "excluded": excluded, "generated": dt.datetime.now().isoformat(timespec="seconds"),
                "gazetteer": actors.stamp().get("gazetteer_retrieved")}}


def _country_actors(con) -> dict[str, dict]:
    return {r["key"]: dict(r) for r in con.execute("SELECT key, label, iso FROM actors WHERE kind='country'")}


def geography(mode: str = "about", target: str = "", year_from=None, year_to=None, type="") -> dict:
    """mode 'about': for a mentioned country (Wikidata id), the share of each reporting country's reports naming it.
    mode 'from': for a reporting country (ISO) or coalition, the share of its reports naming each other country."""
    names = countries.names()
    with db.session() as con:
        actors.init()
        cmap = _country_actors(con)
        by_iso = {c["iso"]: c for c in cmap.values() if c["iso"]}
        out = {"mode": mode, "target": target, "rows": [],
               "countries": sorted(({"key": c["key"], "label": c["label"], "iso": c["iso"]} for c in cmap.values()),
                                   key=lambda c: c["label"])}
        if mode == "about":
            c = cmap.get(target)
            if not c:
                return out
            where, args, params = _scope(year_from, year_to, "", type)
            den = dict(con.execute(f"""SELECT s.country, COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                                       WHERE {where} GROUP BY s.country""", args).fetchall())
            num = dict(con.execute(
                f"""SELECT s.country, COUNT(DISTINCT d.id) FROM doc_actors da JOIN documents d ON d.id=da.doc_id
                    JOIN sources s ON s.id=d.source_id JOIN actors a ON a.key=da.actor_key
                    WHERE da.actor_key=? AND {where} AND {NOT_BEFORE_FOUNDED} GROUP BY s.country""",
                (target, *args)).fetchall())
            for rep, n in sorted(den.items()):
                if rep == c["iso"]:
                    continue        # a country's own reports naming itself say nothing about attention
                out["rows"].append({"iso": rep, "name": names.get(rep, rep), "docs": num.get(rep, 0), "of": n,
                                    "share": round(num.get(rep, 0) / n, 4) if n else None,
                                    "link": trends.docs_url({**params, "country": rep}, actor=target)})
            out["label"] = c["label"]
            out["how"] = (f"For each reporting country: its reports in scope that name {c['label']} (names, aliases and "
                          f"demonyms from Wikidata) ÷ all its reports in scope. {names.get(c['iso'], c['label'])}'s own "
                          "reports are left out. EU and NATO bodies and international organisations are listed in the "
                          "table but not on the map.")
        else:
            coalition = target if target in countries.coalitions() else ""
            country = "" if coalition else target
            if not (coalition or country):
                return out
            where, args, params = _scope(year_from, year_to, coalition, type, country=country)
            den = con.execute(f"SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id WHERE {where}",
                              args).fetchone()[0]
            own = set(countries.scope(coalition)) if coalition else {country}
            for r in con.execute(
                    f"""SELECT da.actor_key, COUNT(DISTINCT d.id) n FROM doc_actors da JOIN documents d ON d.id=da.doc_id
                        JOIN sources s ON s.id=d.source_id JOIN actors a ON a.key=da.actor_key
                        WHERE a.kind='country' AND {where} AND {NOT_BEFORE_FOUNDED} GROUP BY da.actor_key""", args):
                c = cmap[r["actor_key"]]
                if c["iso"] in own and not coalition:
                    continue
                out["rows"].append({"iso": c["iso"], "key": c["key"], "name": c["label"], "docs": r["n"], "of": den,
                                    "share": round(r["n"] / den, 4) if den else None, "own": c["iso"] in own,
                                    "link": trends.docs_url(params, actor=c["key"]), "actor": f"/actors/{c['key']}"})
            out["label"] = (countries.coalitions()[coalition]["name"] if coalition else names.get(country, country))
            out["how"] = (f"For each country: reports in scope from {out['label']} that name it (names, aliases and "
                          f"demonyms from Wikidata) ÷ all {den} reports in scope from {out['label']}."
                          + (" Member countries are shown too, marked." if coalition else
                             " The reporting country itself is left out."))
        out["rows"].sort(key=lambda r: (-(r["share"] or 0), r["name"]))
        out["filters"] = {k: v for k, v in {"year_from": year_from, "year_to": year_to, "type": type}.items() if v}
        out["generated"] = dt.datetime.now().isoformat(timespec="seconds")
    return out


def topic_tree(per_topic: int = 6, coalition: str = "", year_from=None, year_to=None, min_reports: int = 3) -> dict:
    """Categories → topics (reports) → the actors most characteristic of each topic.

    For each topic, actors are ranked by n × n / total: n = reports that have the topic among their main topics
    (topics.MAIN_TOPICS highest keyword scores) and name the actor, total = all reports naming the actor. Frequent and
    specific actors come first; actors need `min_reports` such reports.
    """
    tax = topics.taxonomy()
    where, args, params = _scope(year_from, year_to, coalition)
    main_sql, main_args = topics.main_topic_clause()
    with db.session() as con:
        actors.init()
        counts = dict(con.execute(f"""SELECT t.topic, COUNT(DISTINCT d.id) FROM doc_topics t
                                      JOIN documents d ON d.id=t.doc_id JOIN sources s ON s.id=d.source_id
                                      WHERE {where} GROUP BY t.topic""", args).fetchall())
        totals = dict(con.execute(
            f"""SELECT a.key, COUNT(DISTINCT d.id) FROM doc_actors da JOIN actors a ON a.key=da.actor_key
                JOIN documents d ON d.id=da.doc_id JOIN sources s ON s.id=d.source_id
                WHERE {where} AND a.kind != 'country' AND {NOT_BEFORE_FOUNDED} GROUP BY a.key""", args).fetchall())
        cand: dict[str, list] = {}
        for t, info in tax["topics"].items():
            if info.get("meta"):
                continue
            for r in con.execute(
                    f"""SELECT a.key, a.label, a.kind, COUNT(DISTINCT d.id) n FROM doc_actors da
                        JOIN actors a ON a.key=da.actor_key JOIN documents d ON d.id=da.doc_id
                        JOIN sources s ON s.id=d.source_id
                        WHERE {where} AND a.kind != 'country' AND {NOT_BEFORE_FOUNDED} AND {main_sql}
                        GROUP BY a.key HAVING n >= ?""", (*args, *main_args, t, min_reports)):
                share = r["n"] / totals[r["key"]]
                cand.setdefault(t, []).append({**dict(r), "of": totals[r["key"]], "share": round(share, 4),
                                               "score": r["n"] * share})
    tops = {t: sorted(lst, key=lambda x: (-x["score"], x["label"]))[:per_topic] for t, lst in cand.items()}
    tree = {"name": "Library", "children": []}
    for ckey, cat in tax["categories"].items():
        kids = []
        for t in cat["topics"]:
            if tax["topics"][t].get("meta"):
                continue
            kids.append({"name": tax["topics"][t]["name"], "key": t, "value": counts.get(t, 0), "type": "topic",
                         "link": trends.docs_url(params, topic=t),
                         "children": [{"name": a["label"], "key": a["key"], "value": a["n"], "of": a["of"],
                                       "share": a["share"], "type": "actor", "kind": a["kind"],
                                       "link": trends.docs_url(params, topic=t, actor=a["key"], main=1),
                                       "all_link": trends.docs_url(params, actor=a["key"]),
                                       "actor": f"/actors/{a['key']}"} for a in tops.get(t, [])]})
        tree["children"].append({"name": cat["name"], "key": ckey, "type": "category",
                                 "value": sum(k["value"] for k in kids), "children": kids})
    return {"tree": tree, "filters": params, "per_topic": per_topic, "min_reports": min_reports,
            "how": (f"Categories and topics of the keyword index (sources/topics.yaml) with the number of reports in "
                    f"scope. Under each topic: the actors most characteristic of it. Counted are reports that have the "
                    f"topic among their {topics.MAIN_TOPICS} main topics (highest keyword score) and name the actor, "
                    f"ranked by that number × its share of all reports naming the actor; at least {min_reports}. "
                    "Countries are left out."),
            "generated": dt.datetime.now().isoformat(timespec="seconds")}
