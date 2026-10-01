"""Web portal: browse, filter, download and add security reports."""
import csv
import datetime as dt
import io
import threading
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from markupsafe import escape

from . import (__version__, actors, build_version, countries, crawler, db, downloader, graphs, logos, paging,
               registry, topics, trends)
from .config import FILES

HERE = Path(__file__).parent
app = FastAPI(title="Rozvedka", version=__version__)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
tpl = Jinja2Templates(directory=HERE / "templates")

COUNTRY_NAMES = countries.names()
region_of = countries.region_of
TYPE_NAMES = {
    "intelligence-civil": "Civil intelligence", "intelligence-military": "Military / foreign intelligence",
    "cyber": "Cyber security", "civil-protection": "Civil protection & crisis", "police-ct": "Police / counter-terrorism",
    "eu-body": "EU body", "nato": "NATO", "other": "Other",
}
FLAGS = {p.stem for p in (HERE / "static" / "flags").glob("*.svg")}


def flag_url(country: str) -> str:
    code = (country or "").lower()
    return f"/static/flags/{code if code in FLAGS else 'other'}.svg"


def initials(agency: str) -> str:
    """Badge text for agencies without a logo: 'NBÚ' -> 'NBÚ', 'Dept. of the Taoiseach' -> 'DT'."""
    words = [w for w in agency.replace("/", " ").split() if w[:1].isalpha()]
    if len(words) == 1:
        return words[0][:4]
    return "".join(w[0] for w in words if w[0].isupper())[:4] or agency[:3]


def coalition_scope(coalition: str) -> set[str]:
    return countries.scope(coalition)


def coalition_members_of(country: str) -> set[str]:
    """Coalitions a registry entry belongs to (EU bodies count as EU, NATO bodies as NATO)."""
    return set(countries.memberships(country)) | ({country} if country in ("EU", "NATO") else set())


def in_coalition_order(keys) -> list[str]:
    """Coalition keys in the display order of countries.yaml (EU, NATO, Five Eyes, …)."""
    order = list(countries.coalitions())
    return sorted(keys, key=lambda k: order.index(k) if k in order else len(order))


def coalition_tags(country: str) -> list[dict]:
    """Coalition chips for a country, in the order of countries.yaml."""
    mine = countries.memberships(country)
    return [{"key": k, "short": c["short"], "name": c["name"], "since": mine[k]}
            for k, c in countries.coalitions().items() if k in mine]


tpl.env.globals.update(COUNTRY_NAMES=COUNTRY_NAMES, TYPE_NAMES=TYPE_NAMES, flag_url=flag_url, initials=initials,
                       coalition_tags=coalition_tags, COALITIONS=countries.coalitions(), VERSION=__version__,
                       BUILD=build_version())

_jobs: dict[str, str] = {}      # background job name -> status text
_jobs_lock = threading.Lock()


def _run_job(name: str, fn, *args):
    def target():
        try:
            result = fn(*args)
            status = f"finished: {result}"
        except Exception as e:  # noqa: BLE001 - surface any failure in the UI
            status = f"failed: {type(e).__name__}: {e}"
        with _jobs_lock:
            _jobs[name] = status
    with _jobs_lock:
        if _jobs.get(name, "").startswith("running"):
            return False
        _jobs[name] = "running…"
    threading.Thread(target=target, daemon=True).start()
    return True


@app.on_event("startup")
def startup():
    db.init()
    registry.sync()


