"""Web portal: browse, filter, download and add security reports."""
import csv
import datetime as dt
import hashlib
import io
import json
import re
import time
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from markupsafe import Markup, escape

from . import (__version__, actors, build_version, collect, countries, crawler, db, downloader, graphs, home, logos,
               paging, registry, series, topics, trends, updates)
from . import compare as compare_mod
from . import dating
from . import dataset, doclist, doctypes, folders, report, review, updater, watch
from . import jobs as jobrunner
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
    "eu-body": "EU body", "nato": "NATO", "other": "Other", "think-tank": "Think tank (independent)",
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


tpl.env.globals.update(sid=series.sid, COUNTRY_NAMES=COUNTRY_NAMES, TYPE_NAMES=TYPE_NAMES, flag_url=flag_url, initials=initials,
                       coalition_tags=coalition_tags, COALITIONS=countries.coalitions(), VERSION=__version__,
                       BUILD=build_version())

tpl.env.filters["num"] = lambda n: f"{n or 0:,}"

_independent: dict = {"at": None, "ids": frozenset()}     # at=None: not loaded yet


def independent_ids() -> frozenset:
    """Sources not run by a state (think tanks) – refreshed every minute; few rows."""
    if _independent["at"] is None or time.monotonic() - _independent["at"] > 60:
        with db.session() as con:
            _independent["ids"] = frozenset(r[0] for r in con.execute(
                "SELECT id FROM sources WHERE COALESCE(publisher, 'official') = 'independent'"))
        _independent["at"] = time.monotonic()
    return _independent["ids"]


def pub_mark(source_id) -> Markup:
    """The badge that marks an independent publisher next to its name, wherever a source or report is shown."""
    if source_id in independent_ids():
        return Markup('<span class="pub-ind" title="Independent publisher – a think tank, not run by a state">think tank</span>')
    return Markup("")


tpl.env.globals.update(pub_mark=pub_mark, is_independent=lambda sid: sid in independent_ids())


def asset(path: str) -> str:
    """URL of a static file with a content stamp (`/static/style.css?v=1a2b3c4d`): a changed file gets a new URL,
    so browsers never keep an old stylesheet or script after an update."""
    f = HERE / "static" / path
    try:
        stat = f.stat()
    except OSError:
        return f"/static/{path}"
    key = (path, stat.st_mtime_ns, stat.st_size)
    if key not in _stamps:
        _stamps[key] = hashlib.sha1(f.read_bytes()).hexdigest()[:8]
    return f"/static/{path}?v={_stamps[key]}"


_stamps: dict[tuple, str] = {}
tpl.env.globals["asset"] = asset


@app.middleware("http")
async def static_cache(request: Request, call_next):
    """Stamped static files never change (cache for a year); anything else under /static is revalidated each time."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = ("public, max-age=31536000, immutable" if "v" in request.query_params
                                             else "no-cache")
    return response

_age_cache: dict = {}


def header_status() -> dict:
    """For the header's Update button: how old the data is (last check of the report pages) and the running job."""
    now = time.time()
    if now - _age_cache.get("at", 0) > 30:
        with db.session() as con:
            since = updater.all_checked_since(con)
            latest = con.execute("SELECT MAX(last_crawled) FROM pages").fetchone()[0]
        _age_cache.update(at=now, last=since, latest=latest,
                          days=(dt.datetime.now() - dt.datetime.fromisoformat(since[:19])).days if since else None)
    j = jobrunner.state()
    running = j if j and j["status"] == "running" else None
    pct = int(100 * running["progress"]["done"] / running["progress"]["total"]) if running and running["progress"]["total"] else None
    return {"last": _age_cache["last"], "latest": _age_cache["latest"], "days": _age_cache["days"],
            "job": running and running["title"], "pct": pct}


tpl.env.globals["header_status"] = header_status
tpl.env.filters["days_ago"] = lambda ts: (dt.datetime.now() - dt.datetime.fromisoformat(ts[:19])).days


@app.on_event("startup")
def startup():
    db.init()
    collect.init()
    registry.sync()


@app.get("/")
def home_page(request: Request):
    if request.url.query:   # links and bookmarks from before 0.22.0, when the Documents list was the home page
        return RedirectResponse(f"/documents?{request.url.query}", status_code=307)
    return _home(request)


def _home(request: Request, q: str = "", problems: list | None = None):
    return tpl.TemplateResponse(request, "home.html", {
        "d": home.dashboard(), "q": q, "problems": problems or [], "operators": home.OPERATORS,
        "examples": home.examples()})


@app.get("/search")
def search(request: Request, q: str = ""):
    """The home page's search console: operators (country:, actor:, topic: …) become Documents filters."""
    if not q.strip():
        return RedirectResponse("/documents", status_code=303)
    parsed = home.parse(q)
    if parsed["problems"]:
        return _home(request, q, parsed["problems"])
    return RedirectResponse(home.docs_url(**parsed["params"]), status_code=303)


@app.get("/api/suggest")
def api_suggest(q: str = ""):
    out = home.suggest(q)
    for g in out["groups"]:
        for it in g["items"]:
            if it.get("country"):
                it["flag"] = flag_url(it["country"])
    return out


