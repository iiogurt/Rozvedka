"""The local book library (rozvedka/books.py)."""
from fastapi import APIRouter, HTTPException, Request

from .. import books, meanings, paging
from ..web import tpl

router = APIRouter()


@router.get("/books")
def books_page(request: Request, q: str = "", page: int = 1, per_page: str = ""):
    """The books read from data/books/, with their metadata and where each field came from, and what the library found
    in them (topics, actors named most)."""
    size = paging.per_page_of(per_page, 25)
    f = {"q": q.strip(), "per_page": size if size != 25 else ""}
    total, _ = books.listing(0, 0, q=f["q"])
    pg = paging.paginate(total, page, size, "/books", f, default=25)
    _, rows = books.listing(pg["offset"], size, q=f["q"])
    from .. import topics
    return tpl.TemplateResponse(request, "books.html", {"rows": rows, "pg": pg, "f": f, "folder": str(books.BOOKS),
                                                        "TOPICS": topics.taxonomy()["topics"]})


def _book_or_404(doc_id: int) -> dict:
    total, rows = books.listing(0, 1000)
    b = next((r for r in rows if r["doc_id"] == doc_id), None)
    if not b:
        raise HTTPException(404, "not a book of the local library")
    return b


@router.get("/books/{doc_id}/statements")
def book_statements(request: Request, doc_id: int, actor: str = "", page: int = 1, per_page: str = ""):
    """Every sentence of a book that names a gazetteer actor and a date, by date – with its printed page."""
    b = _book_or_404(doc_id)
    size = paging.per_page_of(per_page)
    f = {"actor": actor, "per_page": size if size != paging.PER_PAGE_CHOICES[2] else ""}
    total, _ = meanings.statements(doc_id, 0, 0, actor)
    pg = paging.paginate(total, page, size, f"/books/{doc_id}/statements", f)
    _, rows = meanings.statements(doc_id, pg["offset"], size, actor)
    return tpl.TemplateResponse(request, "book_statements.html", {"b": b, "rows": rows, "pg": pg, "f": f})


@router.get("/books/{doc_id}/relations")
def book_relations(request: Request, doc_id: int, page: int = 1, per_page: str = ""):
    """Who did what to whom, as the book's sentences state it (spaCy's grammar; every relation with its sentence)."""
    b = _book_or_404(doc_id)
    size = paging.per_page_of(per_page)
    f = {"per_page": size if size != paging.PER_PAGE_CHOICES[2] else ""}
    total, _ = meanings.relations(doc_id, 0, 0)
    pg = paging.paginate(total, page, size, f"/books/{doc_id}/relations", f)
    _, rows = meanings.relations(doc_id, pg["offset"], size)
    return tpl.TemplateResponse(request, "book_relations.html", {"b": b, "rows": rows, "pg": pg, "f": f,
                                                                 "VERBS": sorted(meanings.RELATION_VERBS), "parser": bool(meanings.parser())})