@app.get("/")
def index(request: Request, country: str = "", type: str = "", lang: str = "", year: str = "",
          status: str = "", q: str = "", source: int = 0, page: str = "1", per_page: str = "", show_hidden: int = 0,
          coalition: str = "", topic: list[str] = Query(default=[]), sort: str = "",
          year_from: str = "", year_to: str = "", indexed: int = 0, actor: str = "", main: int = 0,
          cluster: str = ""):
    tax = topics.taxonomy()["topics"]
    chosen = [t for t in topic if t in tax]
    where, args = ["s.active=1"], []
    if coalition in countries.coalitions():
        codes = sorted(coalition_scope(coalition))
        where.append(f"s.country IN ({','.join('?' * len(codes))})"); args += codes
    if not show_hidden:
        where.append("d.hidden=0 AND d.status NOT IN ('missing','duplicate','skipped')")
    for col, val in (("s.country", country), ("s.type", type), ("d.lang", lang), ("d.status", status)):
        if val:
            where.append(f"{col}=?"); args.append(val)
    if year:
        where.append("d.year=?"); args.append(int(year))
    if year_from.strip().isdigit():
        where.append("d.year>=?"); args.append(int(year_from))
    if year_to.strip().isdigit():
        where.append("d.year<=?"); args.append(int(year_to))
    if indexed:   # links from the Trends charts count only documents whose text is topic-classified
        where.append(trends.CLASSIFIED)
    actor_row = None
    if actor:
        where.append(actors.doc_clause()); args.append(actor)
    cluster_keys = [k for k in cluster.split(",") if k][:200]
    if cluster_keys:   # link from a Network cluster: reports naming two of these actors in one passage
        sql, cargs = actors.cluster_clause(cluster_keys)
        where.append(sql); args += cargs
        with db.session() as con:
            actors.init()
            actor_row = con.execute("SELECT key, label FROM actors WHERE key=?", (actor,)).fetchone()
    if source:
        where.append("s.id=?"); args.append(source)
    fts = trends.or_query(q) if q.strip() else ""
    if q.strip() and indexed:
        # link from a Trends chart: exactly the full-text match the chart counted
        where.append("d.id IN (SELECT rowid FROM doc_text WHERE doc_text MATCH ?)"); args.append(fts or '""')
    elif q.strip():
        # metadata match OR full-text match inside the report ("a OR b" is handled by the full-text match)
        where.append("""(d.title LIKE ? OR s.agency LIKE ? OR s.name_local LIKE ? OR s.name_en LIKE ?
                         OR d.id IN (SELECT rowid FROM doc_text WHERE doc_text MATCH ?))""")
        args += [f"%{q}%"] * 4 + [fts or '""']
    base_where, base_args = " AND ".join(where), list(args)      # everything except the topic filter
    for t in chosen:                                              # several topics: a document must have all
        if main:   # link from the topic mind map: the topic must be one of the report's main topics
            sql, margs = topics.main_topic_clause()
            where.append(sql); args += [*margs, t]
        else:
            where.append("d.id IN (SELECT doc_id FROM doc_topics WHERE topic=?)"); args.append(t)
    sql_where = " AND ".join(where)
    sort = sort or ("relevance" if chosen or q.strip() else "year")
    if sort == "relevance" and chosen:
        order = f"""(SELECT SUM(score) FROM doc_topics WHERE doc_id=d.id AND topic IN ({','.join('?' * len(chosen))})) DESC,
                    d.year DESC NULLS LAST"""
        order_args = list(chosen)
    elif sort == "relevance" and fts:
        order = "(SELECT bm25(doc_text) FROM doc_text WHERE doc_text MATCH ? AND rowid=d.id) ASC NULLS LAST, d.year DESC NULLS LAST"
        order_args = [fts]
    else:
        order, order_args = "d.year DESC NULLS LAST, s.country, s.agency, d.lang", []
    size = paging.per_page_of(per_page)
    params = dict(country=country, type=type, lang=lang, year=year, status=status, q=q, source=source or "",
                  coalition=coalition, topic=chosen, sort=sort if sort != "year" or chosen or q else "",
                  show_hidden=show_hidden or "", year_from=year_from, year_to=year_to, indexed=indexed or "",
                  actor=actor, main=main or "", cluster=cluster,
                  per_page=size if size != paging.PER_PAGE_CHOICES[2] else "")
    with db.session() as con:
        topics.init()
        total = con.execute(f"SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id WHERE {sql_where}",
                            args).fetchone()[0]
        pg = paging.paginate(total, page, size, "/", params)
        docs = [dict(r) for r in con.execute(
            f"""SELECT d.*, s.country, s.agency, s.type, s.name_en, s.logo_path
                FROM documents d JOIN sources s ON s.id=d.source_id
                WHERE {sql_where} ORDER BY {order} LIMIT ? OFFSET ?""",
            (*args, *order_args, size, pg["offset"]))]
        ids = [d["id"] for d in docs]
        by_doc: dict[int, list] = {}
        if ids:
            for r in con.execute(f"""SELECT doc_id, topic, score FROM doc_topics WHERE doc_id IN ({','.join('?' * len(ids))})
                                     ORDER BY score DESC""", ids):
                by_doc.setdefault(r["doc_id"], []).append(r["topic"])
            if fts:
                for r in con.execute(f"""SELECT rowid, snippet(doc_text, 1, char(2), char(3), '…', 14) AS snip FROM doc_text
                                         WHERE doc_text MATCH ? AND rowid IN ({','.join('?' * len(ids))})""", (fts, *ids)):
                    for d in docs:
                        if d["id"] == r["rowid"]:
                            d["snippet"] = highlight(r["snip"])
        for d in docs:   # subject topics first (by score), meta topics such as "agency activity" last
            d["topics"] = sorted(by_doc.get(d["id"], []), key=lambda t: bool(tax.get(t, {}).get("meta")))
        topic_counts = dict(con.execute(
            f"""SELECT t.topic, COUNT(DISTINCT t.doc_id) FROM doc_topics t JOIN documents d ON d.id=t.doc_id
                JOIN sources s ON s.id=d.source_id WHERE {base_where} GROUP BY t.topic""", base_args).fetchall())
        facets = {
            "country": con.execute("SELECT DISTINCT country FROM sources WHERE active=1 ORDER BY country").fetchall(),
            "type": con.execute("SELECT DISTINCT type FROM sources WHERE active=1 ORDER BY type").fetchall(),
            "lang": con.execute("SELECT DISTINCT lang FROM documents WHERE lang!='' ORDER BY lang").fetchall(),
            "year": con.execute("SELECT DISTINCT year FROM documents WHERE year IS NOT NULL ORDER BY year DESC").fetchall(),
        }
        counts = dict(con.execute("SELECT status, COUNT(*) FROM documents GROUP BY status").fetchall())

    def qs(**kw):
        merged = {**params, **kw}
        return urlencode({k: v for k, v in merged.items() if v not in ("", 0, None, [])}, doseq=True)

    return tpl.TemplateResponse(request, "index.html", {
        "docs": docs, "total": total, "pg": pg,
        "facets": facets, "f": params, "counts": counts, "jobs": dict(_jobs), "qs": qs,
        "TOPICS": tax, "CATEGORIES": topics.taxonomy()["categories"], "topic_counts": topic_counts,
        "actor_row": actor_row,
    })


