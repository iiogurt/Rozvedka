"""Events for the timeline: Wikidata, EuRepoC and UCDP, each with its source (rozvedka/events.py)."""
from fastapi import APIRouter, Request

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
