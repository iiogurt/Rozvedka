"""What's new, update by update: the reports each update found, the actors named for the first time, the topics whose
share jumped – and an Atom feed of new reports.

An *update* is a day on which reports entered the library (`documents.discovered_at`): crawls run on demand, so a
day groups one update's crawl and downloads. Every count comes with the Documents link that lists exactly those
reports (`added_from`/`added_to` = the update's day).
"""
from . import actors, db, topics, trends
from .home import docs_url

LISTED = trends.LISTED
JUMP_MIN = 3          # a topic needs at least this many reports in the update to be listed as jumping
NOT_COUNTRY = "a.kind != 'country'"


def days(con) -> list[dict]:
    """All updates, newest first, with the number of reports each found."""
    return [{"day": r[0], "n": r[1], "url": docs_url(added_from=r[0], added_to=r[0], sort="added")}
            for r in con.execute(f"""SELECT date(d.discovered_at) day, COUNT(*) FROM documents d
                                      JOIN sources s ON s.id=d.source_id WHERE {LISTED} GROUP BY day ORDER BY day DESC""")]


def _main_topics(con, ids: list[int]) -> dict[int, list[str]]:
    tax = topics.taxonomy()["topics"]
    out: dict[int, list[str]] = {}
    if ids:
        for r in con.execute(f"""SELECT doc_id, topic FROM doc_topics WHERE doc_id IN ({','.join('?' * len(ids))})
                                 ORDER BY doc_id, score DESC, topic""", ids):
            if not tax.get(r[1], {}).get("meta") and len(out.setdefault(r[0], [])) < topics.MAIN_TOPICS:
                out[r[0]].append(r[1])
    return out


def _actors_of(con, ids: list[int], limit: int = 5) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    if ids:
        for r in con.execute(f"""SELECT da.doc_id, a.key, a.label FROM doc_actors da JOIN actors a ON a.key=da.actor_key
                                 JOIN documents d ON d.id=da.doc_id
                                 WHERE da.doc_id IN ({','.join('?' * len(ids))}) AND {NOT_COUNTRY} AND {actors.NOT_BEFORE_FOUNDED}
                                 ORDER BY da.doc_id, da.hits DESC, a.label""", ids):
            lst = out.setdefault(r[0], [])
            if len(lst) < limit:
                lst.append({"key": r[1], "label": r[2]})
    return out


def update(day: str | None = None) -> dict:
    """One update: its reports by agency, the actors first named in it, and the topics whose share jumped."""
    with db.session() as con:
        topics.init()
        actors.init()
        all_days = days(con)
        if not all_days:
            return {"days": [], "day": None}
        day = day if any(d["day"] == day for d in all_days) else all_days[0]["day"]
        prev = next((d["day"] for d in all_days if d["day"] < day), None)
        in_day = f"{LISTED} AND date(d.discovered_at) = ?"
        before = f"{LISTED} AND date(d.discovered_at) < ?"
        docs = [dict(r) for r in con.execute(
            f"""SELECT d.id, d.title, d.year, d.lang, d.status, d.url, d.local_path, s.id source_id, s.country, s.agency
                FROM documents d JOIN sources s ON s.id=d.source_id WHERE {in_day}
                ORDER BY s.country, s.agency, d.year DESC NULLS LAST, d.title""", (day,))]
        ids = [d["id"] for d in docs]
        main, named = _main_topics(con, ids), _actors_of(con, ids)
        agencies: list[dict] = []
        for d in docs:
            d["topics"], d["actors"] = main.get(d["id"], []), named.get(d["id"], [])
            if not agencies or agencies[-1]["source_id"] != d["source_id"]:
                agencies.append({"source_id": d["source_id"], "country": d["country"], "agency": d["agency"], "docs": [],
                                 "url": docs_url(source=d["source_id"], added_from=day, added_to=day)})
            agencies[-1]["docs"].append(d)
        # actors named for the first time: in this update's reports, and in no report found earlier
        first = [dict(r) for r in con.execute(
            f"""SELECT a.key, a.label, a.kind, COUNT(DISTINCT d.id) n FROM doc_actors da JOIN actors a ON a.key=da.actor_key
                JOIN documents d ON d.id=da.doc_id JOIN sources s ON s.id=d.source_id
                WHERE {in_day} AND {NOT_COUNTRY} AND {actors.NOT_BEFORE_FOUNDED}
                  AND a.key NOT IN (SELECT da2.actor_key FROM doc_actors da2 JOIN documents d ON d.id=da2.doc_id
                                    JOIN actors a ON a.key=da2.actor_key JOIN sources s ON s.id=d.source_id
                                    WHERE {before} AND {actors.NOT_BEFORE_FOUNDED})
                GROUP BY a.key ORDER BY n DESC, a.label""", (day, day))]
        for a in first:
            a["kind_name"] = actors.KINDS.get(a["kind"], a["kind"])
            a["url"] = docs_url(actor=a["key"], added_from=day, added_to=day)
            a["before_url"] = docs_url(actor=a["key"], added_to=prev) if prev else None
        # topics whose share among this update's reports is above their share in the library before it
        jumps = []
        n_in = len(docs)
        n_before = con.execute(f"SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id WHERE {before}",
                               (day,)).fetchone()[0]
        if n_in and n_before:
            tax = topics.taxonomy()["topics"]
            count = lambda where, arg: dict(con.execute(   # noqa: E731
                f"""SELECT t.topic, COUNT(*) FROM doc_topics t JOIN documents d ON d.id=t.doc_id JOIN sources s ON s.id=d.source_id
                    WHERE {where} GROUP BY t.topic""", (arg,)).fetchall())
            now_, then_ = count(in_day, day), count(before, day)
            for t, n in now_.items():
                if n < JUMP_MIN or tax.get(t, {}).get("meta") or t not in tax:
                    continue
                a, b = then_.get(t, 0) / n_before, n / n_in
                if b > a:
                    jumps.append({"key": t, "name": tax[t]["name"], "n": n, "share": b, "n_before": then_.get(t, 0),
                                  "share_before": a, "pp": round((b - a) * 100, 1),
                                  "url": docs_url(topic=t, added_from=day, added_to=day),
                                  "url_before": docs_url(topic=t, added_to=prev) if prev else None})
            jumps.sort(key=lambda j: -j["pp"])
    return {"days": all_days, "day": day, "prev": prev, "n": n_in, "n_before": n_before, "agencies": agencies, "docs": docs,
            "url": docs_url(added_from=day, added_to=day, sort="added"),
            "before_url": docs_url(added_to=prev) if prev else None,
            "first": first, "jumps": jumps[:12], "jump_min": JUMP_MIN}


