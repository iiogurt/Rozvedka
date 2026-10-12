"""Terrorism threat levels of states, with the official passage behind every level."""
from fastapi import APIRouter, Request

from .. import threat_levels
from ..web import tpl

router = APIRouter()


@router.get("/threat-levels")
def threat_levels_page(request: Request):
    return tpl.TemplateResponse(request, "threat_levels.html", threat_levels.overview())
