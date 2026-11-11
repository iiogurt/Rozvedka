"""All views: every page of the portal, grouped as in the menu, with a live count where there is one."""
from fastapi import APIRouter, Request

from .. import attributions, books, cves, db, doclist, events, nav, techniques, threat_levels
from ..web import tpl

router = APIRouter()


@db.cached
def counts() -> dict[str, str]:
    """What each view holds, as a short phrase – every phrase is a number that the page it links to shows."""
    out = {"/documents": f"{doclist.count():,} reports"}
    with db.session() as con:
        n_off = con.execute("SELECT COUNT(*) FROM sources WHERE active=1 AND COALESCE(publisher, 'official') = 'official'").fetchone()[0]
        n_ind = con.execute("SELECT COUNT(*) FROM sources WHERE active=1 AND publisher = 'independent'").fetchone()[0]
        n_com = con.execute("SELECT COUNT(*) FROM sources WHERE active=1 AND publisher = 'commercial'").fetchone()[0]
    out["/sources"] = f"{n_off} agencies"
    out["/publishers"] = f"{n_ind} think tanks" + (f", {n_com} commercial analysts" if n_com else "")
    out["/cves"] = f"{cves.overview()['total']:,} CVE numbers"
    out["/techniques"] = f"{techniques.overview()['total']:,} techniques"
    out["/threat-levels"] = f"{len(threat_levels.load())} statements"
    out["/books"] = f"{books.listing(0, 0)[0]:,} books"
    out["/events"] = f"{sum(n for _, n in events.facets()['sources']):,} events"
    out["/actors/attributions"] = f"{len(attributions.load())} statements"
    return out


def rail_counts() -> dict[str, int]:
    """The numbers beside the side menu's rows – the ones the linked pages show (the same as on All views), so a row
    never states a count its page does not. Things whose page states no single total carry none."""
    c = counts()
    n = {key: int(c[link].split()[0].replace(",", "")) for key, link in
         (("reports", "/documents"), ("agencies", "/sources"), ("events", "/events"), ("/cves", "/cves"),
          ("/techniques", "/techniques"), ("/books", "/books")) if c.get(link)}
    return {k: v for k, v in n.items() if v or not k.startswith("/")}


tpl.env.globals["rail_counts"] = rail_counts


@router.get("/views")
def views(request: Request):
    return tpl.TemplateResponse(request, "views.html", {"c": counts()})
