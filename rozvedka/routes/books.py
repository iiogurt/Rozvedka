"""The local book library (rozvedka/books.py)."""
from fastapi import APIRouter, Request

from .. import books, paging
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
