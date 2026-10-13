"""Actors: list, review, pairs, sanctions, attributions, timeline and actor pages."""
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from .. import actor_events, actor_profiles, actors, attributions, cves, db, graphs, paging, review, sanctions, timeline, topics, trends
from ..web import _years_desc, tpl

router = APIRouter()


@router.get("/actors")
def actors_page(request: Request, kind: str = "", q: str = "", min_docs: int = 2, page: str = "1", per_page: str = ""):
    every = actors.actor_list("", q, max(1, min_docs), include_countries=True)
    counts: dict[str, int] = {}
    for r in every:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    rows = [r for r in every if r["kind"] == kind] if kind else [r for r in every if r["kind"] != "country"]
    size = paging.per_page_of(per_page)
    f = {"kind": kind, "q": q, "min_docs": min_docs, "per_page": size if size != paging.PER_PAGE_CHOICES[2] else ""}
    pg = paging.paginate(len(rows), page, size, "/actors", f)
    maxdocs = max((r["docs"] for r in rows), default=1)
    return tpl.TemplateResponse(request, "actors.html", {
        "rows": rows[pg["offset"]:pg["offset"] + size], "pg": pg, "kinds": actors.KINDS, "counts": counts, "f": f,
        "maxdocs": maxdocs, "meta": actors.stamp(), "precision": review.summary()})


@router.get("/api/actors/suggest")
def api_actor_suggest(q: str = ""):
    """Actors for the search box as one types: names and aliases, accents and misspellings forgiven."""
    return {"q": q, "actors": [{**r, "picture": f"/actor-image/{r['key']}" if actor_profiles.image_path(r["key"]) else None}
                               for r in actors.suggest(q)]}


@router.get("/actors/review")
def actors_review(request: Request, page: str = "1", per_page: str = "", kind: str = "", notice: str = ""):
    """Precision review: random passages of the names with the most impact, to mark right or wrong."""
    q = review.queue(page, paging.per_page_of(per_page, 5) if per_page else 5, kind)
    return tpl.TemplateResponse(request, "review.html", {"q": q, "f": {"kind": kind}, "kinds": actors.KINDS,
                                                        "notice": notice})


@router.post("/actors/review")
def actors_review_verdict(actor: str = Form(...), doc_id: int = Form(...), verdict: str = Form(...), name: str = Form(""),
                          says: str = Form(""), back: str = Form("/actors/review")):
    r = review.record(actor, doc_id, verdict, name, says)
    if "error" in r:
        raise HTTPException(400, r["error"])
    back = back if back.startswith("/") and not back.startswith("//") else "/actors/review"
    return RedirectResponse(back, status_code=303)


@router.get("/actors/names")
def actor_names_page(request: Request, status: str = "used", page: str = "1", per_page: str = ""):
    status = "ignored" if status == "ignored" else "used"
    size = paging.per_page_of(per_page)
    pg = paging.paginate(actors.count_names(status), page, size, "/actors/names",
                         {"status": status if status == "ignored" else ""})
    return tpl.TemplateResponse(request, "actor_names.html", {
        "rows": actors.top_names(size, status, pg["offset"]), "pg": pg, "status": status,
        "kinds": actors.KINDS})


@router.get("/actors/{a}/with/{b}")
def actor_pair_page(request: Request, a: str, b: str, year_from: int = 0, year_to: int = 0, coalition: str = "",
                    topic: str = "", type: str = "", page: str = "1", per_page: str = ""):
    size = paging.per_page_of(per_page, 25)
    d = actors.pair_detail(a, b, year_from or None, year_to or None, coalition, topic, type, size, page)
    if d is None:
        raise HTTPException(404, "unknown actor")
    filters = {"year_from": year_from or "", "year_to": year_to or "", "coalition": coalition, "topic": topic,
               "type": type, "per_page": size if size != 25 else ""}
    pg = paging.paginate(d["docs"], page, size, f"/actors/{a}/with/{b}", filters, default=25)
    return tpl.TemplateResponse(request, "pair.html", {**d, "pg": pg, "TOPICS": topics.taxonomy()["topics"]})


