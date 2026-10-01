"""Data behind the Network, Geography and topic mind-map views.

Like the Trends pages, every node, link and country carries the link that lists exactly the documents (or
passages) it counts, and every result says how it was computed.
"""
import datetime as dt
import math
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


def npmi(n_ab: int, n_a: int, n_b: int, n: int) -> float:
    """Normalised pointwise mutual information of two actors over n reports: 0 = named together as often as chance
    predicts, 1 = only ever named together. Negative values (less than chance) are reported as 0."""
    if not (n_ab and n_a and n_b and n) or n_ab >= n:
        return 0.0
    p_ab, p_a, p_b = n_ab / n, n_a / n, n_b / n
    return max(0.0, math.log(p_ab / (p_a * p_b)) / -math.log(p_ab))


def cluster(keys: list[str], sim: dict[tuple[str, str], float], threshold: float) -> list[list[str]]:
    """Average-linkage agglomerative clustering on association strength; merging stops below `threshold`.
    Returns clusters in merge order (strongest first), members in a stable order."""
    groups = [[k] for k in keys]

    def link(g1, g2):
        return sum(sim.get((a, b) if a < b else (b, a), 0.0) for a in g1 for b in g2) / (len(g1) * len(g2))

    while len(groups) > 1:
        best, pair = -1.0, None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                v = link(groups[i], groups[j])
                if v > best:
                    best, pair = v, (i, j)
        if best < threshold:
            break
        i, j = pair
        groups[i] = groups[i] + groups[j]
        del groups[j]
    return groups


def associations(year_from=None, year_to=None, coalition="", type="", topic="", include_countries=False,
                 max_actors=60, min_pair=3, threshold=0.25, kinds: list[str] | None = None) -> dict:
    """Which actors the reports name together more often than their frequency predicts – clusters, matrix, ties.

    For the max_actors actors named in most reports in scope: n_ab = reports naming a and b in one passage
    (within actors.WINDOW characters), n_a / n_b = reports naming each, N = reports in scope; association = NPMI,
    counted only where n_ab >= min_pair. Clusters: average-linkage on association, stopped at `threshold`.
    """
    where, args, params = _scope(year_from, year_to, coalition, type, topic)
    kinds = [k for k in (kinds or []) if k in actors.KINDS and k != "country"]
    if include_countries and kinds:
        kinds.append("country")
    kind_sql = (f" AND a.kind IN ({','.join(repr(k) for k in kinds)})" if kinds
                else "" if include_countries else " AND a.kind != 'country'")
    qs = _qs({k: params.get(k) for k in ("year_from", "year_to", "coalition", "type", "topic")})
    with db.session() as con:
        actors.init()
        n_docs = con.execute(f"SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id WHERE {where}",
                             args).fetchone()[0]
        nodes = [dict(r) for r in con.execute(
            f"""SELECT a.key, a.label, a.kind, COUNT(DISTINCT da.doc_id) docs
                FROM doc_actors da JOIN actors a ON a.key=da.actor_key JOIN documents d ON d.id=da.doc_id
                JOIN sources s ON s.id=d.source_id
                WHERE {where} AND {NOT_BEFORE_FOUNDED}{kind_sql}
                GROUP BY a.key ORDER BY docs DESC, a.label LIMIT ?""", (*args, max_actors))]
        info = {n["key"]: n for n in nodes}
        keys = list(info)
        pairs = {}
        if keys:
            marks = ",".join("?" * len(keys))
            for r in con.execute(
                    f"""SELECT p.a, p.b, COUNT(DISTINCT p.doc_id) n FROM actor_pairs p
                        JOIN documents d ON d.id=p.doc_id JOIN sources s ON s.id=d.source_id
                        JOIN actors a1 ON a1.key=p.a JOIN actors a2 ON a2.key=p.b
                        WHERE p.a IN ({marks}) AND p.b IN ({marks}) AND {where} AND {PAIR_FOUNDED}
                        GROUP BY p.a, p.b""", (*keys, *keys, *args)):
                pairs[(r["a"], r["b"])] = r["n"]
        sim = {k: npmi(n, info[k[0]]["docs"], info[k[1]]["docs"], n_docs) for k, n in pairs.items() if n >= min_pair}
        groups = cluster(keys, sim, threshold)
        multi = [g for g in groups if len(g) > 1]
        single = [g[0] for g in groups if len(g) == 1]
        # matrix order: clusters (largest first), then the actors that belong to none
        multi.sort(key=lambda g: -sum(info[k]["docs"] for k in g))
        order = [k for g in multi for k in sorted(g, key=lambda k: -info[k]["docs"])] + \
            sorted(single, key=lambda k: -info[k]["docs"])
        clusters = [_cluster_summary(con, g, info, pairs, sim, where, args, params, qs, n_docs) for g in multi]
    cells = [{"a": a, "b": b, "docs": n, "npmi": round(sim.get((a, b), 0.0), 3),
              "link": f"/actors/{a}/with/{b}" + (f"?{qs}" if qs else "")} for (a, b), n in pairs.items()]
    for n in nodes:
        n["link"] = f"/actors/{n['key']}"
        n["docs_link"] = trends.docs_url(params, actor=n["key"])
        n["cluster"] = next((i for i, g in enumerate(multi) if n["key"] in g), None)
    return {"actors": [info[k] for k in order], "cells": cells, "clusters": clusters, "unclustered": len(single),
            "n_docs": n_docs, "filters": params, "kinds": actors.KINDS, "min_pair": min_pair, "threshold": threshold,
            "provenance": {
                "how": (f"The {len(nodes)} actors named in most of the {n_docs} reports in scope. Two actors are 'named "
                        f"together' in a report when they occur within {actors.WINDOW} characters of each other – "
                        "roughly one paragraph. Association is normalised pointwise mutual information (NPMI): 0 means "
                        "they are named together no more often than their frequency predicts, 1 that they are only "
                        f"ever named together; it is computed where they are named together in at least {min_pair} "
                        f"reports. Clusters join actors whose average association is at least {threshold}. Being "
                        "named together is not evidence of a connection – read the passages."),
                "generated": dt.datetime.now().isoformat(timespec="seconds"),
                "gazetteer": actors.stamp().get("gazetteer_retrieved")}}


