"""Maps and graphs: network, democracy, mentions, topic map, headquarters map."""
from fastapi import APIRouter, Request
from .. import countries, db, graphs, ratings, topics, trends
from ..web import COUNTRY_NAMES, TYPE_NAMES, _abs, _csv, _years_desc, coalition_members_of, flag_url, in_coalition_order, pub_profile, tpl

router = APIRouter()


@router.get("/map/democracy")
def democracy_map_page(request: Request):
    return tpl.TemplateResponse(request, "map_democracy.html", {"MEASURES": ratings.MEASURES, "GROUPS": ratings.GROUPS})


@router.get("/api/ratings/map")
def api_ratings_map():
    """The ratings of every country per year (democracy, security, governance), plus the library's official reports per country and year (each
    count is the Documents list /documents?country=…&year=…&type=official)."""
    data = ratings.map_data()
    with db.session() as con:
        reports: dict[str, dict] = {}
        for c, y, n in con.execute(f"""SELECT s.country, d.year, COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                                       WHERE {trends.LISTED} AND {trends.OFFICIAL} AND d.year IS NOT NULL
                                       GROUP BY s.country, d.year"""):
            reports.setdefault(c, {})[str(y)] = n
    data["reports"] = reports
    return data


@router.get("/map/mentions")
def mentions_page(request: Request):
    return tpl.TemplateResponse(request, "mentions.html", {"years": _years_desc(),
                                                         "reporting": sorted(COUNTRY_NAMES.items(), key=lambda x: x[1])})


@router.get("/api/mentions")
def api_mentions(request: Request, mode: str = "about", target: str = "", year_from: int = 0, year_to: int = 0,
                 type: str = "", format: str = "json"):
    d = graphs.geography("from" if mode == "from" else "about", target, year_from or None, year_to or None, type)
    if format != "csv":
        return d
    return _csv(f"mentions-{mode}-{target}", ["country", "iso", "reports_naming", "reports_in_scope", "share", "source_documents"],
                ([r["name"], r["iso"], r["docs"], r["of"], r["share"], _abs(request, r["link"])] for r in d["rows"]))


@router.get("/topics/map")
def topic_map_page(request: Request):
    return tpl.TemplateResponse(request, "topic_map.html", {"years": _years_desc()})


@router.get("/api/topics/tree")
def api_topic_tree(coalition: str = "", year_from: int = 0, year_to: int = 0, per_topic: int = 6):
    return graphs.topic_tree(max(0, min(per_topic, 12)), coalition, year_from or None, year_to or None)


@router.get("/api/events")
def api_events():
    return trends.events()


@router.get("/map")
def world_map(request: Request):
    return tpl.TemplateResponse(request, "map.html", {"TYPE_NAMES": TYPE_NAMES})


@router.get("/api/map")
def map_data(topic: str = ""):
    """Agencies with HQ coordinates and document counts (optionally only documents on one topic),
    plus per-country totals for shading."""
    topic = topic if topic in topics.taxonomy()["topics"] else ""
    with db.session() as con:
        topics.init()
        rows = con.execute(
            """SELECT s.id, s.country, s.agency, s.name_en, s.name_local, s.type, s.description, s.homepage,
                      s.hq_address, s.lat, s.lon, s.hq_precision, s.logo_path,
                      COUNT(d.id) AS n_docs, COALESCE(SUM(d.status='downloaded'), 0) AS n_ok,
                      MIN(d.year) AS y0, MAX(d.year) AS y1
               FROM sources s LEFT JOIN documents d ON d.source_id=s.id AND d.hidden=0
                    AND (? = '' OR d.id IN (SELECT doc_id FROM doc_topics WHERE topic = ?))
               WHERE s.active=1 GROUP BY s.id""", (topic, topic)).fetchall()
    agencies = [{**dict(r), "flag": flag_url(r["country"]), "logo": f"/logo/{r['id']}" if r["logo_path"] else None,
                 "type_name": TYPE_NAMES.get(r["type"], r["type"]),
                 "credibility": (pub_profile(r["id"]) or {}).get("level"),       # think tanks, commercial analysts: rating colour of the diamond / square
                 "credibility_label": (pub_profile(r["id"]) or {}).get("label"),
                 "country_name": COUNTRY_NAMES.get(r["country"], r["country"]),
                 "coalitions": in_coalition_order(coalition_members_of(r["country"]))}
                for r in rows if r["lat"] is not None]
    per_country: dict[str, dict] = {}
    for r in rows:
        if r["country"] in ("EU", "NATO", "OTHER"):
            continue   # organisations, not territories
        c = per_country.setdefault(r["country"], {"name": COUNTRY_NAMES.get(r["country"], r["country"]),
                                                  "agencies": 0, "docs": 0,
                                                  "coalitions": in_coalition_order(countries.memberships(r["country"]))})
        c["agencies"] += 1
        c["docs"] += r["n_docs"]
    tax = topics.taxonomy()
    return {"agencies": agencies, "countries": per_country, "topic": topic,
            "topic_list": [{"key": k, "name": tax["topics"][k]["name"], "category": c["name"]}
                           for c in tax["categories"].values() for k in c["topics"]],
            "coalitions": {k: {"short": v["short"], "name": v["name"]} for k, v in countries.coalitions().items()}}


