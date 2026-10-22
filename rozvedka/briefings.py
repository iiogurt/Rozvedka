"""Briefing pages: one topic, or one country, on one page – what the library's reports say about it, with every number
opening the Documents list it counts.

A topic (/topics/{key}): its reports year by year (official agencies, think tanks and commercial analysts apart), the
countries and agencies that write most about it, the actors and other topics its reports emphasise (lift: how much more
often than in all reports – not raw frequency, which favours the actors every report names), and its newest reports with
the words that tagged them.

A country (/countries/{code}): its agencies and their reports, the topics and actors its official reports emphasise
compared with all official reports, who else reports about it, and its ratings, threat level and events.

Counted as everywhere (rozvedka/trends.py): listed reports, one file per report, classified by the topic index.
"""
import datetime as dt
import json
import math

from . import actors, countries, db, ratings, ties, topics, trends
from .trends import CLASSIFIED, COMMERCIAL, LISTED, OFFICIAL, THINK_TANK, docs_url

MIN_DOCS = 3            # an actor or topic needs this many reports in the briefing's set to be ranked by lift
TOP = 15
NEWEST = 12
KINDS = {"official": ("official agencies", OFFICIAL), "think-tank": ("think tanks ◆", THINK_TANK),
         "commercial": ("commercial analysts ■", COMMERCIAL)}


def _base(con, where: str, args: list) -> int:
    return con.execute(f"SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id WHERE {where}", args).fetchone()[0]


def _years(con, where: str, args: list, params: dict) -> list[dict]:
    """Reports per year in the set, by kind of publisher, with the share of all official reports that year."""
    now = dt.date.today().year
    rows: dict[int, dict] = {}
    for r in con.execute(f"""SELECT d.year y, COALESCE(s.publisher, 'official') p, COUNT(*) n
                             FROM documents d JOIN sources s ON s.id=d.source_id
                             WHERE {where} AND d.year BETWEEN ? AND ? GROUP BY d.year, p""", (*args, trends.MIN_YEAR, now)):
        rows.setdefault(r["y"], {})["think-tank" if r["p"] == "independent" else r["p"]] = r["n"]
    if not rows:
        return []
    den = dict(con.execute(f"""SELECT d.year, COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                               WHERE {LISTED} AND {CLASSIFIED} AND {OFFICIAL} AND d.year BETWEEN ? AND ? GROUP BY d.year""",
                           (min(rows), max(rows))).fetchall())
    out = []
    for y in range(min(rows), max(rows) + 1):
        r = rows.get(y, {})
        out.append({"year": y, "official": r.get("official", 0), "independent": r.get("think-tank", 0) + r.get("commercial", 0),
                    "share": round(r.get("official", 0) / den[y], 4) if den.get(y) else None, "of": den.get(y, 0),
                    "link": docs_url(params, year=y, type="official"), "link_all": docs_url(params, year=y)})
    return out


def _lift(con, kind: str, where: str, args: list, n_set: int, where_all: str, args_all: list, n_all: int,
          skip=frozenset()) -> list[dict]:
    """Actors (not countries) or topics named in the set's reports, by how much more often than in all reports."""
    if kind == "actor":
        q = """SELECT x.actor_key k, COUNT(DISTINCT d.id) n FROM doc_actors x JOIN actors a ON a.key=x.actor_key
               JOIN documents d ON d.id=x.doc_id JOIN sources s ON s.id=d.source_id
               WHERE a.kind != 'country' AND {w} GROUP BY x.actor_key"""
    else:
        q = """SELECT x.topic k, COUNT(DISTINCT d.id) n FROM doc_topics x JOIN documents d ON d.id=x.doc_id
               JOIN sources s ON s.id=d.source_id WHERE {w} GROUP BY x.topic"""
    here = {r["k"]: r["n"] for r in con.execute(q.format(w=where), args)}
    every = {r["k"]: r["n"] for r in con.execute(q.format(w=where_all), args_all)}
    out = []
    for k, n in here.items():
        if n >= MIN_DOCS and every.get(k) and k not in skip:
            lift = (n / n_set) / (every[k] / n_all)
            if lift > 1:          # ranked by n × log2(lift): over-emphasised, and not only in a handful of reports
                out.append({"key": k, "n": n, "share": n / n_set, "all": every[k], "lift": lift, "score": n * math.log2(lift)})
    return sorted(out, key=lambda r: (-r["score"], -r["n"]))[:TOP]