@router.get("/network")
def network_page(request: Request):
    tax = topics.taxonomy()
    return tpl.TemplateResponse(request, "network.html", {
        "kinds": actors.KINDS, "years": _years_desc(), "TOPICS": tax["topics"], "CATEGORIES": tax["categories"]})


@router.get("/api/network")
def api_network(year_from: int = 0, year_to: int = 0, coalition: str = "", type: str = "", topic: str = "",
                countries_too: int = 0, actors_n: int = 60, min_pair: int = 3, threshold: float = 0.25,
                kind: list[str] = Query(default=[])):
    return graphs.associations(year_from or None, year_to or None, coalition, type, topic, bool(countries_too),
                               max(10, min(actors_n, 120)), max(1, min_pair), min(max(threshold, 0.05), 0.9), kind)


@router.get("/actors/sanctions")
def actors_sanctions(request: Request, list_: str = Query("", alias="list"), via: str = "", kind: str = ""):
    """Every actor found on an official sanctions list, with the list, entry and how the name matched."""
    d = sanctions.table(list_, via, kind)
    return tpl.TemplateResponse(request, "sanctions.html", {**d, "kinds": actors.KINDS})


@router.get("/actors/attributions")
def actors_attributions(request: Request):
    """Government statements that name a threat group, each with its quote and when it was last checked on the page."""
    return tpl.TemplateResponse(request, "attributions.html", attributions.overview())


@router.get("/actors/{key}/timeline")
def actor_timeline(request: Request, key: str):
    d = timeline.detail(key)
    if d is None:
        raise HTTPException(404, "unknown actor")
    events = actor_events.of_actor(key)
    marks = {"founded": "●", "dissolved": "○", "designated": "■", "listed": "◆", "attributed": "▲", "threat-level": "▴"}
    lane = {y: [] for y in d["years"]}
    outside = 0
    for e in events:
        if e["kind"] not in marks:
            continue
        y = int(str(e["date"])[:4])
        if y in lane:
            lane[y].append({"mark": marks[e["kind"]], "kind": e["kind"], "title": f"{e['date']}: {e['title']}"})
        else:
            outside += 1
    return tpl.TemplateResponse(request, "actor_timeline.html", {**d, "events": events, "lane": lane, "lane_outside": outside,
                                                                "marks": marks})


@router.get("/actors/{key}")
def actor_page(request: Request, key: str, page: str = "1", per_page: str = ""):
    size = paging.per_page_of(per_page, 25)
    d = actors.actor_detail(key, size, page)
    if d is None:
        raise HTTPException(404, "unknown actor")
    pg = paging.paginate(d["docs"], page, size, f"/actors/{key}", {"per_page": size if size != 25 else ""},
                         anchor="#passages", default=25)
    return tpl.TemplateResponse(request, "actor.html", {**d, "pg": pg, "kinds": actors.KINDS, "meta": actors.stamp(),
                                                       "reviewed_out": review.of_actor(key),
                                                       "sanctions": sanctions.of_actor(key),
                                                       "attributions": attributions.of_actor(key),
                                                       "cve_rows": cves.of_actor(key),
                                                       "sanction_lists": sanctions.LISTS,
                                                       "sanction_dates": sanctions.overview()["retrieved"],
                                                       "TOPICS": topics.taxonomy()["topics"],
                                                       "profile": actor_profiles.profile(key)})


@router.get("/actor-image/{key}")
def actor_image(key: str):
    path = actor_profiles.image_path(key)
    if not path:
        raise HTTPException(404, "no picture")
    return FileResponse(path, media_type=actor_profiles.IMAGE_TYPES.get(path.suffix.lstrip(".").lower(), "application/octet-stream"),
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "max-age=86400"})