def highlight(snippet: str) -> str:
    """FTS snippet → safe HTML: escape the report text first, then turn our \\x02/\\x03 markers into <mark>."""
    return str(escape(snippet)).replace("\x02", "<mark>").replace("\x03", "</mark>")


@app.get("/topics")
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
    return tpl.TemplateResponse(request, "topics.html", {"tax": tax, "stats": rows, "indexed": indexed,
                                                        "jobs": dict(_jobs)})


@app.get("/sources")
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
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["country"], []).append(r)
    ordered = sorted(groups.items(), key=lambda kv: (region_of(kv[0])[0], COUNTRY_NAMES.get(kv[0], kv[0])))
    regions: list[tuple[str, list]] = []
    for country, items in ordered:
        name = region_of(country)[1]
        if not regions or regions[-1][0] != name:
            regions.append((name, []))
        regions[-1][1].append((country, items))
    return tpl.TemplateResponse(request, "sources.html", {"sources": rows, "groups": ordered, "regions": regions,
                                                         "pages": pages, "jobs": dict(_jobs)})


@app.get("/changelog")
def changelog(request: Request):
    import markdown   # our own CHANGELOG.md – trusted content
    text = (HERE.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    html = markdown.markdown(text, extensions=["extra"], output_format="html")
    return tpl.TemplateResponse(request, "changelog.html", {"body": html, "jobs": dict(_jobs)})


@app.get("/api/version")
def version():
    return {"version": __version__, "build": build_version()}


TREND_VIEWS = {"topics": "Topics over time", "terms": "Term trends", "matrix": "Who reports on what"}


def _trend_page(request: Request, view: str):
    tax = topics.taxonomy()
    with db.session() as con:
        years = [r[0] for r in con.execute("SELECT DISTINCT year FROM documents WHERE year >= ? ORDER BY year DESC",
                                           (trends.MIN_YEAR,))]
        present = {r[0] for r in con.execute("SELECT DISTINCT country FROM sources WHERE active=1")}
    return tpl.TemplateResponse(request, "trends.html", {
        "view": view, "views": TREND_VIEWS, "TOPICS": tax["topics"], "CATEGORIES": tax["categories"],
        "topic_names": {k: t["name"] for k, t in tax["topics"].items()},
        "years": years, "countries": sorted(present, key=lambda c: COUNTRY_NAMES.get(c, c)), "jobs": dict(_jobs)})


@app.get("/trends")
def trends_topics(request: Request):
    return _trend_page(request, "topics")


@app.get("/trends/terms")
def trends_terms(request: Request):
    return _trend_page(request, "terms")


@app.get("/trends/matrix")
def trends_matrix(request: Request):
    return _trend_page(request, "matrix")


def _csv(name: str, header: list[str], rows) -> Response:
    """Chart data as CSV; every row keeps the link to the documents it counts."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="rozvedka-{name}.csv"'})


def _abs(request: Request, link: str) -> str:
    return str(request.base_url).rstrip("/") + link


def _series_csv(request: Request, name: str, data: dict) -> Response:
    rows = []
    den = data["denominator"]
    for s in data["series"]:
        for i, y in enumerate(data["years"]):
            rows.append([s["name"], y, s["docs"][i], den["docs"][i], s["share_docs"][i], s["agencies"][i],
                         den["agencies"][i], s["share_agencies"][i], _abs(request, s["links"][i])])
    return _csv(name, ["series", "year", "documents", "documents_in_scope", "share_of_documents", "agencies",
                       "agencies_in_scope", "share_of_agencies", "source_documents"], rows)


@app.get("/api/trends/topics")
def api_trend_topics(request: Request, topic: list[str] = Query(default=[]), country: str = "", coalition: str = "",
                     type: str = "", format: str = "json"):
    data = trends.topic_trends(topic[:8], country, coalition, type)
    return _series_csv(request, "topic-trends", data) if format == "csv" else data


@app.get("/api/trends/terms")
def api_trend_terms(request: Request, term: list[str] = Query(default=[]), country: str = "", coalition: str = "",
                    type: str = "", format: str = "json"):
    data = trends.term_trends([t for t in term if t.strip()][:8], country, coalition, type)
    return _series_csv(request, "term-trends", data) if format == "csv" else data


@app.get("/api/trends/rising")
def api_trend_rising(country: str = "", coalition: str = "", type: str = ""):
    return trends.rising(country, coalition, type)


@app.get("/api/trends/matrix")
def api_trend_matrix(request: Request, year_from: int = 0, year_to: int = 0, by: str = "country",
                     coalition: str = "", type: str = "", format: str = "json"):
    now = dt.date.today().year
    year_to = year_to or now - 1
    year_from = year_from or year_to - 2
    data = trends.matrix(year_from, year_to, "agency" if by == "agency" else "country", coalition, type)
    if format != "csv":
        return data
    rows_by_key = {r["key"]: r for r in data["rows"]}
    names = {t["key"]: t["name"] for t in data["topics"]}
    return _csv(f"matrix-{year_from}-{year_to}", ["row", "topic", "documents_with_topic", "documents_of_row", "share",
                                                 "source_documents"],
                ([rows_by_key[c["row"]]["label"], names[c["topic"]], c["n"], rows_by_key[c["row"]]["docs"],
                  c["share"], _abs(request, c["link"])] for c in data["cells"]))


@app.get("/actors")
def actors_page(request: Request, kind: str = "", q: str = "", min_docs: int = 2, page: str = "1", per_page: str = ""):
    every = actors.actor_list("", q, max(1, min_docs), include_countries=True)
    counts: dict[str, int] = {}
    for r in every:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    rows = [r for r in every if r["kind"] == kind] if kind else [r for r in every if r["kind"] != "country"]
    size = paging.per_page_of(per_page)
    f = {"kind": kind, "q": q, "min_docs": min_docs, "per_page": size if size != paging.PER_PAGE_CHOICES[2] else ""}
    pg = paging.paginate(len(rows), page, size, "/actors", f)
    maxdocs = max((r["docs"] for r in rows), default=1)
    return tpl.TemplateResponse(request, "actors.html", {
        "rows": rows[pg["offset"]:pg["offset"] + size], "pg": pg, "kinds": actors.KINDS, "counts": counts, "f": f,
        "maxdocs": maxdocs, "meta": actors.stamp(), "jobs": dict(_jobs)})


@app.get("/actors/names")
def actor_names_page(request: Request, status: str = "used", page: str = "1", per_page: str = ""):
    status = "ignored" if status == "ignored" else "used"
    size = paging.per_page_of(per_page)
    pg = paging.paginate(actors.count_names(status), page, size, "/actors/names",
                         {"status": status if status == "ignored" else ""})
    return tpl.TemplateResponse(request, "actor_names.html", {
        "rows": actors.top_names(size, status, pg["offset"]), "pg": pg, "status": status,
        "kinds": actors.KINDS, "jobs": dict(_jobs)})


@app.get("/actors/{a}/with/{b}")
def actor_pair_page(request: Request, a: str, b: str, year_from: int = 0, year_to: int = 0, coalition: str = "",
                    topic: str = "", type: str = "", page: str = "1", per_page: str = ""):
    size = paging.per_page_of(per_page, 25)
    d = actors.pair_detail(a, b, year_from or None, year_to or None, coalition, topic, type, size, page)
    if d is None:
        raise HTTPException(404, "unknown actor")
    filters = {"year_from": year_from or "", "year_to": year_to or "", "coalition": coalition, "topic": topic,
               "type": type, "per_page": size if size != 25 else ""}
    pg = paging.paginate(d["docs"], page, size, f"/actors/{a}/with/{b}", filters, default=25)
    return tpl.TemplateResponse(request, "pair.html", {**d, "pg": pg, "TOPICS": topics.taxonomy()["topics"],
                                                      "jobs": dict(_jobs)})


def _years_desc():
    with db.session() as con:
        return [r[0] for r in con.execute("SELECT DISTINCT year FROM documents WHERE year >= ? ORDER BY year DESC",
                                          (trends.MIN_YEAR,))]


@app.get("/network")
def network_page(request: Request):
    tax = topics.taxonomy()
    return tpl.TemplateResponse(request, "network.html", {
        "kinds": actors.KINDS, "years": _years_desc(), "TOPICS": tax["topics"], "CATEGORIES": tax["categories"],
        "jobs": dict(_jobs)})


@app.get("/api/network")
def api_network(year_from: int = 0, year_to: int = 0, coalition: str = "", type: str = "", topic: str = "",
                countries_too: int = 0, actors_n: int = 60, min_pair: int = 3, threshold: float = 0.25,
                kind: list[str] = Query(default=[])):
    return graphs.associations(year_from or None, year_to or None, coalition, type, topic, bool(countries_too),
                               max(10, min(actors_n, 120)), max(1, min_pair), min(max(threshold, 0.05), 0.9), kind)


@app.get("/map/mentions")
def mentions_page(request: Request):
    return tpl.TemplateResponse(request, "mentions.html", {"years": _years_desc(), "jobs": dict(_jobs),
                                                         "reporting": sorted(COUNTRY_NAMES.items(), key=lambda x: x[1])})


@app.get("/api/mentions")
def api_mentions(request: Request, mode: str = "about", target: str = "", year_from: int = 0, year_to: int = 0,
                 type: str = "", format: str = "json"):
    d = graphs.geography("from" if mode == "from" else "about", target, year_from or None, year_to or None, type)
    if format != "csv":
        return d
    return _csv(f"mentions-{mode}-{target}", ["country", "iso", "reports_naming", "reports_in_scope", "share", "source_documents"],
                ([r["name"], r["iso"], r["docs"], r["of"], r["share"], _abs(request, r["link"])] for r in d["rows"]))


@app.get("/topics/map")
def topic_map_page(request: Request):
    return tpl.TemplateResponse(request, "topic_map.html", {"years": _years_desc(), "jobs": dict(_jobs)})


@app.get("/api/topics/tree")
def api_topic_tree(coalition: str = "", year_from: int = 0, year_to: int = 0, per_topic: int = 6):
    return graphs.topic_tree(max(0, min(per_topic, 12)), coalition, year_from or None, year_to or None)


@app.get("/actors/{key}")
def actor_page(request: Request, key: str, page: str = "1", per_page: str = ""):
    size = paging.per_page_of(per_page, 25)
    d = actors.actor_detail(key, size, page)
    if d is None:
        raise HTTPException(404, "unknown actor")
    pg = paging.paginate(d["docs"], page, size, f"/actors/{key}", {"per_page": size if size != 25 else ""},
                         anchor="#passages", default=25)
    return tpl.TemplateResponse(request, "actor.html", {**d, "pg": pg, "kinds": actors.KINDS, "meta": actors.stamp(),
                                                       "TOPICS": topics.taxonomy()["topics"], "jobs": dict(_jobs)})


@app.get("/api/events")
def api_events():
    return trends.events()


@app.get("/map")
def world_map(request: Request):
    return tpl.TemplateResponse(request, "map.html", {"jobs": dict(_jobs), "TYPE_NAMES": TYPE_NAMES})


@app.get("/api/map")
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


LOGO_TYPES = {"svg": "image/svg+xml", "png": "image/png", "jpg": "image/jpeg", "webp": "image/webp",
              "gif": "image/gif", "ico": "image/x-icon"}


@app.get("/logo/{source_id}")
def logo(source_id: int):
    with db.session() as con:
        s = con.execute("SELECT logo_path FROM sources WHERE id=?", (source_id,)).fetchone()
    if not s or not s["logo_path"]:
        raise HTTPException(404, "no logo")
    path = (logos.LOGOS / s["logo_path"]).resolve()
    if not path.is_relative_to(logos.LOGOS.resolve()) or not path.exists():
        raise HTTPException(404, "logo missing")
    # logos come from third-party sites: an SVG could carry script, so forbid active content outright
    return FileResponse(path, media_type=LOGO_TYPES.get(path.suffix.lstrip("."), "application/octet-stream"),
                        headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:",
                                 "X-Content-Type-Options": "nosniff", "Cache-Control": "max-age=86400"})


@app.get("/doc/{doc_id}")
def open_doc(doc_id: int):
    with db.session() as con:
        d = con.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not d or not d["local_path"]:
        raise HTTPException(404, "not downloaded")
    path = (FILES / d["local_path"]).resolve()
    if not path.is_relative_to(FILES.resolve()) or not path.exists():
        raise HTTPException(404, "file missing")
    return FileResponse(path, media_type="application/pdf", filename=path.name, content_disposition_type="inline")


def _back(request: Request, fallback: str = "/"):
    return RedirectResponse(request.headers.get("referer") or fallback, status_code=303)


@app.post("/doc/{doc_id}/download")
def download_doc(request: Request, doc_id: int):
    downloader.download_one(doc_id)
    return _back(request)


@app.post("/doc/{doc_id}/hide")
def hide_doc(request: Request, doc_id: int, hidden: int = Form(1)):
    with db.session() as con:
        con.execute("UPDATE documents SET hidden=? WHERE id=?", (hidden, doc_id))
    return _back(request)


@app.post("/doc/{doc_id}/edit")
def edit_doc(request: Request, doc_id: int, title: str = Form(...), lang: str = Form(""), year: str = Form("")):
    with db.session() as con:
        con.execute("UPDATE documents SET title=?, lang=?, year=? WHERE id=?",
                    (title.strip(), lang.strip().lower(), int(year) if year.strip().isdigit() else None, doc_id))
    return _back(request)


@app.post("/add")
def add_doc(request: Request, source_id: int = Form(...), url: str = Form(...), title: str = Form(""),
            lang: str = Form(""), year: str = Form(""), fetch_now: str = Form("")):
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL must start with http(s)://")
    with db.session() as con:
        con.execute(
            """INSERT INTO documents(source_id,url,title,lang,year,origin) VALUES(?,?,?,?,?,'manual')
               ON CONFLICT(url) DO UPDATE SET title=excluded.title, lang=excluded.lang, year=excluded.year, hidden=0""",
            (source_id, url, title.strip() or url.rsplit("/", 1)[-1], lang.strip().lower(),
             int(year) if year.strip().isdigit() else crawler.guess_year(title, url)))
        doc_id = con.execute("SELECT id FROM documents WHERE url=?", (url,)).fetchone()["id"]
    if fetch_now:
        downloader.download_one(doc_id)
    return RedirectResponse(f"/?source={source_id}", status_code=303)


@app.post("/jobs/crawl")
def job_crawl(request: Request, country: str = Form(""), agency: str = Form("")):
    _run_job(f"crawl {country} {agency}".strip(), crawler.crawl, country or None, agency or None)
    return _back(request, "/sources")


@app.post("/jobs/download")
def job_download(request: Request, country: str = Form(""), retry_failed: str = Form("")):
    _run_job(f"download {country}".strip(), downloader.download, country or None, bool(retry_failed))
    return _back(request)


@app.post("/jobs/sync")
def job_sync(request: Request):
    registry.sync()
    return _back(request, "/sources")
