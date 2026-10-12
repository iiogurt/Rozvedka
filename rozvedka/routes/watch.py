"""Watchlist and the Atom feed."""
from urllib.parse import urlencode
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response
from .. import home, updates, watch
from ..web import tpl

router = APIRouter()


@router.get("/feed.atom")
def atom_feed(request: Request, watch: str = ""):
    return Response(updates.feed(str(request.base_url).rstrip("/"), watch=watch), media_type="application/atom+xml")


@router.get("/watch")
def watch_page(request: Request, notice: str = ""):
    """The watchlist: followed searches, update by update (one shared list)."""
    o = watch.overview()
    for it in o["entries"]:
        if "cells" in it:
            it["latest"] = watch.latest(it["query"])
    return tpl.TemplateResponse(request, "watch.html", {"o": o, "notice": notice, "file": "sources/watchlist.yaml",
                                                       "operators": home.OPERATORS})


@router.post("/watch/add")
def watch_add(query: str = Form(...)):
    r = watch.add(query)
    notice = ("Now watching: " + r["added"]) if "added" in r else ("Already on the list: " + r["exists"]) if "exists" in r \
        else ("Not added – " + r["error"])
    return RedirectResponse("/watch?" + urlencode({"notice": notice}), status_code=303)


@router.post("/watch/remove")
def watch_remove(query: str = Form(...)):
    watch.remove(query)
    return RedirectResponse("/watch?" + urlencode({"notice": "Removed: " + query}), status_code=303)
