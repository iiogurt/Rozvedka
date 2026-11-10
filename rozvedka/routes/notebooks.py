"""Research notebooks: passages marked in reports, with notes, exported with citations (one shared set)."""
import re
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse

from .. import notebooks
from ..web import local_url, tpl

router = APIRouter()


def _back(back: str, fallback: str, notice: str) -> RedirectResponse:
    back, _, frag = (back or "").partition("#")      # the place on the page to return to
    path = local_url(back, fallback.partition("#")[0])
    if path != back:
        frag = fallback.partition("#")[2]
    frag = frag if re.fullmatch(r"[\w-]{1,40}", frag) else ""
    sep = "&" if "?" in path else "?"
    return RedirectResponse(path + sep + urlencode({"nb": notice}) + ("#" + frag if frag else ""), status_code=303)


def _added(r: dict) -> str:
    if "added" in r:
        return f"Added to the notebook “{r['notebook']}”"
    if "exists" in r:
        return f"Already in the notebook “{r['notebook']}”"
    return "Not added – " + r["error"]


@router.get("/notebooks")
def notebooks_page(request: Request, nb: str = ""):
    """Every notebook: how many passages from how many reports; create one, choose where new passages go."""
    return tpl.TemplateResponse(request, "notebooks.html", {"o": notebooks.overview(), "notice": nb,
                                                           "file": notebooks.path().name})


@router.get("/notebooks/{slug}")
def notebook_page(request: Request, slug: str, nb: str = ""):
    book = notebooks.notebook(slug)
    if book is None:
        raise HTTPException(404, "No such notebook")
    return tpl.TemplateResponse(request, "notebook.html", {"nb": book, "notice": nb, "print": False})


@router.get("/notebooks/{slug}/print")
def notebook_print(request: Request, slug: str):
    """The notebook laid out for printing or saving as PDF from the browser."""
    book = notebooks.notebook(slug)
    if book is None:
        raise HTTPException(404, "No such notebook")
    return tpl.TemplateResponse(request, "notebook_print.html", {"nb": book, "base": str(request.base_url).rstrip("/")})


@router.get("/notebooks/{slug}/export.md")
def notebook_export(request: Request, slug: str):
    """The notebook as Markdown: the passages, the notes and a numbered list of sources."""
    md = notebooks.markdown(slug, str(request.base_url).rstrip("/"))
    if md is None:
        raise HTTPException(404, "No such notebook")
    return PlainTextResponse(md, media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f"attachment; filename=\"{quote(slug)}.md\""})


@router.post("/notebooks/new")
def notebook_new(name: str = Form(...), back: str = Form("")):
    r = notebooks.create(name)
    if "error" in r:
        return _back(back, "/notebooks", "Not created – " + r["error"])
    slug = r.get("added") or r.get("exists")
    notice = "Notebook created – new passages go there" if "added" in r else "That notebook exists – new passages go there"
    return _back(back or f"/notebooks/{slug}", f"/notebooks/{slug}", notice)


@router.post("/notebooks/current")
def notebook_current(slug: str = Form(...), back: str = Form("/notebooks")):
    ok = notebooks.set_current(slug)
    return _back(back, "/notebooks", "New passages go to this notebook" if ok else "No such notebook")


@router.post("/notebooks/rename")
def notebook_rename(slug: str = Form(...), name: str = Form(...)):
    notebooks.rename(slug, name)
    return _back(f"/notebooks/{slug}", "/notebooks", "Renamed")


@router.post("/notebooks/delete")
def notebook_delete(slug: str = Form(...)):
    ok = notebooks.delete(slug)
    return _back("/notebooks", "/notebooks", "Notebook deleted" if ok else "No such notebook")


@router.post("/notebooks/add")
def notebook_add(doc: int = Form(...), start: int = Form(...), end: int = Form(...), note: str = Form(""),
                 slug: str = Form(""), widen: int = Form(0), back: str = Form("")):
    """Mark a passage the portal shows (an actor's passage on a report page) – widened to its sentence."""
    r = notebooks.add(doc, start, end, note, slug or None, widen=bool(widen))
    return _back(back, f"/report/{doc}", _added(r))


@router.post("/notebooks/add-text")
def notebook_add_text(doc: int = Form(...), text: str = Form(...), note: str = Form(""), slug: str = Form(""),
                      back: str = Form("")):
    """Mark a passage pasted from the report: found in its text and kept as worded there, with its page."""
    r = notebooks.add_text(doc, text, note, slug or None)
    return _back(back, f"/report/{doc}", _added(r))


@router.post("/notebooks/note")
def notebook_note(slug: str = Form(...), id: str = Form(...), note: str = Form("")):
    notebooks.set_note(slug, id, note)
    return _back(f"/notebooks/{slug}#n-{id}", "/notebooks", "Note saved")


@router.post("/notebooks/remove")
def notebook_remove(slug: str = Form(...), id: str = Form(...)):
    notebooks.remove(slug, id)
    return _back(f"/notebooks/{slug}", "/notebooks", "Passage removed")


@router.post("/notebooks/move")
def notebook_move(slug: str = Form(...), id: str = Form(...), step: int = Form(...)):
    notebooks.move(slug, id, -1 if step < 0 else 1)
    return _back(f"/notebooks/{slug}#n-{id}", "/notebooks", "Moved")