def topic(key: str) -> dict | None:
    tax = topics.taxonomy()
    if key not in tax["topics"]:
        return None
    t = tax["topics"][key]
    where, args, params = trends.scope()
    tw = f"{where} AND {CLASSIFIED} AND d.id IN (SELECT doc_id FROM doc_topics WHERE topic=?)"
    ta = [*args, key]
    p = {**params, "topic": key}
    with db.session() as con:
        topics.init()
        actors.init()
        n = _base(con, tw, ta)
        n_all = _base(con, f"{where} AND {CLASSIFIED}", args)
        kinds = [{"key": k, "name": name, "n": _base(con, f"{tw} AND {cond}", ta), "link": docs_url(p, type=k)}
                 for k, (name, cond) in KINDS.items()]
        years = _years(con, tw, ta, p)
        official_all = _base(con, f"{where} AND {CLASSIFIED} AND {OFFICIAL}", args)
        by_country = [dict(r) for r in con.execute(
            f"""SELECT s.country, COUNT(*) n FROM documents d JOIN sources s ON s.id=d.source_id
                WHERE {tw} AND {OFFICIAL} GROUP BY s.country ORDER BY n DESC LIMIT ?""", (*ta, TOP))]
        tot_country = dict(con.execute(f"""SELECT s.country, COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                                          WHERE {where} AND {CLASSIFIED} AND {OFFICIAL} GROUP BY s.country""", args).fetchall())
        for r in by_country:
            r.update(name=countries.names().get(r["country"], r["country"]), of=tot_country.get(r["country"], 0), link=docs_url(p, country=r["country"], type="official"))
        by_agency = [dict(r) for r in con.execute(
            f"""SELECT s.id, s.agency, s.country, COALESCE(s.publisher, 'official') publisher, COUNT(*) n
                FROM documents d JOIN sources s ON s.id=d.source_id WHERE {tw}
                GROUP BY s.id ORDER BY n DESC, s.agency LIMIT ?""", (*ta, TOP))]
        for r in by_agency:
            r["link"] = docs_url(p, source=r["id"])
        labels = dict(con.execute("SELECT key, label FROM actors").fetchall())
        kinds_of = dict(con.execute("SELECT key, kind FROM actors").fetchall())
        acts = _lift(con, "actor", tw, ta, n, f"{where} AND {CLASSIFIED}", args, n_all)
        for r in acts:
            r.update(label=labels.get(r["key"], r["key"]), kind=kinds_of.get(r["key"]), link=docs_url(p, actor=r["key"]),
                     href=f"/actors/{r['key']}")
        rel = [r for r in _lift(con, "topic", tw, ta, n, f"{where} AND {CLASSIFIED}", args, n_all) if r["key"] != key]
        for r in rel:
            r.update(label=tax["topics"].get(r["key"], {}).get("name", r["key"]), link=docs_url(p, topic=[key, r["key"]]),
                     href=f"/topics/{r['key']}")
        newest = [dict(r) for r in con.execute(
            f"""SELECT d.id, d.title, d.year, s.agency, s.country, COALESCE(s.publisher, 'official') publisher, x.terms, x.score
                FROM documents d JOIN sources s ON s.id=d.source_id JOIN doc_topics x ON x.doc_id=d.id AND x.topic=?
                WHERE {tw} ORDER BY d.year DESC, d.discovered_at DESC LIMIT ?""", (key, *ta, NEWEST))]
    for r in newest:                                   # the words that tagged it: [[term, hits], …] or [term, …]
        try:
            ts = json.loads(r["terms"] or "[]")
        except ValueError:
            ts = []
        r["terms"] = [x[0] if isinstance(x, list) else x for x in ts][:5]
    cat = next((c for c in tax["categories"].values() if key in c["topics"]), {})
    return {"key": key, "name": t["name"], "category": cat.get("name", ""), "terms": t.get("terms") or t.get("keywords") or [],
            "n": n, "link": docs_url(p), "n_all": n_all, "official_all": official_all, "kinds": kinds, "years": years,
            "countries": by_country, "agencies": by_agency, "actors": acts, "related": rel, "newest": newest,
            "min_docs": MIN_DOCS, "trend_link": f"/trends?topic={key}", "compare_link": f"/compare?topic={key}"}


