"""Events and the timeline: Wikidata, EuRepoC and UCDP, each with its source (rozvedka/events.py)."""
from fastapi import APIRouter, HTTPException, Query, Request

from .. import events, paging
from ..web import COUNTRY_NAMES, tpl

router = APIRouter()


@router.get("/events")
def events_page(request: Request, source: str = "", kind: str = "", country: str = "", year: int | None = None,
                q: str = "", actor: str = "", page: int = 1, per_page: str = ""):
    """Every stored event, newest first, filtered by source, kind, state, year, name or actor."""
    size = paging.per_page_of(per_page)
    f = {"source": source, "kind": kind, "country": country.upper(), "year": year, "q": q.strip(), "actor": actor}
    total, _ = events.listing(0, 0, **f)
    pg = paging.paginate(total, page, size, "/events", {**f, "per_page": size if size != paging.PER_PAGE_CHOICES[2] else ""})
    _, rows = events.listing(pg["offset"], size, **f)
    return tpl.TemplateResponse(request, "events.html", {"rows": rows, "pg": pg, "f": f, "facets": events.facets(),
                                                         "meta": events.meta(), "COUNTRY_NAMES": COUNTRY_NAMES})


DEFAULT_LANES = ["country:UA", "country:RU", "country:DE", "country:US"]


@router.get("/timeline")
def timeline_page(request: Request):
    """Lanes of states and actors on one time axis (static/timeline.js draws it from /api/timeline); full screen and a
    wall mode for large screens; the whole view lives in the address."""
    return tpl.TemplateResponse(request, "timeline.html", {"meta": events.meta(), "COUNTRY_NAMES": COUNTRY_NAMES,
                                                           "default_lanes": DEFAULT_LANES})


@router.get("/api/timeline")
def api_timeline(lane: list[str] = Query(default=[])):
    return events.timeline(events.parse_lanes(lane or DEFAULT_LANES)[:12])


@router.get("/api/timeline/event/{key}")
def api_timeline_event(key: str):
    e = events.detail(key)
    if not e:
        raise HTTPException(404, "no such event")
    return e
