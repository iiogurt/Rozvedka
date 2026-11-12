"""Briefing pages: one topic, one country (registered after /topics/map so that the map keeps its address)."""
from fastapi import APIRouter, HTTPException, Request

from .. import briefings, home, publishers, ratings, series
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
    from .sources import rating_groups
    groups = rating_groups(d["code"], d["profile"]) if d["profile"] else []
    return tpl.TemplateResponse(request, "briefing_country.html", {"d": d, "groups": groups, "docs_url": home.docs_url,
                                                                   "meta": ratings.load()})


@router.get("/agency/{source_id}")
def agency_page(request: Request, source_id: int):
    """An agency, think tank or commercial analyst on one page: its reports, what they emphasise, its series and the
    pages its reports are collected from."""
    d = briefings.agency(source_id)
    if not d:
        raise HTTPException(404, "no such agency in the library")
    s = d["s"]
    prof = publishers.profile(s["key"], s["publisher"]) if s["publisher"] in publishers.KINDS else None
    return tpl.TemplateResponse(request, "agency.html", {"d": d, "s": s, "series_of": series.by_source().get(s["key"], []),
                                                         "prof": prof, "kind": publishers.KINDS.get(s["publisher"])})
