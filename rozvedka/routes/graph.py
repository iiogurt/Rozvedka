"""The connection graph: overview, the list of links, and a page per entity that is not an actor."""
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from .. import paths, sanctions, ties
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


@router.get("/graph/path")
def path_page(request: Request, a: str = "", b: str = "", layer: list[str] = Query(default=[]), countries: int = 0):
    """How are two entities connected? – the most specific chains of stated links between them."""
    ea, ca = paths.resolve(a)
    eb, cb = paths.resolve(b)
    layers = [l for l in layer if l in ties.LAYERS] or list(ties.LAYERS)
    found = paths.chains(ea["id"], eb["id"], layers, bool(countries)) if ea and eb else None
    parts = {"a": paths.part(ea["id"]), "b": paths.part(eb["id"])} if ea and eb and not found else None
    return tpl.TemplateResponse(request, "graph_path.html", {
        "a": a, "b": b, "ea": ea, "eb": eb, "ca": ca, "cb": cb, "chains": found, "parts": parts,
        "f": {"layers": layers, "countries": countries, "all": len(layers) == len(ties.LAYERS)},
        "layers": ties.LAYERS, "groups": ties.GROUPS, "base": paths.BASE, "hub": paths.HUB, "max_steps": paths.MAX_STEPS})


@router.get("/api/entities/suggest")
def api_entity_suggest(q: str = ""):
    """Entities of the network for the path form as one types: actors by any of their names, list entries by label."""
    return {"q": q, "entities": paths.suggest(q)}
