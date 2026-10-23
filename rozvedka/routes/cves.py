"""CVE numbers named in the reports and CISA's Known Exploited Vulnerabilities list."""
from fastapi import APIRouter, HTTPException, Query, Request

from .. import cves, paging
from ..web import tpl

router = APIRouter()


@router.get("/cves")
def cves_page(request: Request, kev: str = "", q: str = "", ransomware: int = 0, sort: str = "reports",
              page: str = "1", per_page: str = ""):
    """Every CVE number the reports name: how many reports and agencies, and whether CISA lists it as exploited."""
    d = cves.overview(kev if kev in ("yes", "no") else "", q, ransomware, sort)
    size = paging.per_page_of(per_page, 50)
    pg = paging.paginate(len(d["rows"]), page, size, "/cves",
                         {"kev": kev, "q": q, "ransomware": ransomware or "", "sort": sort if sort != "reports" else "",
                          "per_page": size if size != 50 else ""}, default=50)
    return tpl.TemplateResponse(request, "cves.html", {**d, "rows": d["rows"][pg["offset"]:pg["offset"] + size], "pg": pg,
                                                       "f": {"kev": kev, "q": q, "ransomware": ransomware, "sort": sort},
                                                       "lag": cves.lags()})


@router.get("/cves/{cve}")
def cve_page(request: Request, cve: str, page: str = "1", per_page: str = ""):
    d = cves.detail(cve, paging.per_page_of(per_page, 25), page)
    if d is None:
        raise HTTPException(404, "this CVE is not named in any report and not on the Known Exploited list")
    return tpl.TemplateResponse(request, "cve.html", d)
