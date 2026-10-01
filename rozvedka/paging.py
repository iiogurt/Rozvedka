"""Pagination shared by every list in the portal (templates/_pager.html renders it)."""
import math
from urllib.parse import urlencode

PER_PAGE_CHOICES = (25, 50, 100, 200, 500)


def per_page_of(value: int | str | None, default: int = 100) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return v if v in PER_PAGE_CHOICES else default


def page_offset(total: int, page: int | str | None, per_page: int) -> int:
    """Offset of the (clamped) page – the same clamping as paginate(), for code that slices before rendering."""
    pages = max(1, math.ceil(total / per_page)) if per_page else 1
    try:
        page = int(page or 1)
    except (TypeError, ValueError):
        page = 1
    return (min(max(page, 1), pages) - 1) * per_page


def paginate(total: int, page: int | str | None, per_page: int, path: str, params: dict, anchor: str = "",
             default: int = 100) -> dict:
    """Everything the pager needs: clamped page, offset, numbered window and the links.

    `params` are the list's other query parameters (filters); they are kept in every link and in the
    "go to page" form, so changing page never loses a filter.
    """
    pages = max(1, math.ceil(total / per_page)) if per_page else 1
    try:
        page = int(page or 1)
    except (TypeError, ValueError):
        page = 1
    page = min(max(page, 1), pages)
    keep = {k: v for k, v in params.items() if v not in ("", None, [], 0) and k not in ("page", "per_page")}

    def href(p: int, pp: int = per_page) -> str:
        q = {**keep, "page": p if p > 1 else "", "per_page": pp if pp != default else ""}
        return path + "?" + urlencode({k: v for k, v in q.items() if v not in ("", None)}, doseq=True) + anchor

    # 1 … 5 6 [7] 8 9 … 30
    window = sorted({1, pages, *range(max(1, page - 2), min(pages, page + 2) + 1)})
    items, prev = [], 0
    for n in window:
        if n - prev > 1:
            items.append(None)
        items.append(n)
        prev = n
    first = (page - 1) * per_page
    return {
        "page": page, "pages": pages, "per_page": per_page, "total": total, "offset": first,
        "first": first + 1 if total else 0, "last": min(first + per_page, total),
        "numbers": [{"n": n, "href": href(n) if n else None, "current": n == page} for n in items],
        "prev": href(page - 1) if page > 1 else None, "next": href(page + 1) if page < pages else None,
        "first_href": href(1) if page > 1 else None, "last_href": href(pages) if page < pages else None,
        "choices": [{"n": c, "href": href(1, c), "current": c == per_page} for c in PER_PAGE_CHOICES],
        "path": path, "keep": keep, "anchor": anchor, "default": default,
    }
