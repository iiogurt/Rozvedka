"""Web portal: browse, filter, download and add security reports."""
import threading
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import crawler, db, downloader, registry
from .config import FILES

HERE = Path(__file__).parent
app = FastAPI(title="Rozvedka")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
tpl = Jinja2Templates(directory=HERE / "templates")

COUNTRY_NAMES = {
    "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "HR": "Croatia", "CY": "Cyprus", "CZ": "Czechia",
    "DK": "Denmark", "EE": "Estonia", "FI": "Finland", "FR": "France", "DE": "Germany", "GR": "Greece",
    "HU": "Hungary", "IE": "Ireland", "IT": "Italy", "LV": "Latvia", "LT": "Lithuania", "LU": "Luxembourg",
    "MT": "Malta", "NL": "Netherlands", "PL": "Poland", "PT": "Portugal", "RO": "Romania", "SK": "Slovakia",
    "SI": "Slovenia", "ES": "Spain", "SE": "Sweden", "EU": "EU bodies", "NATO": "NATO", "OTHER": "Other",
}
TYPE_NAMES = {
    "intelligence-civil": "Civil intelligence", "intelligence-military": "Military / foreign intelligence",
    "cyber": "Cyber security", "civil-protection": "Civil protection & crisis", "police-ct": "Police / counter-terrorism",
    "eu-body": "EU body", "nato": "NATO", "other": "Other",
}
tpl.env.globals.update(COUNTRY_NAMES=COUNTRY_NAMES, TYPE_NAMES=TYPE_NAMES)

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
          status: str = "", q: str = "", source: int = 0, page: int = 1, show_hidden: int = 0):
    where, args = ["s.active=1"], []
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
        where.append("(d.title LIKE ? OR d.url LIKE ? OR s.agency LIKE ? OR s.full_name LIKE ?)")
        args += [f"%{q}%"] * 4
    sql_where = " AND ".join(where)
    per_page = 100
    with db.session() as con:
        total = con.execute(f"SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id WHERE {sql_where}",
                            args).fetchone()[0]
        docs = con.execute(
            f"""SELECT d.*, s.country, s.agency, s.type FROM documents d JOIN sources s ON s.id=d.source_id
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
    return tpl.TemplateResponse(request, "sources.html", {"sources": rows, "pages": pages, "jobs": dict(_jobs)})


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
