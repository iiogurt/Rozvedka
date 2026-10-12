"""To collect: uploads, the inbox and missing editions."""
import datetime as dt
import re
from urllib.parse import urlencode
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from .. import collect, db, jobs as jobrunner, paging, series, updater
from ..web import _back_to, tpl

router = APIRouter()

COLLECT_TABS = {"missing": "Missing editions", "blocked": "Blocked downloads", "manual": "Sources to check by hand",
                "inbox": "Inbox"}


@router.get("/collect")
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


@router.post("/collect/upload")
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


@router.post("/collect/inbox")
def collect_inbox(request: Request, path: str = Form(...), source_id: int = Form(...), url: str = Form(...),
                  title: str = Form(""), lang: str = Form(""), year: str = Form("")):
    try:
        result = collect.import_inbox(path, source_id, url, title=title, lang=lang, year=year)
    except ValueError as e:
        return _collect_redirect(request, error=str(e))
    _index_new()
    return _collect_redirect(request, result)


@router.post("/collect/attach")
def collect_attach(request: Request, source: str = Form(...), name: str = Form(...), url: str = Form(...)):
    series.attach_url(source, name, url)
    return _back_to(request, "/collect")


@router.post("/collect/checked")
def collect_checked(request: Request, source_id: int = Form(...), note: str = Form("")):
    collect.checked(source_id, note)
    return _back_to(request, "/collect?tab=manual")


@router.post("/jobs/update")
def job_update(request: Request):
    """Older pages' "Update now": a full update of every source, followed on the Update page."""
    jobrunner.update("full", "all")
    return RedirectResponse("/update", status_code=303)
