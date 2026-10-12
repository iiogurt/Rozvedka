"""Trends pages and their data."""
import csv
import datetime as dt
import io
from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from .. import db, topics, trends
from ..web import COUNTRY_NAMES, _abs, _csv, tpl

router = APIRouter()

TREND_VIEWS = {"topics": "Topics over time", "terms": "Term trends", "matrix": "Who reports on what"}


def _trend_page(request: Request, view: str):
    tax = topics.taxonomy()
    with db.session() as con:
        years = [r[0] for r in con.execute("SELECT DISTINCT year FROM documents WHERE year >= ? ORDER BY year DESC",
                                           (trends.MIN_YEAR,))]
        present = {r[0] for r in con.execute("SELECT DISTINCT country FROM sources WHERE active=1")}
    return tpl.TemplateResponse(request, "trends.html", {
        "view": view, "views": TREND_VIEWS, "TOPICS": tax["topics"], "CATEGORIES": tax["categories"],
        "topic_names": {k: t["name"] for k, t in tax["topics"].items()},
        "years": years, "countries": sorted(present, key=lambda c: COUNTRY_NAMES.get(c, c))})


@router.get("/trends")
def trends_topics(request: Request):
    return _trend_page(request, "topics")


@router.get("/trends/terms")
def trends_terms(request: Request):
    return _trend_page(request, "terms")


@router.get("/trends/matrix")
def trends_matrix(request: Request):
    return _trend_page(request, "matrix")


def _series_csv(request: Request, name: str, data: dict) -> Response:
    rows = []
    den = data["denominator"]
    for s in data["series"]:
        for i, y in enumerate(data["years"]):
            rows.append([s["name"], y, s["docs"][i], den["docs"][i], s["share_docs"][i], s["agencies"][i],
                         den["agencies"][i], s["share_agencies"][i], _abs(request, s["links"][i])])
    return _csv(name, ["series", "year", "documents", "documents_in_scope", "share_of_documents", "agencies",
                       "agencies_in_scope", "share_of_agencies", "source_documents"], rows)


@router.get("/api/trends/topics")
def api_trend_topics(request: Request, topic: list[str] = Query(default=[]), country: str = "", coalition: str = "",
                     type: str = "", format: str = "json"):
    data = trends.topic_trends(topic[:8], country, coalition, type)
    return _series_csv(request, "topic-trends", data) if format == "csv" else data


@router.get("/api/trends/terms")
def api_trend_terms(request: Request, term: list[str] = Query(default=[]), country: str = "", coalition: str = "",
                    type: str = "", format: str = "json"):
    data = trends.term_trends([t for t in term if t.strip()][:8], country, coalition, type)
    return _series_csv(request, "term-trends", data) if format == "csv" else data


@router.get("/api/trends/rising")
def api_trend_rising(country: str = "", coalition: str = "", type: str = ""):
    return trends.rising(country, coalition, type)


@router.get("/api/trends/matrix")
def api_trend_matrix(request: Request, year_from: int = 0, year_to: int = 0, by: str = "country",
                     coalition: str = "", type: str = "", format: str = "json"):
    now = dt.date.today().year
    year_to = year_to or now - 1
    year_from = year_from or year_to - 2
    data = trends.matrix(year_from, year_to, "agency" if by == "agency" else "country", coalition, type)
    if format != "csv":
        return data
    rows_by_key = {r["key"]: r for r in data["rows"]}
    names = {t["key"]: t["name"] for t in data["topics"]}
    return _csv(f"matrix-{year_from}-{year_to}", ["row", "topic", "documents_with_topic", "documents_of_row", "share",
                                                 "source_documents"],
                ([rows_by_key[c["row"]]["label"], names[c["topic"]], c["n"], rows_by_key[c["row"]]["docs"],
                  c["share"], _abs(request, c["link"])] for c in data["cells"]))
