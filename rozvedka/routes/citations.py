"""Who cites whom: addresses in the reports that point to other reports, other agencies and outside sources."""
from fastapi import APIRouter, Request

from .. import citations
from ..web import tpl

router = APIRouter()


@router.get("/citations")
def citations_page(request: Request):
    return tpl.TemplateResponse(request, "citations.html", citations.overview())
