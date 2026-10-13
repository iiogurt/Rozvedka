"""All views: every page of the portal, grouped as in the menu, with a live count where there is one."""
from fastapi import APIRouter, Request

from .. import attributions, cves, db, doclist, nav, techniques, threat_levels
from ..web import tpl

router = APIRouter()


@db.cached
def counts() -> dict[str, str]:
    """What each view holds, as a short phrase – every phrase is a number that the page it links to shows."""
    out = {"/documents": f"{doclist.count():,} reports"}
    with db.session() as con:
        n_off = con.execute("SELECT COUNT(*) FROM sources WHERE active=1 AND COALESCE(publisher, 'official') != 'independent'").fetchone()[0]
        n_ind = con.execute("SELECT COUNT(*) FROM sources WHERE active=1 AND publisher = 'independent'").fetchone()[0]
    out["/sources"], out["/publishers"] = f"{n_off} agencies", f"{n_ind} think tanks"
    out["/cves"] = f"{cves.overview()['total']:,} CVE numbers"
    out["/techniques"] = f"{techniques.overview()['total']:,} techniques"
    out["/threat-levels"] = f"{len(threat_levels.load())} statements"
    out["/actors/attributions"] = f"{len(attributions.load())} statements"
    return out


@router.get("/views")
def views(request: Request):
    return tpl.TemplateResponse(request, "views.html", {"c": counts()})