@app.get("/new")
def whats_new(request: Request, day: str = ""):
    """What's new, update by update (an update = a day on which reports entered the library)."""
    u = updates.update(day or None)
    size = paging.per_page_of(request.query_params.get("per_page"), 100)
    pg = paging.paginate(u.get("n", 0), request.query_params.get("page", "1"), size, "/new", {"day": day},
                         anchor="#reports")
    return tpl.TemplateResponse(request, "new.html", {
        "u": u, "TOPICS": topics.taxonomy()["topics"], "pg": pg,
        "page_docs": u.get("docs", [])[pg["offset"]:pg["offset"] + size],
        "by_source": {g["source_id"]: g for g in u.get("agencies", [])}})


@app.get("/compare")
def compare_page(request: Request, q: str = "", actor: str = "", topic: str = "", year_from: str = "", year_to: str = "",
                 country: str = "", coalition: str = "", type: str = "", page: str = "1", per_page: str = ""):
    """Compare agencies on one question: each agency's densest passages on one actor or topic."""
    problem = ""
    if q.strip() and not (actor or topic):        # the form's subject box: a topic name, else an actor name or alias
        text = q.strip()
        for prefix in ("topic:", "actor:"):
            if text.lower().startswith(prefix):
                text = text[len(prefix):].strip().strip('"')
        with db.session() as con:
            topic = "" if q.lower().startswith("actor:") else (home._topic(text) or "")
            if not topic:
                a = home._actor(con, text)
                actor = a["key"] if a else ""
        if not (actor or topic):
            problem = f"No topic or actor named “{q}” – try the Topics or Actors page."
    year = lambda v: int(v) if v.strip().isdigit() else None   # noqa: E731
    size = paging.per_page_of(per_page, 12) if per_page else 12
    try:
        pnum = max(1, int(page))
    except ValueError:
        pnum = 1
    c = compare_mod.compare(actor, topic, year(year_from), year(year_to), country, coalition, type, pnum, size) \
        if (actor or topic) else None
    pg = None
    if c and "error" not in c:
        pg = paging.paginate(c["n_agencies"], page, size, "/compare",
                             {"actor": actor, "topic": topic, "year_from": c["year_from"], "year_to": c["year_to"],
                              "country": country, "coalition": coalition, "type": type,
                              "per_page": size if size != 12 else ""}, default=12)
    with db.session() as con:
        have = [r[0] for r in con.execute("SELECT DISTINCT country FROM sources WHERE active=1")]
    return tpl.TemplateResponse(request, "compare.html", {
        "c": c, "pg": pg, "problem": problem or (c or {}).get("error", ""), "TOPICS": topics.taxonomy()["topics"],
        "CATEGORIES": topics.taxonomy()["categories"], "countries": sorted(have, key=lambda k: COUNTRY_NAMES.get(k, k)),
        "f": {"q": q if not (actor or topic) else ((c or {}).get("subject") or {}).get("label", q), "actor": actor,
              "topic": topic, "year_from": year_from, "year_to": year_to, "country": country, "coalition": coalition,
              "type": type},
        "examples": [("Wagner Group", "actor"), ("Ransomware & extortion", "topic"), ("Fancy Bear", "actor"),
                     ("Hybrid threats & grey-zone activity", "topic")]})


@app.get("/data")
def data_page(request: Request):
    """Data exchange: this installation, how fresh its data is, and the datasets exported or imported."""
    with db.session() as con:
        fresh = dataset.freshness(con)
        runs = [dict(r) for r in con.execute(
            "SELECT kind, started_at, summary FROM runs WHERE kind IN ('export','import') ORDER BY id DESC LIMIT 50")]
    for r in runs:
        try:
            r["summary"] = json.loads(r["summary"])
        except (TypeError, ValueError):
            r["summary"] = {}
    size = sum(f.stat().st_size for f in FILES.rglob("*") if f.is_file()) if FILES.exists() else 0
    logs = sorted(jobrunner.logs_dir().glob("*.log"), reverse=True)[:15] if jobrunner.logs_dir().exists() else []
    last_dir = next((str(Path(r["summary"]["manifest"]).parent) for r in runs
                     if r["kind"] == "export" and r["summary"].get("manifest")
                     and folders.allowed(Path(r["summary"]["manifest"]).parent)
                     and Path(r["summary"]["manifest"]).parent.is_dir()), "")
    return tpl.TemplateResponse(request, "data.html", {"me": dataset.installation(), "fresh": fresh, "runs": runs,
                                                      "files_bytes": size, "logs": [p.name for p in logs], "last_dir": last_dir,
                                                      "roots": [str(r) for r in folders.roots()]})


def _api_error(e: Exception, status: int = 400):
    return JSONResponse({"error": str(e)}, status_code=status)


@app.get("/api/data/folders")
def api_data_folders(path: str = ""):
    try:
        return folders.listing(path)
    except (PermissionError, FileNotFoundError, OSError) as e:
        return _api_error(e)


