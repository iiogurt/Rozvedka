"""Changelog, favicon and version."""
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from .. import __version__, build_version
from ..web import HERE, tpl

router = APIRouter()


@router.get("/changelog")
def changelog(request: Request):
    import markdown   # our own CHANGELOG.md – trusted content
    text = (HERE.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    html = markdown.markdown(text, extensions=["extra"], output_format="html")
    return tpl.TemplateResponse(request, "changelog.html", {"body": html})


@router.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Browsers ask for /favicon.ico even when the page names its icons."""
    return FileResponse(HERE / "static" / "favicon.ico", media_type="image/x-icon")


@router.get("/api/version")
def version():
    return {"version": __version__, "build": build_version()}


