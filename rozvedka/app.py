"""Web portal: browse, filter, download and add security reports.

The app itself – middleware, start-up, static files – lives here; the pages are in rozvedka/routes/ (one module per area)
and what they share (templates, helpers, the request guard) in rozvedka/web.py."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import __version__, collect, db, registry
from .routes import actors, citations, collect as collect_routes, cves, data, documents, graph, home, library, maps, misc, series, sources, techniques, threat_levels, trends, update, views, watch
from .web import (HERE, TYPE_NAMES, _age_cache, _independent, request_guard, static_cache, tpl)   # noqa: F401 – re-exported (tests, home.py)

app = FastAPI(title="Rozvedka", version=__version__)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
app.middleware("http")(request_guard)
app.middleware("http")(static_cache)


@app.on_event("startup")
def startup():
    db.init()
    collect.init()
    registry.sync()


# order matters where paths overlap (/actors/sanctions before /actors/{key}); each module keeps its own order
for module in (home, data, update, watch, documents, sources, series, collect_routes, misc, trends, actors, graph, cves, techniques, threat_levels, citations, maps, library, views):
    app.include_router(module.router)