def country(code: str) -> dict | None:
    code = code.upper()
    names = countries.names()
    with db.session() as con:
        topics.init()
        actors.init()
        srcs = [dict(r) for r in con.execute(
            f"""SELECT s.id, s.agency, s.name_en, s.type, COALESCE(s.publisher, 'official') publisher,
                       (SELECT COUNT(*) FROM documents d WHERE d.source_id=s.id AND {LISTED.replace('s.active=1', '1=1')}) n
                FROM sources s WHERE s.country=? AND s.active=1 ORDER BY n DESC, s.agency""", (code,))]
        if not srcs and code not in names:
            return None
        where, args, params = trends.scope(country=code)
        cw, ca = f"{where} AND {CLASSIFIED} AND {OFFICIAL}", args
        p = {**params, "type": "official"}
        for s in srcs:
            s["link"] = f"/documents?source={s['id']}"
        n = _base(con, cw, ca)
        aw, aa = f"{LISTED} AND {CLASSIFIED} AND {OFFICIAL}", []
        n_all = _base(con, aw, aa)
        years = _years(con, f"{where} AND {CLASSIFIED}", args, params)
        tax = topics.taxonomy()["topics"]
        tps = _lift(con, "topic", cw, ca, n, aw, aa, n_all) if n else []
        for r in tps:
            r.update(label=tax.get(r["key"], {}).get("name", r["key"]), link=docs_url(p, topic=r["key"]), href=f"/topics/{r['key']}")
        labels = dict(con.execute("SELECT key, label FROM actors").fetchall())
        kinds_of = dict(con.execute("SELECT key, kind FROM actors").fetchall())
        own = {r["key"] for r in con.execute("SELECT key, data FROM actors WHERE kind='state'")
               if any(c.get("iso") == code for c in json.loads(r["data"] or "{}").get("countries") or [])}
        acts = _lift(con, "actor", cw, ca, n, aw, aa, n_all, skip=own) if n else []     # not the state's own agencies
        for r in acts:
            r.update(label=labels.get(r["key"], r["key"]), kind=kinds_of.get(r["key"]), link=docs_url(p, actor=r["key"]),
                     href=f"/actors/{r['key']}")
        me = con.execute("SELECT key, label FROM actors WHERE kind='country' AND iso=?", (code,)).fetchone()
        about = []
        if me:                                          # other states' official reports that name this one
            about = [dict(r) for r in con.execute(
                f"""SELECT s.country, COUNT(DISTINCT d.id) n FROM doc_actors x JOIN documents d ON d.id=x.doc_id
                    JOIN sources s ON s.id=d.source_id
                    WHERE x.actor_key=? AND s.country != ? AND {LISTED} AND {CLASSIFIED} AND {OFFICIAL}
                    GROUP BY s.country ORDER BY n DESC LIMIT ?""", (me["key"], code, TOP))]
            for r in about:
                r.update(name=names.get(r["country"], r["country"]), link=docs_url({"type": "official"}, country=r["country"], actor=me["key"]))
        newest = [dict(r) for r in con.execute(
            f"""SELECT d.id, d.title, d.year, s.agency FROM documents d JOIN sources s ON s.id=d.source_id
                WHERE {where} AND {OFFICIAL} ORDER BY d.year DESC, d.discovered_at DESC LIMIT ?""",
            (*args, NEWEST))]
    prof = ratings.profile(code) or {}
    regime = (prof.get("measures") or {}).get("vdem_regime")
    return {"code": code, "name": names.get(code, code), "sources": srcs, "n": n, "link": docs_url(p), "n_all": n_all,
            "years": years, "topics": tps, "actors": acts, "about": about, "me": dict(me) if me else None,
            "about_link": f"/actors/{me['key']}" if me else "", "newest": newest, "regime": regime,
            "has_ratings": bool(prof), "coalitions": countries.memberships(code), "min_docs": MIN_DOCS, "own": len(own),
            "events_link": f"/events?country={code}", "threat_link": f"/threat-levels#{code}"}


def index() -> list[dict]:
    """Every state with agencies in the library: its agencies and official reports."""
    names = countries.names()
    with db.session() as con:
        rows = [dict(r) for r in con.execute(
            f"""SELECT s.country, COUNT(DISTINCT s.id) agencies, COUNT(DISTINCT CASE WHEN {LISTED} AND {OFFICIAL} THEN d.id END) n
                FROM sources s LEFT JOIN documents d ON d.source_id=s.id WHERE s.active=1
                GROUP BY s.country ORDER BY s.country""")]
    for r in rows:
        r.update(name=names.get(r["country"], r["country"]), href=f"/countries/{r['country']}",
                 link=docs_url({"type": "official"}, country=r["country"]))
    return sorted(rows, key=lambda r: r["name"])


def figures(topic_key: str, code: str) -> list[tuple[str, int, str]]:
    """(label, number, Documents link) of one topic's and one country's briefing, for tools/check_links.py."""
    out = []
    t = topic(topic_key)
    if t:
        out.append((f"topic {topic_key}", t["n"], t["link"]))
        out += [(f"topic {topic_key} {k['key']}", k["n"], k["link"]) for k in t["kinds"]]
        out += [(f"topic {topic_key} {r['country']}", r["n"], r["link"]) for r in t["countries"][:5]]
        out += [(f"topic {topic_key} actor {r['key']}", r["n"], r["link"]) for r in t["actors"][:5]]
        out += [(f"topic {topic_key} {y['year']}", y["official"], y["link"]) for y in t["years"][-3:]]
    c = country(code)
    if c:
        out.append((f"country {code}", c["n"], c["link"]))
        out += [(f"country {code} topic {r['key']}", r["n"], r["link"]) for r in c["topics"][:5]]
        out += [(f"country {code} actor {r['key']}", r["n"], r["link"]) for r in c["actors"][:5]]
        out += [(f"country {code} named by {r['country']}", r["n"], r["link"]) for r in c["about"][:5]]
    return out
