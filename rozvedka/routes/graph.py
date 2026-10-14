"""The connection graph: overview, the list of links, and a page per entity that is not an actor."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import sanctions, ties
from ..web import tpl

router = APIRouter()


@router.get("/graph")
def graph_page(request: Request):
    """Links by layer, the most linked entities on the official lists, and where the layers meet."""
    return tpl.TemplateResponse(request, "graph.html", {
        "s": ties.summary(), "rank": ties.ranking("official", "", 25), "cross": ties.crossroads(25), "meta": ties.meta(),
        "layers": ties.LAYERS})


@router.get("/graph/ties")
def ties_page(request: Request, entity: str = "", layer: str = "", group: str = "", q: str = "", kind: str = "",
              page: str = "1", per_page: str = ""):
    d = ties.paged(entity, layer if layer in ties.LAYERS else "", group if group in ties.GROUPS else "", q,
                   kind if kind in ties.KINDS else "", page, per_page)
    if entity and not d["focus"]:
        raise HTTPException(404, "no such entity in the network")
    return tpl.TemplateResponse(request, "graph_ties.html", {**d, "layers": ties.LAYERS, "groups": ties.GROUPS,
                                                             "kinds": ties.KINDS})


@router.get("/entity/{id_:path}")
def entity_page(request: Request, id_: str):
    e = ties.entity(id_)
    if not e:
        raise HTTPException(404, "no such entity in the network")
    if e["actor"]:
        return RedirectResponse(f"/actors/{e['actor']}#network", status_code=307)
    return tpl.TemplateResponse(request, "entity.html", {"e": e, "groups": ties.neighbours(id_), "lists": sanctions.LISTS})