def figures(u: dict) -> list[tuple[str, int, str]]:
    """Every (label, count, Documents link) on the page – checked by tools/check_links.py."""
    out = [(f"update {d['day']}", d["n"], d["url"]) for d in u["days"]]
    if u.get("day"):
        out.append(("this update", u["n"], u["url"]))
        if u["before_url"]:
            out.append(("before", u["n_before"], u["before_url"]))
        out += [(f"agency {g['agency']}", len(g["docs"]), g["url"]) for g in u["agencies"]]
        out += [(f"first {a['label']}", a["n"], a["url"]) for a in u["first"]]
        out += [(f"no earlier {a['label']}", 0, a["before_url"]) for a in u["first"] if a["before_url"]]
        out += [(f"jump {j['key']}", j["n"], j["url"]) for j in u["jumps"]]
        out += [(f"jump before {j['key']}", j["n_before"], j["url_before"]) for j in u["jumps"] if j["url_before"]]
    return out


def feed(base: str, limit: int = 50, watch: str = "") -> str:
    """Atom feed of the newest reports (by when they entered the library), with their main topics and actors;
    with `watch`, only the reports of that watchlist query."""
    from urllib.parse import urlencode
    from xml.sax.saxutils import escape as x

    from . import doclist, home
    where, args = LISTED, []
    if watch:
        parsed = home.parse(watch)
        f = doclist.build(**{k: v for k, v in parsed["params"].items() if v not in ("", None, [])})
        where, args = " AND ".join(f["where"]), f["args"]
    with db.session() as con:
        topics.init()
        actors.init()
        docs = [dict(r) for r in con.execute(
            f"""SELECT d.id, d.title, d.year, d.lang, d.url, d.local_path, d.discovered_at, s.country, s.agency, s.name_en
                FROM documents d JOIN sources s ON s.id=d.source_id WHERE {where}
                ORDER BY d.discovered_at DESC, d.id DESC LIMIT ?""", (*args, limit))]
        ids = [d["id"] for d in docs]
        main, named = _main_topics(con, ids), _actors_of(con, ids)
    tax = topics.taxonomy()["topics"]
    stamp = lambda s: (s or "1970-01-01 00:00:00").replace(" ", "T")[:19] + "Z"   # noqa: E731 – stored as UTC
    entries = []
    for d in docs:      # ids do not depend on the address the portal is opened with, so readers never see doubles
        link = f"{base}/doc/{d['id']}" if d["local_path"] else d["url"]
        bits = [f"{d['agency']} ({d['country']})", str(d["year"] or "year unknown"), (d["lang"] or "?").upper()]
        if main.get(d["id"]):
            bits.append("Topics: " + ", ".join(tax[t]["name"] for t in main[d["id"]] if t in tax))
        if named.get(d["id"]):
            bits.append("Names: " + ", ".join(a["label"] for a in named[d["id"]]))
        bits.append(f"Official source: {d['url']}")
        entries.append(f"""  <entry>
    <id>tag:rozvedka,2026:doc/{d['id']}</id>
    <title>{x(d['agency'])}: {x(d['title'] or '')}</title>
    <link href="{x(link)}"/>
    <link rel="related" href="{x(d['url'])}"/>
    <updated>{stamp(d['discovered_at'])}</updated>
    <author><name>{x(d['name_en'] or d['agency'])}</name></author>
    <summary>{x(' · '.join(bits))}</summary>
  </entry>""")
    updated = stamp(docs[0]["discovered_at"]) if docs else stamp(None)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>tag:rozvedka,2026:feed{x(('/watch/' + watch) if watch else '')}</id>
  <title>Rozvedka – {x(('watchlist: ' + watch) if watch else 'new reports')}</title>
  <subtitle>Reports found by the latest updates, newest first ({limit} at most)</subtitle>
  <link rel="self" href="{x(base)}/feed.atom{x(('?' + urlencode({'watch': watch})) if watch else '')}"/>
  <link href="{x(base)}{'/watch' if watch else '/new'}"/>
  <updated>{updated}</updated>
{chr(10).join(entries)}
</feed>
"""