def _cluster_summary(con, members, info, pairs, sim, where, args, params, qs, n_docs) -> dict:  # noqa: ARG001
    """What a cluster's reports are about: members, strongest ties, characteristic topics, years, agencies."""
    sql, sargs = actors.cluster_clause(members)
    docs = [dict(r) for r in con.execute(
        f"""SELECT d.id, d.year, s.id source_id, s.agency, s.country FROM documents d JOIN sources s ON s.id=d.source_id
            WHERE {where} AND {sql}""", (*args, *sargs))]
    ids = [d["id"] for d in docs]
    ties = sorted(((a, b) for (a, b) in pairs if a in members and b in members and (a, b) in sim),
                  key=lambda k: (-sim[k], -pairs[k]))
    topics_out, years, agencies = [], {}, {}
    if ids:
        marks = ",".join("?" * len(ids))
        tax = topics.taxonomy()["topics"]
        meta = [t for t, v in tax.items() if v.get("meta")]
        # main topics (highest keyword scores) say what a report is about; long annual reports carry every topic
        for r in con.execute(
                f"""SELECT topic, COUNT(*) n FROM (SELECT doc_id, topic, ROW_NUMBER() OVER (PARTITION BY doc_id
                        ORDER BY score DESC, topic) rk FROM doc_topics WHERE doc_id IN ({marks})
                        AND topic NOT IN ({','.join('?' * len(meta))}))
                    WHERE rk <= {topics.MAIN_TOPICS} GROUP BY topic ORDER BY n DESC""", (*ids, *meta)):
            if r["n"] < 2:
                continue
            topics_out.append({"key": r["topic"], "name": tax[r["topic"]]["name"], "docs": r["n"],
                               "share": round(r["n"] / len(ids), 3),
                               "link": trends.docs_url({**params, "cluster": ",".join(sorted(members))}, topic=r["topic"], main=1)})
        for d in docs:
            if d["year"]:
                years[d["year"]] = years.get(d["year"], 0) + 1
            g = agencies.setdefault(d["source_id"], {"agency": d["agency"], "country": d["country"], "docs": 0,
                                                     "link": trends.docs_url({**params, "cluster": ",".join(sorted(members)),
                                                                              "source": d["source_id"]})})
            g["docs"] += 1
    ordered = sorted(members, key=lambda k: -info[k]["docs"])
    return {"members": [{"key": k, "label": info[k]["label"], "kind": info[k]["kind"], "docs": info[k]["docs"]}
                        for k in ordered],
            "name": " · ".join(info[k]["label"] for k in ordered[:3]),
            "docs": len(ids), "docs_link": trends.docs_url({**params, "cluster": ",".join(sorted(members))}),
            "cohesion": round(sum(sim.get(t, 0) for t in ties) / max(1, len(members) * (len(members) - 1) / 2), 3),
            "ties": [{"a": a, "b": b, "la": info[a]["label"], "lb": info[b]["label"], "docs": pairs[(a, b)],
                      "npmi": round(sim[(a, b)], 2), "link": f"/actors/{a}/with/{b}" + (f"?{qs}" if qs else "")}
                     for a, b in ties[:4]],
            "topics": topics_out[:5], "years": sorted(years.items()),
            "agencies": sorted(agencies.values(), key=lambda g: -g["docs"])[:4]}


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
