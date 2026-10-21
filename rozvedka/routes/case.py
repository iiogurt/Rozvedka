"""The case file: pinned entities and the chains between them (one shared board)."""
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import PlainTextResponse, RedirectResponse

from .. import casefile, paths
from ..web import tpl

router = APIRouter()


def _back(back: str, notice: str) -> RedirectResponse:
    back = back if back.startswith("/") and not back.startswith("//") else "/case"
    sep = "&" if "?" in back else "?"
    return RedirectResponse(back + sep + urlencode({"case": notice}), status_code=303)


@router.get("/case")
def case_page(request: Request, case: str = "", e: str = ""):
    """The case file: pinned entities, how every pair is connected, the entities on several chains."""
    return tpl.TemplateResponse(request, "case.html", {"b": casefile.board(), "notice": case, "e": e,
                                                      "cands": paths.resolve(e)[1] if e else []})


@router.post("/case/pin")
def case_pin(e: str = Form(...), note: str = Form(""), back: str = Form("/case")):
    r = casefile.pin(e, note)
    if r.get("cands"):
        return RedirectResponse("/case?" + urlencode({"e": e, "case": r["error"]}), status_code=303)
    notice = (f"Pinned to the case file: {r['added']}" if "added" in r else f"Already in the case file: {r['exists']}"
              if "exists" in r else "Not pinned – " + r["error"])
    return _back(back, notice)


@router.post("/case/unpin")
def case_unpin(id: str = Form(...)):
    casefile.unpin(id)
    return _back("/case", "Removed from the case file")


@router.post("/case/note")
def case_note(id: str = Form(...), note: str = Form("")):
    casefile.set_note(id, note)
    return _back("/case", "Note saved")


@router.post("/case/clear")
def case_clear():
    casefile.clear()
    return _back("/case", "The case file is empty")


@router.get("/case/export.md")
def case_export(request: Request):
    """The case file as Markdown, with a citation for every step of every chain."""
    return PlainTextResponse(casefile.markdown(str(request.base_url).rstrip("/")), media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="case-file.md"'})