@app.post("/api/data/folders")
def api_data_mkdir(parent: str = Form(...), name: str = Form(...)):
    try:
        return {"path": str(folders.make(parent, name))}
    except (PermissionError, FileNotFoundError, ValueError, OSError) as e:
        return _api_error(e)


@app.get("/api/data/estimate")
def api_data_estimate(what: str = "all", since: str = ""):
    """About how many bytes an export will need (report files + compressed database)."""
    with db.session() as con:
        if what == "catalogue":
            files_bytes, n = 0, 0
        else:
            row = con.execute("""SELECT COALESCE(SUM(size),0), COUNT(*) FROM documents WHERE status='downloaded'
                                 AND local_path IS NOT NULL AND (? = '' OR MAX(COALESCE(discovered_at,''), COALESCE(downloaded_at,'')) >= ?)""",
                              (since if what == "since" else "", since if what == "since" else "")).fetchone()
            files_bytes, n = row[0], row[1]
    db_bytes = int(db.DB_PATH.stat().st_size * 0.35) if db.DB_PATH.exists() else 0
    return {"files": n, "files_bytes": files_bytes, "database_bytes": db_bytes, "total": files_bytes + db_bytes + (30 << 20)}


@app.post("/api/data/export")
def api_data_export(dest: str = Form(...), what: str = Form("all"), since: str = Form(""), part_size: str = Form("2000"),
                    name: str = Form("")):
    try:
        size_mb = int(part_size)
        if not 50 <= size_mb <= 100_000:
            raise ValueError("part size must be between 50 MB and 100 GB")
        if what == "since" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
            raise ValueError("choose the day from which report files are included")
        r = jobrunner.export(dest, files=what != "catalogue", since=since if what == "since" else None,
                            part_size=size_mb * 1_000_000, name=name.strip())
    except (PermissionError, FileNotFoundError, ValueError) as e:
        return _api_error(e)
    return r if "error" not in r else JSONResponse(r, status_code=409)


@app.post("/api/data/check")
def api_data_check(manifest: str = Form(...)):
    try:
        r = jobrunner.check(manifest)
    except (PermissionError, FileNotFoundError) as e:
        return _api_error(e)
    return r if "error" not in r else JSONResponse(r, status_code=409)


@app.post("/api/data/import")
def api_data_import(manifest: str = Form(...), prefer: str = Form("local")):
    try:
        r = jobrunner.import_(manifest, prefer)
    except (PermissionError, FileNotFoundError) as e:
        return _api_error(e)
    return r if "error" not in r else JSONResponse(r, status_code=409)


@app.post("/api/data/cancel")
def api_data_cancel():
    return {"cancelled": jobrunner.cancel()}


@app.get("/api/data/job")
def api_data_job():
    return {"job": jobrunner.state()}


@app.get("/data/logs/{name}")
def data_log(name: str):
    p = jobrunner.log_path(name)
    if p is None:
        raise HTTPException(404, "no such log")
    return PlainTextResponse(p.read_text(encoding="utf-8", errors="replace"))


@app.get("/update")
def update_page(request: Request, country: str = "", state: str = "", q: str = "", page: str = "1", per_page: str = ""):
    """Check the agencies for new reports: what to do, which sources, progress, and every source's last check."""
    rows = updater.sources_status(country, state, q)
    allrows = updater.sources_status() if (country or state or q) else rows
    size = paging.per_page_of(per_page, 200)       # usually every source on one page, so all can be ticked
    pg = paging.paginate(len(rows), page, size, "/update", {"country": country, "state": state, "q": q,
                         "per_page": size if size != 200 else ""}, anchor="#sources", default=200)
    with db.session() as con:
        fresh = dataset.freshness(con)
        counts = dict(con.execute("""SELECT d.status, COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                                     WHERE d.hidden=0 AND s.active=1 GROUP BY d.status""").fetchall())
    from collections import Counter
    logs = sorted(jobrunner.logs_dir().glob("update-*.log"), reverse=True)[:10] if jobrunner.logs_dir().exists() else []
    return tpl.TemplateResponse(request, "update.html", {
        "rows": rows[pg["offset"]:pg["offset"] + size], "pg": pg, "f": {"country": country, "state": state, "q": q},
        "states": Counter(r["state"] for r in allrows), "stale_n": sum(1 for r in allrows if r["stale"] and r["state"] != "manual"),
        "countries": sorted({r["country"] for r in allrows}, key=lambda k: COUNTRY_NAMES.get(k, k)),
        "fresh": fresh, "counts": counts, "history": updater.history(), "logs": [p.name for p in logs],
        "since": _since(),
        "actions": updater.ACTIONS, "plan": updater.plan()})


def _since() -> str | None:
    with db.session() as con:
        return updater.all_checked_since(con)


def _update_form(action: str, scope: str, country: str, sources: str, stale_days: str, retry_failed: str) -> dict:
    ids = [int(x) for x in sources.split(",") if x.strip().isdigit()]
    days = int(stale_days) if stale_days.strip().isdigit() else 7
    return {"action": action, "scope": scope, "country": country, "sources": ids, "stale_days": days,
            "retry_failed": retry_failed in ("1", "true", "on")}


