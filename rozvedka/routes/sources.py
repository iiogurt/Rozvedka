"""Topics, sources, think tanks and the ratings of states."""
from fastapi import APIRouter, HTTPException, Request
from .. import actors, db, home, publishers, ratings, series, ties, topics, trends
from ..web import COUNTRY_NAMES, _independent, independent_ids, region_of, tpl

router = APIRouter()


@router.get("/topics")
def topics_page(request: Request):
    tax = topics.taxonomy()
    with db.session() as con:
        topics.init()
        rows = {r["topic"]: dict(r) for r in con.execute(
            """SELECT t.topic, COUNT(DISTINCT t.doc_id) AS docs, COUNT(DISTINCT d.source_id) AS sources,
                      COUNT(DISTINCT s.country) AS countries, MIN(d.year) AS y0, MAX(d.year) AS y1
               FROM doc_topics t JOIN documents d ON d.id=t.doc_id JOIN sources s ON s.id=d.source_id
               WHERE d.hidden=0 AND s.active=1 GROUP BY t.topic""")}
        indexed = con.execute("SELECT COUNT(*), SUM(taxonomy_hash IS NOT NULL) FROM doc_index").fetchone()
    return tpl.TemplateResponse(request, "topics.html", {"tax": tax, "stats": rows, "indexed": indexed})


@router.get("/sources")
def sources(request: Request):
    with db.session() as con:
        rows = con.execute(
            """SELECT s.*, COUNT(d.id) n_docs, SUM(d.status='downloaded') n_ok
               FROM sources s LEFT JOIN documents d ON d.source_id=s.id AND d.hidden=0
               WHERE s.active=1 GROUP BY s.id ORDER BY s.country, s.agency""").fetchall()
        pages = {}
        for p in con.execute("SELECT * FROM pages WHERE active=1 ORDER BY lang, kind"):
            pages.setdefault(p["source_id"], []).append(p)
    # countries by region (EU members first), alphabetically by name within a region
    # official agencies by region (EU members first); think tanks and commercial analysts each in a section of their own
    official = [r for r in rows if (r["publisher"] or "official") == "official"]
    independent = [r for r in rows if (r["publisher"] or "official") == "independent"]
    commercial = [r for r in rows if r["publisher"] == "commercial"]

    def by_country(items):
        groups: dict[str, list] = {}
        for r in items:
            groups.setdefault(r["country"], []).append(r)
        return sorted(groups.items(), key=lambda kv: (region_of(kv[0])[0], COUNTRY_NAMES.get(kv[0], kv[0])))
    ordered = by_country(official)
    regions: list[tuple[str, list, str]] = []     # (heading, countries, kind of publisher: "" = official agencies)
    for country, items in ordered:
        name = region_of(country)[1]
        if not regions or regions[-1][0] != name:
            regions.append((name, [], ""))
        regions[-1][1].append((country, items))
    if independent:
        regions.append(("Independent publishers – think tanks", by_country(independent), "independent"))
    if commercial:
        regions.append(("Commercial analysts – companies", by_country(commercial), "commercial"))
    return tpl.TemplateResponse(request, "sources.html", {"sources": rows, "groups": ordered, "regions": regions,
                                                         "n_official": len(official), "n_independent": len(independent),
                                                         "n_commercial": len(commercial),
                                                         "pages": pages, "series_by": series.by_source()})


@router.get("/sources/grid")
def coverage_grid(request: Request):
    """Every state against the national agency types: covered, checked and found not published, or open."""
    from .. import gaps
    return tpl.TemplateResponse(request, "coverage_grid.html", {"g": gaps.grid()})


@router.get("/publishers")
def publishers_page(request: Request):
    """Every publisher that is not a state – think tanks, then commercial analysts – with its credibility rating and checks."""
    independent_ids()
    with db.session() as con:
        rows = [dict(r) for r in con.execute(
            f"""SELECT src.id, src.key, src.country, src.agency, src.name_en, src.homepage, src.access,
                       (SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                        WHERE {trends.LISTED} AND d.source_id=src.id) n,
                       src.publisher
                FROM sources src WHERE src.active=1 AND COALESCE(src.publisher, 'official') != 'official'""")]
    order = list(publishers.LEVELS)
    for r in rows:
        r["profile"] = _independent["levels"].get(r["id"]) or publishers.profile(r["key"], r["publisher"])
    rows.sort(key=lambda r: (order.index(r["profile"]["level"]), r["agency"]))
    kinds = [(k, spec, [r for r in rows if r["publisher"] == k]) for k, spec in publishers.KINDS.items()]
    return tpl.TemplateResponse(request, "publishers.html", {"rows": rows, "kinds": kinds, "docs_url": home.docs_url,
                                                           "meta": publishers.load()})


