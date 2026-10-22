"""Briefing pages: one topic, one country (registered after /topics/map so that the map keeps its address)."""
from fastapi import APIRouter, HTTPException, Request

from .. import briefings, topics
from ..web import tpl

router = APIRouter()


@router.get("/topics/{key}")
def topic_page(request: Request, key: str):
    """A topic on one page: its reports year by year, who writes about it, the actors and topics its reports emphasise."""
    d = briefings.topic(key)
    if not d:
        raise HTTPException(404, "no such topic")
    return tpl.TemplateResponse(request, "briefing_topic.html", {"d": d})


@router.get("/countries")
def countries_page(request: Request):
    return tpl.TemplateResponse(request, "countries.html", {"rows": briefings.index()})


@router.get("/countries/{code}")
def country_page(request: Request, code: str):
    """A state on one page: its agencies, what their reports emphasise, who reports about it, its ratings and events."""
    d = briefings.country(code)
    if not d:
        raise HTTPException(404, "no such country in the library")
    return tpl.TemplateResponse(request, "briefing_country.html", {"d": d})