@app.get("/api/update/plan")
def api_update_plan(action: str = "full", scope: str = "all", country: str = "", sources: str = "", stale_days: str = "7",
                    retry_failed: str = ""):
    return updater.plan(**_update_form(action, scope, country, sources, stale_days, retry_failed))


@app.post("/api/update")
def api_update(action: str = Form("full"), scope: str = Form("all"), country: str = Form(""), sources: str = Form(""),
               stale_days: str = Form("7"), retry_failed: str = Form("")):
    f = _update_form(action, scope, country, sources, stale_days, retry_failed)
    if scope == "sources" and not f["sources"]:
        return JSONResponse({"error": "tick the sources to check in the table"}, status_code=400)
    if scope == "country" and not country:
        return JSONResponse({"error": "choose a country"}, status_code=400)
    r = jobrunner.update(**f)
    return r if "error" not in r else JSONResponse(r, status_code=409)


@app.get("/api/job")
def api_job():
    return {"job": jobrunner.state()}


@app.post("/api/job/cancel")
def api_job_cancel():
    return {"cancelled": jobrunner.cancel()}


@app.get("/feed.atom")
def atom_feed(request: Request, watch: str = ""):
    return Response(updates.feed(str(request.base_url).rstrip("/"), watch=watch), media_type="application/atom+xml")


@app.get("/watch")
def watch_page(request: Request, notice: str = ""):
    """The watchlist: followed searches, update by update (one shared list)."""
    o = watch.overview()
    for it in o["entries"]:
        if "cells" in it:
            it["latest"] = watch.latest(it["query"])
    return tpl.TemplateResponse(request, "watch.html", {"o": o, "notice": notice, "file": "sources/watchlist.yaml",
                                                       "operators": home.OPERATORS})


@app.post("/watch/add")
def watch_add(query: str = Form(...)):
    r = watch.add(query)
    notice = ("Now watching: " + r["added"]) if "added" in r else ("Already on the list: " + r["exists"]) if "exists" in r \
        else ("Not added – " + r["error"])
    return RedirectResponse("/watch?" + urlencode({"notice": notice}), status_code=303)


@app.post("/watch/remove")
def watch_remove(query: str = Form(...)):
    watch.remove(query)
    return RedirectResponse("/watch?" + urlencode({"notice": "Removed: " + query}), status_code=303)


