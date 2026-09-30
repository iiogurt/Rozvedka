"""Web portal: browse, filter, download and add security reports."""
import threading
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import __version__, countries, crawler, db, downloader, logos, registry
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
    """Registry country codes in a coalition; the EU and NATO filters also include their own institutions."""
    return countries.members(coalition) | ({coalition} if coalition in ("EU", "NATO") else set())


def coalition_members_of(country: str) -> set[str]:
    """Coalitions a registry entry belongs to (EU bodies count as EU, NATO bodies as NATO)."""
    return set(countries.memberships(country)) | ({country} if country in ("EU", "NATO") else set())


def coalition_tags(country: str) -> list[dict]:
    """Coalition chips for a country, in the order of countries.yaml."""
    mine = countries.memberships(country)
    return [{"key": k, "short": c["short"], "name": c["name"], "since": mine[k]}
            for k, c in countries.coalitions().items() if k in mine]


tpl.env.globals.update(COUNTRY_NAMES=COUNTRY_NAMES, TYPE_NAMES=TYPE_NAMES, flag_url=flag_url, initials=initials,
                       coalition_tags=coalition_tags, COALITIONS=countries.coalitions(), VERSION=__version__)

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
          status: str = "", q: str = "", source: int = 0, page: int = 1, show_hidden: int = 0,
          coalition: str = ""):
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
    if source:
        where.append("s.id=?"); args.append(source)
    if q:
        where.append("(d.title LIKE ? OR d.url LIKE ? OR s.agency LIKE ? OR s.name_local LIKE ? OR s.name_en LIKE ?)")
        args += [f"%{q}%"] * 5
    sql_where = " AND ".join(where)
    per_page = 100
    with db.session() as con:
        total = con.execute(f"SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id WHERE {sql_where}",
                            args).fetchone()[0]
        docs = con.execute(
            f"""SELECT d.*, s.country, s.agency, s.type, s.name_en, s.logo_path
                FROM documents d JOIN sources s ON s.id=d.source_id
                WHERE {sql_where} ORDER BY d.year DESC NULLS LAST, s.country, s.agency, d.lang
                LIMIT ? OFFSET ?""", (*args, per_page, (page - 1) * per_page)).fetchall()
        facets = {
            "country": con.execute("SELECT DISTINCT country FROM sources WHERE active=1 ORDER BY country").fetchall(),
            "type": con.execute("SELECT DISTINCT type FROM sources WHERE active=1 ORDER BY type").fetchall(),
            "lang": con.execute("SELECT DISTINCT lang FROM documents WHERE lang!='' ORDER BY lang").fetchall(),
            "year": con.execute("SELECT DISTINCT year FROM documents WHERE year IS NOT NULL ORDER BY year DESC").fetchall(),
        }
        counts = dict(con.execute("SELECT status, COUNT(*) FROM documents GROUP BY status").fetchall())
    params = dict(country=country, type=type, lang=lang, year=year, status=status, q=q, source=source or "",
                  coalition=coalition,
                  show_hidden=show_hidden or "")
    return tpl.TemplateResponse(request, "index.html", {
        "docs": docs, "total": total, "page": page, "pages": (total + per_page - 1) // per_page,
        "facets": facets, "f": params, "counts": counts, "jobs": dict(_jobs),
        "qs": lambda **kw: urlencode({k: v for k, v in {**params, **kw}.items() if v not in ("", 0, None)}),
    })


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
    return {"version": __version__}


@app.get("/map")
def world_map(request: Request):
    return tpl.TemplateResponse(request, "map.html", {"jobs": dict(_jobs), "TYPE_NAMES": TYPE_NAMES})


@app.get("/api/map")
def map_data():
    """Agencies with HQ coordinates and document counts, plus per-country totals for shading."""
    with db.session() as con:
        rows = con.execute(
            """SELECT s.id, s.country, s.agency, s.name_en, s.name_local, s.type, s.description, s.homepage,
                      s.hq_address, s.lat, s.lon, s.hq_precision, s.logo_path,
                      COUNT(d.id) AS n_docs, COALESCE(SUM(d.status='downloaded'), 0) AS n_ok,
                      MIN(d.year) AS y0, MAX(d.year) AS y1
               FROM sources s LEFT JOIN documents d ON d.source_id=s.id AND d.hidden=0
               WHERE s.active=1 GROUP BY s.id""").fetchall()
    agencies = [{**dict(r), "flag": flag_url(r["country"]), "logo": f"/logo/{r['id']}" if r["logo_path"] else None,
                 "type_name": TYPE_NAMES.get(r["type"], r["type"]),
                 "country_name": COUNTRY_NAMES.get(r["country"], r["country"]),
                 "coalitions": sorted(coalition_members_of(r["country"]))} for r in rows if r["lat"] is not None]
    per_country: dict[str, dict] = {}
    for r in rows:
        if r["country"] in ("EU", "NATO", "OTHER"):
            continue   # organisations, not territories
        c = per_country.setdefault(r["country"], {"name": COUNTRY_NAMES.get(r["country"], r["country"]),
                                                  "agencies": 0, "docs": 0,
                                                  "coalitions": sorted(countries.memberships(r["country"]))})
        c["agencies"] += 1
        c["docs"] += r["n_docs"]
    return {"agencies": agencies, "countries": per_country,
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
