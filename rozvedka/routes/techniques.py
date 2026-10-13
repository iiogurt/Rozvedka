"""MITRE ATT&CK technique numbers named in the reports."""
from fastapi import APIRouter, HTTPException, Request

from .. import paging, techniques
from ..web import tpl

router = APIRouter()


@router.get("/techniques")
def techniques_page(request: Request, q: str = "", tactic: str = "", sort: str = "reports", page: str = "1", per_page: str = ""):
    """Every ATT&CK technique number the reports name: how many reports and agencies, with MITRE's name and tactics."""
    d = techniques.overview(q, tactic, sort)
    size = paging.per_page_of(per_page, 50)
    pg = paging.paginate(len(d["rows"]), page, size, "/techniques",
                         {"q": q, "tactic": tactic, "sort": sort if sort != "reports" else "",
                          "per_page": size if size != 50 else ""}, default=50)
    return tpl.TemplateResponse(request, "techniques.html", {**d, "rows": d["rows"][pg["offset"]:pg["offset"] + size], "pg": pg,
                                                             "f": {"q": q, "tactic": tactic, "sort": sort}})


@router.get("/techniques/{technique}")
def technique_page(request: Request, technique: str, page: str = "1", per_page: str = ""):
    d = techniques.detail(technique, paging.per_page_of(per_page, 25), page)
    if d is None:
        raise HTTPException(404, "this is not an ATT&CK technique named in a report")
    return tpl.TemplateResponse(request, "technique.html", d)
