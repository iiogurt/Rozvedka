"""The connection graph: overview, the list of links, and a page per entity that is not an actor."""
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from .. import actors, leads, paging, paths, rings, sanctions, techniques, ties, twins, wanted
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
              other_kind: str = "", page: str = "1", per_page: str = ""):
    d = ties.paged(entity, layer if layer in ties.LAYERS else "", group if group in ties.GROUP_FILTERS else "", q,
                   kind if kind in ties.KINDS else "", page, per_page, other_kind if other_kind in ties.KINDS and entity else "")
    if entity and not d["focus"]:
        raise HTTPException(404, "no such entity in the network")
    return tpl.TemplateResponse(request, "graph_ties.html", {**d, "layers": ties.LAYERS, "groups": ties.GROUP_FILTERS,
                                                             "kinds": ties.KINDS})


@router.get("/entity/{id_:path}")
def entity_page(request: Request, id_: str):
    e = ties.entity(id_)
    if not e:
        raise HTTPException(404, "no such entity in the network")
    if e["actor"]:
        return RedirectResponse(f"/actors/{e['actor']}#network", status_code=307)
    return tpl.TemplateResponse(request, "entity.html", {"e": e, "groups": ties.neighbours(id_),
                                                         "lists": {**sanctions.LISTS, **wanted.SOURCES}})


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


@router.get("/graph/rings")
def rings_page(request: Request, e: str = "", show: str = "stated", countries: int = 0):
    """Rings around one entity: its direct links, the entities two steps away, one sector per layer."""
    show = show if show in rings.CHOICES else "stated"
    ent, cands = paths.resolve(e)
    d = rings.rings(ent["id"], show, bool(countries)) if ent else None
    return tpl.TemplateResponse(request, "graph_rings.html", {"e": e, "ev": ent["value"] if ent else e, "d": d, "cands": cands, "choices": rings.CHOICES,
                                                              "f": {"show": show, "countries": countries},
                                                              "inner": rings.INNER, "outer": rings.OUTER, "hub": paths.HUB})


@router.get("/api/entities/suggest")
def api_entity_suggest(q: str = ""):
    """Entities of the network for the path form as one types: actors by any of their names, list entries by label."""
    return {"q": q, "entities": paths.suggest(q)}


@router.get("/graph/twins")
def twins_page(request: Request, q: str = "", page: str = "1", per_page: str = ""):
    """Threat groups that work alike: the most similar toolkits by MITRE ATT&CK, rare items weighted up."""
    rows = twins.ranking(q=q)
    size = paging.per_page_of(per_page, 50)
    pg = paging.paginate(len(rows), page, size, "/graph/twins", {"q": q, "per_page": size if size != 50 else ""}, default=50)
    return tpl.TemplateResponse(request, "twins.html", {"rows": rows[pg["offset"]:pg["offset"] + size], "pg": pg, "q": q,
                                                        "min_shared": twins.MIN_SHARED, "meta": techniques.meta(),
                                                        "groups": len(twins._profiles()["prof"])})


@router.get("/graph/twins/{a}/{b}")
def twins_pair_page(request: Request, a: str, b: str):
    d = twins.pair(a, b)
    if d is None:
        raise HTTPException(404, "not two groups of MITRE ATT&CK")
    return tpl.TemplateResponse(request, "twins_pair.html", {"d": d})


@router.get("/graph/leads")
def leads_page(request: Request, kind: str = "", q: str = "", status: str = "", page: str = "1", per_page: str = ""):
    """Hypotheses: actors never named together, not linked, but sharing neighbours in the stated network."""
    rows = leads.ranking(kind if kind in actors.KINDS else "", q)
    if status == "open":
        rows = [r for r in rows if not r["review"]]
    elif status in leads.VERDICTS:
        rows = [r for r in rows if r["review"] and r["review"]["verdict"] == status]
    size = paging.per_page_of(per_page, 50)
    f = {"kind": kind, "q": q, "status": status}
    pg = paging.paginate(len(rows), page, size, "/graph/leads", {**f, "per_page": size if size != 50 else ""}, default=50)
    reviewed = leads.reviews()
    return tpl.TemplateResponse(request, "leads.html", {
        "rows": rows[pg["offset"]:pg["offset"] + size], "pg": pg, "f": f, "kinds": actors.KINDS, "verdicts": leads.VERDICTS,
        "hub": leads.HUB, "min_shared": leads.MIN_SHARED, "reviewed": len(reviewed),
        "by_verdict": {v: sum(1 for r in reviewed.values() if r["verdict"] == v) for v in leads.VERDICTS}})


@router.get("/graph/leads/{a}/{b}")
def lead_page(request: Request, a: str, b: str, notice: str = ""):
    d = leads.detail(a, b)
    if d is None:
        raise HTTPException(404, "not two actors of the network")
    return tpl.TemplateResponse(request, "lead.html", {"d": d, "notice": notice})


@router.post("/graph/leads/review")
def lead_review(a: str = Form(...), b: str = Form(...), verdict: str = Form(...), note: str = Form("")):
    r = leads.record(a, b, verdict, note)
    if "error" in r:
        raise HTTPException(400, r["error"])
    a, b = sorted((a, b))
    return RedirectResponse(f"/graph/leads/{a}/{b}?notice=saved", status_code=303)


@router.get("/graph/brokers")
def brokers_page(request: Request, kind: str = "", page: str = "1", per_page: str = ""):
    """Entities whose stated links reach actors of several kinds – state, cyber, terror, armed, crime."""
    rows = leads.brokers(kind if kind in leads.DOMAINS else "")
    size = paging.per_page_of(per_page, 50)
    pg = paging.paginate(len(rows), page, size, "/graph/brokers", {"kind": kind, "per_page": size if size != 50 else ""}, default=50)
    return tpl.TemplateResponse(request, "brokers.html", {"rows": rows[pg["offset"]:pg["offset"] + size], "pg": pg, "kind": kind,
                                                          "domains": {d: actors.KINDS[d] for d in leads.DOMAINS}})