@router.get("/publisher/{source_id}")
def publisher_page(request: Request, source_id: int):
    """One think tank or commercial analyst: credibility checks with evidence, identity, registers, owners and sponsors,
    its state, and its reports here."""
    with db.session() as con:
        topics.init()
        actors.init()
        s = con.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        if s is None or s["publisher"] not in publishers.KINDS:
            raise HTTPException(404, "not a think tank or commercial analyst")
        s = dict(s)
        base = f"FROM documents d JOIN sources s ON s.id=d.source_id WHERE {trends.LISTED} AND d.source_id=?"
        n = con.execute(f"SELECT COUNT(*) {base}", (source_id,)).fetchone()[0]
        by_year = con.execute(f"SELECT d.year, COUNT(*) {base} AND d.year IS NOT NULL GROUP BY d.year ORDER BY d.year DESC",
                              (source_id,)).fetchall()
        tax = topics.taxonomy()["topics"]
        top_topics = [(t, tax[t]["name"], c) for t, c in con.execute(
            f"""SELECT t.topic, COUNT(*) c FROM doc_topics t JOIN documents d ON d.id=t.doc_id JOIN sources s ON s.id=d.source_id
                WHERE {trends.LISTED} AND d.source_id=? GROUP BY t.topic ORDER BY c DESC""", (source_id,))
            if t in tax and not tax[t].get("meta")][:12]
        top_actors = [dict(r) for r in con.execute(
            f"""SELECT a.key, a.label, a.kind, COUNT(DISTINCT d.id) c FROM doc_actors da JOIN actors a ON a.key=da.actor_key
                JOIN documents d ON d.id=da.doc_id JOIN sources s ON s.id=d.source_id
                WHERE {trends.LISTED} AND d.source_id=? AND a.kind != 'country' AND {actors.NOT_BEFORE_FOUNDED}
                  AND a.label NOT IN (?, ?) GROUP BY a.key ORDER BY c DESC, a.label LIMIT 15""",
            (source_id, s["agency"], s["name_en"] or s["agency"]))]
        latest = [dict(r) for r in con.execute(
            f"SELECT d.id, d.title, d.year, d.lang {base} ORDER BY d.year DESC NULLS LAST, d.id DESC LIMIT 10", (source_id,))]
        pages = [dict(r) for r in con.execute("SELECT * FROM pages WHERE source_id=? AND active=1", (source_id,))]
    return tpl.TemplateResponse(request, "publisher.html", {
        "s": s, "p": publishers.profile(s["key"], s["publisher"]), "kind": publishers.KINDS[s["publisher"]],
        "ties": ties.publisher_node(s["key"]), "n": n, "by_year": by_year, "top_topics": top_topics,
        "top_actors": top_actors, "latest": latest, "pages": pages, "docs_url": home.docs_url,
        "max_year": max((c for _, c in by_year), default=1), "kinds": actors.KINDS})


@router.get("/ratings")
def ratings_page(request: Request, sort: str = "", group: str = "democracy"):
    """Ratings of the library's states over time, one group at a time (democracy, security, governance), with the
    number of official reports from each state."""
    group = group if group in ratings.GROUPS else "democracy"
    with db.session() as con:
        n_docs = dict(con.execute(f"""SELECT s.country, COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                                      WHERE {trends.LISTED} AND {trends.OFFICIAL} GROUP BY s.country""").fetchall())
    rows = [p | {"name": COUNTRY_NAMES.get(c, c), "n_docs": n_docs.get(c, 0)}
            for c in sorted(COUNTRY_NAMES) if (p := ratings.profile(c))]
    measures = ratings.of_group(group)
    if group == "democracy":
        sort = sort or "ldi"
        key = {"ldi": lambda r: -(r["measures"].get("vdem_libdem", {}).get("latest") or (0, -9))[1],
               "change": lambda r: _ldi_change(r), "name": lambda r: r["name"]}.get(sort, lambda r: r["name"])
    else:
        sort = sort if sort in measures or sort == "name" else next(iter(measures))
        # by its place among the states (the better end first), unrated states last
        key = (lambda r: r["name"]) if sort == "name" else \
            (lambda r: ((r["measures"].get(sort) or {}).get("rank") or (10**6, 0))[0])
    rows.sort(key=key)
    return tpl.TemplateResponse(request, "ratings.html", {"rows": rows, "sort": sort, "MEASURES": ratings.MEASURES,
                                                         "group": group, "GROUPS": ratings.GROUPS, "measures": measures,
                                                         "meta": ratings.load(), "docs_url": home.docs_url})


@router.get("/ratings/{country}")
def ratings_country(request: Request, country: str):
    """Every rating of one state: one small chart per measure on its own scale, with the latest value, the state's
    place among the library's states, the source, and the state's official reports on the matching topic."""
    country = country.upper()
    p = ratings.profile(country)
    if not p or country not in COUNTRY_NAMES:
        raise HTTPException(404, "no ratings for this state")
    tax = topics.taxonomy()["topics"]
    with db.session() as con:
        topics.init()
        n_topic = dict(con.execute(f"""SELECT t.topic, COUNT(DISTINCT d.id) FROM doc_topics t JOIN documents d ON d.id=t.doc_id
                                       JOIN sources s ON s.id=d.source_id
                                       WHERE {trends.LISTED} AND {trends.OFFICIAL} AND s.country=? GROUP BY t.topic""",
                                   (country,)).fetchall())
    groups = [(g, name, about, [p["measures"][k] | {"topic_name": tax.get(m.get("topic") or "", {}).get("name"),
                                                     "n_topic": n_topic.get(m.get("topic"), 0)}
                                for k, m in ratings.of_group(g).items() if k in p["measures"]])
              for g, (name, about) in ratings.GROUPS.items()]
    return tpl.TemplateResponse(request, "ratings_country.html", {
        "p": p, "country": country, "name": COUNTRY_NAMES[country], "groups": groups, "meta": ratings.load(),
        "docs_url": home.docs_url})


def _ldi_change(r: dict) -> float:
    """Change of the Liberal Democracy Index over the last ten years (most negative first)."""
    ldi = r["measures"].get("vdem_libdem")
    if not ldi or not ldi["spark"]:
        return 0.0
    s = dict(ldi["spark"])
    last = max(s)
    before = [y for y in s if y <= last - 10] or [min(s)]      # ten years earlier, or the earliest year known
    return s[last] - s[max(before)]
