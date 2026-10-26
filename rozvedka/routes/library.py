"""Logos, years, reports, opening and editing documents, adding reports, jobs."""
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from .. import crawler, dating, db, doctypes, downloader, jobs as jobrunner, logos, paging, registry, report
from ..config import FILES
from ..web import tpl

router = APIRouter()

LOGO_TYPES = {"svg": "image/svg+xml", "png": "image/png", "jpg": "image/jpeg", "webp": "image/webp",
              "gif": "image/gif", "ico": "image/x-icon"}


@router.get("/logo/{source_id}")
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


@router.get("/years")
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


@router.post("/years/resolve")
async def years_resolve(request: Request):
    form = await request.form()
    # a row's own button names its report in the address; the buttons below the table act on the ticked reports
    ids = [int(x) for x in (request.query_params.getlist("doc") or form.getlist("doc")) if str(x).isdigit()]
    dating.resolve(ids, use_found=form.get("action") == "use")
    return _back(request, "/years")


@router.get("/report/{doc_id}")
def report_page(request: Request, doc_id: int):
    """One report: provenance, series and editions, topics with their terms, actors with passages."""
    d = report.detail(doc_id)
    if d is None:
        raise HTTPException(404, "unknown report")
    return tpl.TemplateResponse(request, "report.html", d)


@router.get("/doc/{doc_id}")
def open_doc(doc_id: int):
    with db.session() as con:
        d = con.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not d or not d["local_path"]:
        raise HTTPException(404, "not downloaded")
    path = (FILES / d["local_path"]).resolve()
    if not path.is_relative_to(FILES.resolve()) or not path.exists():
        raise HTTPException(404, "file missing")
    if path.suffix.lower() == ".epub":       # a book of the local library: saved, browsers do not show EPUBs
        return FileResponse(path, media_type="application/epub+zip", filename=path.name)
    return FileResponse(path, media_type="application/pdf", filename=path.name, content_disposition_type="inline")


def _back(request: Request, fallback: str = "/"):
    return RedirectResponse(request.headers.get("referer") or fallback, status_code=303)


@router.post("/doc/{doc_id}/download")
def download_doc(request: Request, doc_id: int):
    downloader.download_one(doc_id)
    return _back(request)


@router.post("/doc/{doc_id}/hide")
def hide_doc(request: Request, doc_id: int, hidden: int = Form(1)):
    with db.session() as con:
        con.execute("UPDATE documents SET hidden=? WHERE id=?", (hidden, doc_id))
    return _back(request)


@router.post("/doc/{doc_id}/type")
def type_doc(request: Request, doc_id: int, doc_type: str = Form(...)):
    doctypes.set_by_hand(doc_id, doc_type)
    return _back(request, f"/report/{doc_id}")


@router.post("/doc/{doc_id}/edit")
def edit_doc(request: Request, doc_id: int, title: str = Form(...), lang: str = Form(""), year: str = Form("")):
    with db.session() as con:
        old = con.execute("SELECT year, year_source, lang, lang_why FROM documents WHERE id=?", (doc_id,)).fetchone()
        new_year = int(year) if year.strip().isdigit() else None
        source = old["year_source"] if old and old["year"] == new_year else ("set by hand" if new_year else None)
        new_lang = lang.strip().lower()
        lang_why = old["lang_why"] if old and (old["lang"] or "") == new_lang else "set by hand"
        con.execute("UPDATE documents SET title=?, lang=?, year=?, year_source=?, lang_why=? WHERE id=?",
                    (title.strip(), new_lang, new_year, source, lang_why, doc_id))
    return _back(request)


@router.post("/add")
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


@router.post("/jobs/crawl")
def job_crawl(request: Request, country: str = Form(""), agency: str = Form(""), source_id: str = Form("")):
    """Check for new reports (all sources, a country or one source) – followed on the Update page."""
    if source_id.isdigit():
        jobrunner.update("check", "sources", sources=[int(source_id)])
    elif country:
        jobrunner.update("check", "country", country=country)
    else:
        jobrunner.update("check", "all")
    return RedirectResponse("/update", status_code=303)


@router.post("/jobs/download")
def job_download(request: Request, country: str = Form(""), retry_failed: str = Form("")):
    jobrunner.update("download", "country" if country else "all", country=country, retry_failed=bool(retry_failed))
    return RedirectResponse("/update", status_code=303)


@router.post("/jobs/sync")
def job_sync(request: Request):
    registry.sync()
    return _back(request, "/sources")
