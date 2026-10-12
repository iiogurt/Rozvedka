"""Report series: catalogue, editions, changes and coverage."""
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from .. import actors, changes, db, paging, series, topics
from ..web import COUNTRY_NAMES, _back_to, region_of, tpl

router = APIRouter()


@router.get("/series")
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


@router.get("/series/{series_id}")
def series_page(request: Request, series_id: str, lang: str = ""):
    d = series.detail(series_id, lang)
    if d is None:
        raise HTTPException(404, "unknown series")
    return tpl.TemplateResponse(request, "series_detail.html", {**d, "TOPICS": topics.taxonomy()["topics"],
                                                               "kinds": actors.KINDS})


@router.get("/series/{series_id}/changes")
def series_changes(request: Request, series_id: str, old: int = 0, new: int = 0, lang: str = ""):
    """What one edition of a series says that another did not (default: the two newest with text)."""
    d = series.detail(series_id, lang)
    if d is None:
        raise HTTPException(404, "unknown series")
    withtext = sorted(e["year"] for e in d["editions"] if e["profile_doc"])
    if not (old and new) and len(withtext) >= 2:
        old, new = old or withtext[-2], new or withtext[-1]
    c = changes.diff(series_id, old, new, lang)
    return tpl.TemplateResponse(request, "series_changes.html", {**c, "TOPICS": topics.taxonomy()["topics"]})


@router.get("/sources/coverage")
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


@router.post("/series/confirm")
def series_confirm(request: Request, key: str = Form(...), name: str = Form(""), per_year: int = Form(1),
                   into: str = Form("")):
    with db.session() as con:
        prop = next((p for p in series.propose(con) if p["key"] == key), None)
    if prop is None:
        raise HTTPException(404, "proposal not found (already confirmed or rejected?)")
    series.confirm(prop, name or None, max(1, min(per_year, 12)), into or None)
    return _back_to(request)


@router.post("/series/reject")
def series_reject(request: Request, key: str = Form(...)):
    series.reject(key)
    return _back_to(request)


@router.post("/series/absent")
def series_absent(request: Request, source: str = Form(...), name: str = Form(...), year: int = Form(...),
                  lang: str = Form(...), reason: str = Form(""), undo: str = Form("")):
    if undo:
        series.unmark_absent(source, name, year, lang)
    else:
        series.mark_absent(source, name, year, lang, reason)
    return _back_to(request)


@router.post("/series/remove")
def series_remove(request: Request, source: str = Form(...), name: str = Form(...)):
    series.remove(source, name)
    return _back_to(request)