@app.get("/documents")
def documents(request: Request, country: str = "", type: str = "", lang: str = "", year: str = "",
          status: str = "", q: str = "", source: int = 0, page: str = "1", per_page: str = "", show_hidden: int = 0,
          coalition: str = "", topic: list[str] = Query(default=[]), sort: str = "",
          year_from: str = "", year_to: str = "", indexed: int = 0, actor: str = "", main: int = 0,
          cluster: str = "", series_id: str = Query("", alias="series"), added_from: str = "", added_to: str = "", undated: int = 0,
          doc_type: str = "", all_types: int = 0, all_files: int = 0):
    tax = topics.taxonomy()["topics"]
    if doc_type == "all":                                   # the type list's "every type" choice
        doc_type, all_types = "", 1
    doc_type = doc_type if doc_type in doctypes.TYPES else ""
    fargs = dict(country=country, type=type, lang=lang, year=year, status=status, q=q, source=source,
                 show_hidden=show_hidden, coalition=coalition, topic=topic, year_from=year_from, year_to=year_to,
                 indexed=indexed, actor=actor, main=main, cluster=cluster, series_id=series_id,
                 added_from=added_from, added_to=added_to, undated=undated)
    flt = doclist.build(**fargs, doc_type=doc_type, all_types=all_types, all_files=all_files)
    every_type = doclist.build(**fargs, all_types=1)       # the same filters over every type: counts per type
    where, args, chosen, fts = flt["where"], flt["args"], flt["chosen"], flt["fts"]
    base_where, base_args = flt["base_where"], flt["base_args"]
    editions, series_row, actor_row = flt["editions"], flt["series_row"], flt["actor_row"]
    sql_where = " AND ".join(where)
    sort = sort or ("relevance" if chosen or q.strip() else "year")
    if sort == "relevance" and chosen:
        order = f"""(SELECT SUM(score) FROM doc_topics WHERE doc_id=d.id AND topic IN ({','.join('?' * len(chosen))})) DESC,
                    d.year DESC NULLS LAST"""
        order_args = list(chosen)
    elif sort == "relevance" and fts:
        order = "(SELECT bm25(doc_text) FROM doc_text WHERE doc_text MATCH ? AND rowid=d.id) ASC NULLS LAST, d.year DESC NULLS LAST"
        order_args = [fts]
    elif sort == "added":
        order, order_args = "d.discovered_at DESC, d.id DESC", []
    else:
        order, order_args = "d.year DESC NULLS LAST, s.country, s.agency, d.lang", []
    size = paging.per_page_of(per_page)
    params = dict(country=country, type=type, lang=lang, year=year, status=status, q=q, source=source or "",
                  coalition=coalition, topic=chosen, sort=sort if sort != "year" or chosen or q else "",
                  show_hidden=show_hidden or "", year_from=year_from, year_to=year_to, indexed=indexed or "",
                  actor=actor, main=main or "", cluster=cluster, series=series_id, added_from=added_from, added_to=added_to,
                  undated=undated or "", doc_type=doc_type, all_types=all_types or "", all_files=all_files or "",
                  per_page=size if size != paging.PER_PAGE_CHOICES[2] else "")
    with db.session() as con:
        topics.init()
        total = con.execute(f"SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id WHERE {sql_where}",
                            args).fetchone()[0]
        pg = paging.paginate(total, page, size, "/documents", params)
        independent = con.execute(f"""SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                                      WHERE {sql_where} AND NOT {trends.OFFICIAL}""", args).fetchone()[0]
        # other language versions and summaries of the reports listed (one file per report is listed by default)
        every_file = doclist.build(**fargs, doc_type=doc_type, all_types=all_types, all_files=1)
        other_files = con.execute(f"""SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                                      WHERE {' AND '.join(every_file['where'])}""", every_file["args"]).fetchone()[0] - total
        type_counts = dict(con.execute(
            f"""SELECT COALESCE(d.doc_type, ''), COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                WHERE {' AND '.join(every_type['where'])} GROUP BY 1""", every_type["args"]).fetchall())
        docs = [dict(r) for r in con.execute(
            f"""SELECT d.*, s.country, s.agency, s.type, s.name_en, s.logo_path,
                       u.added_at AS hand_added, u.official AS hand_official, ix.ocr AS ocr
                FROM documents d JOIN sources s ON s.id=d.source_id LEFT JOIN uploads u ON u.doc_id=d.id
                LEFT JOIN doc_index ix ON ix.doc_id=d.id
                WHERE {sql_where} ORDER BY {order} LIMIT ? OFFSET ?""",
            (*args, *order_args, size, pg["offset"]))]
        ids = [d["id"] for d in docs]
        variants: dict[int, list] = {}          # the other files of each listed report
        works_ids = [d["work_id"] for d in docs if d.get("work_id")]
        if works_ids:
            for r in con.execute(f"""SELECT id, work_id, lang, title FROM documents WHERE work_id IN ({','.join('?' * len(works_ids))})
                                     ORDER BY lang, id""", works_ids):
                variants.setdefault(r["work_id"], []).append(dict(r))
        for d in docs:
            d["variants"] = [v for v in variants.get(d.get("work_id"), []) if v["id"] != d["id"]]
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
        for d in docs:
            d["ocr"] = json.loads(d["ocr"]) if d.get("ocr") else None
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

    return tpl.TemplateResponse(request, "index.html", {"year_conflicts": len(dating.conflicts()),
        "type_counts": type_counts, "DOC_TYPES": doctypes.TYPES, "NOT_REPORTS": doctypes.NOT_REPORTS,
        "other_files": other_files, "independent": independent,
        "docs": docs, "total": total, "pg": pg,
        "facets": facets, "f": params, "counts": counts, "qs": qs,
        "TOPICS": tax, "CATEGORIES": topics.taxonomy()["categories"], "topic_counts": topic_counts,
        "actor_row": actor_row, "editions": editions, "series_row": series_row,
        "watch_query": watch.to_query({**params, "topic": chosen}) if total else None,
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
    return tpl.TemplateResponse(request, "topics.html", {"tax": tax, "stats": rows, "indexed": indexed})


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
    # official agencies by region (EU members first); independent publishers (think tanks) in a section of their own
    official = [r for r in rows if (r["publisher"] or "official") == "official"]
    independent = [r for r in rows if (r["publisher"] or "official") == "independent"]

    def by_country(items):
        groups: dict[str, list] = {}
        for r in items:
            groups.setdefault(r["country"], []).append(r)
        return sorted(groups.items(), key=lambda kv: (region_of(kv[0])[0], COUNTRY_NAMES.get(kv[0], kv[0])))
    ordered = by_country(official)
    regions: list[tuple[str, list, bool]] = []
    for country, items in ordered:
        name = region_of(country)[1]
        if not regions or regions[-1][0] != name:
            regions.append((name, [], False))
        regions[-1][1].append((country, items))
    if independent:
        regions.append(("Independent publishers – think tanks", by_country(independent), True))
    return tpl.TemplateResponse(request, "sources.html", {"sources": rows, "groups": ordered, "regions": regions,
                                                         "n_official": len(official), "n_independent": len(independent),
                                                         "pages": pages, "series_by": series.by_source()})


@app.get("/series")
def series_catalogue(request: Request, country: str = "", q: str = "", page: str = "1", per_page: str = ""):
    cat = series.catalogue()
    if country:
        cat = [c for c in cat if c["source"] and c["source"]["country"] == country]
    if q.strip():
        cat = [c for c in cat if q.strip().casefold() in (c["series"]["name"] + " " + c["series"]["source"]).casefold()]
    cat.sort(key=lambda c: (region_of(c["source"]["country"]) if c["source"] else (99, ""), c["series"]["source"], c["series"]["name"]))
    size = paging.per_page_of(per_page, 50)
    pg = paging.paginate(len(cat), page, size, "/series", {"country": country, "q": q, "per_page": size if size != 50 else ""},
                         default=50)
    countries_ = sorted({c["source"]["country"] for c in series.catalogue() if c["source"]}, key=lambda k: COUNTRY_NAMES.get(k, k))
    return tpl.TemplateResponse(request, "series.html", {
        "items": cat[pg["offset"]:pg["offset"] + size], "pg": pg, "f": {"country": country, "q": q},
        "countries": countries_})


@app.get("/series/{series_id}")
def series_page(request: Request, series_id: str, lang: str = ""):
    d = series.detail(series_id, lang)
    if d is None:
        raise HTTPException(404, "unknown series")
    return tpl.TemplateResponse(request, "series_detail.html", {**d, "TOPICS": topics.taxonomy()["topics"],
                                                               "kinds": actors.KINDS})


@app.get("/sources/coverage")
def coverage_page(request: Request, source: str = "", page: str = "1", per_page: str = ""):
    """Report series: coverage of the confirmed ones, and proposals to confirm."""
    cov = [c for c in series.all_coverage() if not source or c["series"]["source"] == source]
    with db.session() as con:
        sid = con.execute("SELECT id FROM sources WHERE key=?", (source,)).fetchone() if source else None
        props = series.propose(con, sid["id"] if sid else None)
    size = paging.per_page_of(per_page, 25)
    pg = paging.paginate(len(props), page, size, "/sources/coverage", {"source": source, "per_page": size if size != 25 else ""},
                         anchor="#proposals", default=25)
    confirmed_names: dict[str, list[str]] = {}
    for s in series.load()["series"]:
        confirmed_names.setdefault(s["source"], []).append(s["name"])
    totals = {"series": len(cov), "complete": sum(c["complete"] for c in cov),
              "missing": sum(c["counts"].get("missing", 0) for c in cov),
              "listed": sum(c["counts"].get("listed", 0) for c in cov)}
    return tpl.TemplateResponse(request, "coverage.html", {
        "coverage": cov, "proposals": props[pg["offset"]:pg["offset"] + size], "pg": pg, "source": source,
        "confirmed_names": confirmed_names, "totals": totals})


def _back_to(request: Request, fallback: str = "/sources/coverage"):
    return RedirectResponse(request.headers.get("referer") or fallback, status_code=303)


@app.post("/series/confirm")
def series_confirm(request: Request, key: str = Form(...), name: str = Form(""), per_year: int = Form(1),
                   into: str = Form("")):
    with db.session() as con:
        prop = next((p for p in series.propose(con) if p["key"] == key), None)
    if prop is None:
        raise HTTPException(404, "proposal not found (already confirmed or rejected?)")
    series.confirm(prop, name or None, max(1, min(per_year, 12)), into or None)
    return _back_to(request)


@app.post("/series/reject")
def series_reject(request: Request, key: str = Form(...)):
    series.reject(key)
    return _back_to(request)


@app.post("/series/absent")
def series_absent(request: Request, source: str = Form(...), name: str = Form(...), year: int = Form(...),
                  lang: str = Form(...), reason: str = Form(""), undo: str = Form("")):
    if undo:
        series.unmark_absent(source, name, year, lang)
    else:
        series.mark_absent(source, name, year, lang, reason)
    return _back_to(request)


@app.post("/series/remove")
def series_remove(request: Request, source: str = Form(...), name: str = Form(...)):
    series.remove(source, name)
    return _back_to(request)


COLLECT_TABS = {"missing": "Missing editions", "blocked": "Blocked downloads", "manual": "Sources to check by hand",
                "inbox": "Inbox"}


@app.get("/collect")
def collect_page(request: Request, tab: str = "missing", source: str = "", page: str = "1", per_page: str = "",
                 added: int = 0, status: str = "", official: str = "", error: str = ""):
    tab = tab if tab in COLLECT_TABS else "missing"
    items = {"missing": collect.missing_editions, "blocked": collect.blocked, "manual": collect.manual_sources,
             "inbox": lambda source="": collect.inbox()}[tab](source)
    size = paging.per_page_of(per_page, 25)
    pg = paging.paginate(len(items), page, size, "/collect",
                         {"tab": tab, "source": source, "per_page": size if size != 25 else ""}, default=25)
    with db.session() as con:
        all_sources = [dict(r) for r in con.execute("SELECT id, key, country, agency FROM sources WHERE active=1 ORDER BY key")]
    notice = None
    if added or error:
        notice = {"doc": added, "status": status, "official": official == "1", "error": error}
    return tpl.TemplateResponse(request, "collect.html", {
        "tab": tab, "tabs": COLLECT_TABS, "counts": collect.status_counts(source), "items": items[pg["offset"]:pg["offset"] + size],
        "pg": pg, "source": source, "all_sources": all_sources, "fresh": collect.freshness(), "notice": notice,
        "today": dt.date.today()})


def _index_new():
    """Text, pages, topics, dates and actors for reports added by hand – unless a job runs (the next update indexes
    them then)."""
    jobrunner.start("index", jobrunner.index_steps, steps=updater.INDEX_STEPS)


def _collect_redirect(request: Request, result: dict | None = None, error: str = ""):
    ref = request.headers.get("referer") or "/collect"
    base = re.sub(r"[?&](added|status|official|error)=[^&#]*", "", ref.split("#")[0])
    q = urlencode({"added": result["doc_id"], "status": result["status"], "official": int(result["official"])}
                  if result else {"error": error[:200]})
    return RedirectResponse(base + ("&" if "?" in base else "?") + q, status_code=303)


@app.post("/collect/upload")
def collect_upload(request: Request, source_id: int = Form(...), url: str = Form(...), file: UploadFile = File(...),
                   title: str = Form(""), lang: str = Form(""), year: str = Form(""), series_name: str = Form("")):
    try:
        result = collect.add_upload(source_id, url, file.file, file.filename or "", title=title, lang=lang, year=year)
    except ValueError as e:
        return _collect_redirect(request, error=str(e))
    if series_name and result["status"] == "downloaded":
        with db.session() as con:
            key = con.execute("SELECT key FROM sources WHERE id=?", (source_id,)).fetchone()["key"]
        series.attach_url(key, series_name, url.strip())
    _index_new()
    return _collect_redirect(request, result)


@app.post("/collect/inbox")
def collect_inbox(request: Request, path: str = Form(...), source_id: int = Form(...), url: str = Form(...),
                  title: str = Form(""), lang: str = Form(""), year: str = Form("")):
    try:
        result = collect.import_inbox(path, source_id, url, title=title, lang=lang, year=year)
    except ValueError as e:
        return _collect_redirect(request, error=str(e))
    _index_new()
    return _collect_redirect(request, result)


@app.post("/collect/attach")
def collect_attach(request: Request, source: str = Form(...), name: str = Form(...), url: str = Form(...)):
    series.attach_url(source, name, url)
    return _back_to(request, "/collect")


@app.post("/collect/checked")
def collect_checked(request: Request, source_id: int = Form(...), note: str = Form("")):
    collect.checked(source_id, note)
    return _back_to(request, "/collect?tab=manual")


@app.post("/jobs/update")
def job_update(request: Request):
    """Older pages' "Update now": a full update of every source, followed on the Update page."""
    jobrunner.update("full", "all")
    return RedirectResponse("/update", status_code=303)


@app.get("/changelog")
def changelog(request: Request):
    import markdown   # our own CHANGELOG.md – trusted content
    text = (HERE.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    html = markdown.markdown(text, extensions=["extra"], output_format="html")
    return tpl.TemplateResponse(request, "changelog.html", {"body": html})


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Browsers ask for /favicon.ico even when the page names its icons."""
    return FileResponse(HERE / "static" / "favicon.ico", media_type="image/x-icon")


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
        "years": years, "countries": sorted(present, key=lambda c: COUNTRY_NAMES.get(c, c))})


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
        "maxdocs": maxdocs, "meta": actors.stamp()})


@app.get("/actors/review")
def actors_review(request: Request, page: str = "1", per_page: str = "", kind: str = "", notice: str = ""):
    """Precision review: random passages of the names with the most impact, to mark right or wrong."""
    q = review.queue(page, paging.per_page_of(per_page, 5) if per_page else 5, kind)
    return tpl.TemplateResponse(request, "review.html", {"q": q, "f": {"kind": kind}, "kinds": actors.KINDS,
                                                        "notice": notice})


@app.post("/actors/review")
def actors_review_verdict(actor: str = Form(...), doc_id: int = Form(...), verdict: str = Form(...), name: str = Form(""),
                          says: str = Form(""), back: str = Form("/actors/review")):
    r = review.record(actor, doc_id, verdict, name, says)
    if "error" in r:
        raise HTTPException(400, r["error"])
    back = back if back.startswith("/") and not back.startswith("//") else "/actors/review"
    return RedirectResponse(back, status_code=303)


@app.get("/actors/names")
def actor_names_page(request: Request, status: str = "used", page: str = "1", per_page: str = ""):
    status = "ignored" if status == "ignored" else "used"
    size = paging.per_page_of(per_page)
    pg = paging.paginate(actors.count_names(status), page, size, "/actors/names",
                         {"status": status if status == "ignored" else ""})
    return tpl.TemplateResponse(request, "actor_names.html", {
        "rows": actors.top_names(size, status, pg["offset"]), "pg": pg, "status": status,
        "kinds": actors.KINDS})


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
    return tpl.TemplateResponse(request, "pair.html", {**d, "pg": pg, "TOPICS": topics.taxonomy()["topics"]})


def _years_desc():
    with db.session() as con:
        return [r[0] for r in con.execute("SELECT DISTINCT year FROM documents WHERE year >= ? ORDER BY year DESC",
                                          (trends.MIN_YEAR,))]


@app.get("/network")
def network_page(request: Request):
    tax = topics.taxonomy()
    return tpl.TemplateResponse(request, "network.html", {
        "kinds": actors.KINDS, "years": _years_desc(), "TOPICS": tax["topics"], "CATEGORIES": tax["categories"]})


@app.get("/api/network")
def api_network(year_from: int = 0, year_to: int = 0, coalition: str = "", type: str = "", topic: str = "",
                countries_too: int = 0, actors_n: int = 60, min_pair: int = 3, threshold: float = 0.25,
                kind: list[str] = Query(default=[])):
    return graphs.associations(year_from or None, year_to or None, coalition, type, topic, bool(countries_too),
                               max(10, min(actors_n, 120)), max(1, min_pair), min(max(threshold, 0.05), 0.9), kind)


@app.get("/map/mentions")
def mentions_page(request: Request):
    return tpl.TemplateResponse(request, "mentions.html", {"years": _years_desc(),
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
    return tpl.TemplateResponse(request, "topic_map.html", {"years": _years_desc()})


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
                                                       "reviewed_out": review.of_actor(key),
                                                       "TOPICS": topics.taxonomy()["topics"]})


@app.get("/api/events")
def api_events():
    return trends.events()


@app.get("/map")
def world_map(request: Request):
    return tpl.TemplateResponse(request, "map.html", {"TYPE_NAMES": TYPE_NAMES})


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


@app.get("/years")
def years_page(request: Request, kind: str = "", source: str = "", page: str = "1", per_page: str = ""):
    """Year conflicts: stored years that strong evidence contradicts, for review."""
    src = int(source) if source.isdigit() else None
    kind = kind if kind in dating.CONFLICT_KINDS else ""
    every = dating.conflicts()
    rows = [c for c in every if (not kind or c["kind"] == kind) and (not src or c["source_id"] == src)]
    size = paging.per_page_of(per_page, 50)
    pg = paging.paginate(len(rows), page, size, "/years", {"kind": kind, "source": source,
                                                           "per_page": size if size != 50 else ""}, default=50)
    by_kind = {k: sum(1 for c in every if c["kind"] == k) for k in dating.CONFLICT_KINDS}
    agencies: dict = {}
    for c in every:
        agencies.setdefault(c["source_id"], {"id": c["source_id"], "agency": c["agency"], "country": c["country"], "n": 0})["n"] += 1
    return tpl.TemplateResponse(request, "years.html", {
        "rows": rows[pg["offset"]:pg["offset"] + size], "pg": pg, "total": len(every), "shown": len(rows),
        "f": {"kind": kind, "source": src}, "kinds": dating.CONFLICT_KINDS, "by_kind": by_kind,
        "agencies": sorted(agencies.values(), key=lambda a: (-a["n"], a["agency"])),
        "decided": len(dating.load_reviews())})


@app.post("/years/resolve")
async def years_resolve(request: Request):
    form = await request.form()
    # a row's own button names its report in the address; the buttons below the table act on the ticked reports
    ids = [int(x) for x in (request.query_params.getlist("doc") or form.getlist("doc")) if str(x).isdigit()]
    dating.resolve(ids, use_found=form.get("action") == "use")
    return _back(request, "/years")


@app.get("/report/{doc_id}")
def report_page(request: Request, doc_id: int):
    """One report: provenance, series and editions, topics with their terms, actors with passages."""
    d = report.detail(doc_id)
    if d is None:
        raise HTTPException(404, "unknown report")
    return tpl.TemplateResponse(request, "report.html", d)


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


@app.post("/doc/{doc_id}/type")
def type_doc(request: Request, doc_id: int, doc_type: str = Form(...)):
    doctypes.set_by_hand(doc_id, doc_type)
    return _back(request, f"/report/{doc_id}")


@app.post("/doc/{doc_id}/edit")
def edit_doc(request: Request, doc_id: int, title: str = Form(...), lang: str = Form(""), year: str = Form("")):
    with db.session() as con:
        old = con.execute("SELECT year, year_source FROM documents WHERE id=?", (doc_id,)).fetchone()
        new_year = int(year) if year.strip().isdigit() else None
        source = old["year_source"] if old and old["year"] == new_year else ("set by hand" if new_year else None)
        con.execute("UPDATE documents SET title=?, lang=?, year=?, year_source=? WHERE id=?",
                    (title.strip(), lang.strip().lower(), new_year, source, doc_id))
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
    return RedirectResponse(f"/documents?source={source_id}", status_code=303)


@app.post("/jobs/crawl")
def job_crawl(request: Request, country: str = Form(""), agency: str = Form(""), source_id: str = Form("")):
    """Check for new reports (all sources, a country or one source) – followed on the Update page."""
    if source_id.isdigit():
        jobrunner.update("check", "sources", sources=[int(source_id)])
    elif country:
        jobrunner.update("check", "country", country=country)
    else:
        jobrunner.update("check", "all")
    return RedirectResponse("/update", status_code=303)


@app.post("/jobs/download")
def job_download(request: Request, country: str = Form(""), retry_failed: str = Form("")):
    jobrunner.update("download", "country" if country else "all", country=country, retry_failed=bool(retry_failed))
    return RedirectResponse("/update", status_code=303)


@app.post("/jobs/sync")
def job_sync(request: Request):
    registry.sync()
    return _back(request, "/sources")
