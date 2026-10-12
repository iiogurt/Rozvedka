"""Home page, search and the What's new / Compare pages."""
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from .. import compare as compare_mod, db, home, paging, topics, updates
from ..web import COUNTRY_NAMES, flag_url, tpl

router = APIRouter()


@router.get("/")
def home_page(request: Request):
    if request.url.query:   # links and bookmarks from before 0.22.0, when the Documents list was the home page
        return RedirectResponse(f"/documents?{request.url.query}", status_code=307)
    return _home(request)


def _home(request: Request, q: str = "", problems: list | None = None):
    return tpl.TemplateResponse(request, "home.html", {
        "d": home.dashboard(), "q": q, "problems": problems or [], "operators": home.OPERATORS,
        "examples": home.examples()})


@router.get("/search")
def search(request: Request, q: str = ""):
    """The home page's search console: operators (country:, actor:, topic: …) become Documents filters."""
    if not q.strip():
        return RedirectResponse("/documents", status_code=303)
    parsed = home.parse(q)
    if parsed["problems"]:
        return _home(request, q, parsed["problems"])
    return RedirectResponse(home.docs_url(**parsed["params"]), status_code=303)


@router.get("/api/suggest")
def api_suggest(q: str = ""):
    out = home.suggest(q)
    for g in out["groups"]:
        for it in g["items"]:
            if it.get("country"):
                it["flag"] = flag_url(it["country"])
    return out


@router.get("/new")
def whats_new(request: Request, day: str = ""):
    """What's new, update by update (an update = a day on which reports entered the library)."""
    u = updates.update(day or None)
    size = paging.per_page_of(request.query_params.get("per_page"), 100)
    pg = paging.paginate(u.get("n", 0), request.query_params.get("page", "1"), size, "/new", {"day": day},
                         anchor="#reports")
    return tpl.TemplateResponse(request, "new.html", {
        "u": u, "TOPICS": topics.taxonomy()["topics"], "pg": pg,
        "page_docs": u.get("docs", [])[pg["offset"]:pg["offset"] + size],
        "by_source": {g["source_id"]: g for g in u.get("agencies", [])}})


@router.get("/compare")
def compare_page(request: Request, q: str = "", actor: str = "", topic: str = "", year_from: str = "", year_to: str = "",
                 country: str = "", coalition: str = "", type: str = "", page: str = "1", per_page: str = ""):
    """Compare agencies on one question: each agency's densest passages on one actor or topic."""
    problem = ""
    if q.strip() and not (actor or topic):        # the form's subject box: a topic name, else an actor name or alias
        text = q.strip()
        for prefix in ("topic:", "actor:"):
            if text.lower().startswith(prefix):
                text = text[len(prefix):].strip().strip('"')
        with db.session() as con:
            topic = "" if q.lower().startswith("actor:") else (home._topic(text) or "")
            if not topic:
                a = home._actor(con, text)
                actor = a["key"] if a else ""
        if not (actor or topic):
            problem = f"No topic or actor named “{q}” – try the Topics or Actors page."
    year = lambda v: int(v) if v.strip().isdigit() else None   # noqa: E731
    size = paging.per_page_of(per_page, 12) if per_page else 12
    try:
        pnum = max(1, int(page))
    except ValueError:
        pnum = 1
    c = compare_mod.compare(actor, topic, year(year_from), year(year_to), country, coalition, type, pnum, size) \
        if (actor or topic) else None
    pg = None
    if c and "error" not in c:
        pg = paging.paginate(c["n_agencies"], page, size, "/compare",
                             {"actor": actor, "topic": topic, "year_from": c["year_from"], "year_to": c["year_to"],
                              "country": country, "coalition": coalition, "type": type,
                              "per_page": size if size != 12 else ""}, default=12)
    with db.session() as con:
        have = [r[0] for r in con.execute("SELECT DISTINCT country FROM sources WHERE active=1")]
    return tpl.TemplateResponse(request, "compare.html", {
        "c": c, "pg": pg, "problem": problem or (c or {}).get("error", ""), "TOPICS": topics.taxonomy()["topics"],
        "CATEGORIES": topics.taxonomy()["categories"], "countries": sorted(have, key=lambda k: COUNTRY_NAMES.get(k, k)),
        "f": {"q": q if not (actor or topic) else ((c or {}).get("subject") or {}).get("label", q), "actor": actor,
              "topic": topic, "year_from": year_from, "year_to": year_to, "country": country, "coalition": coalition,
              "type": type},
        "examples": [("Wagner Group", "actor"), ("Ransomware & extortion", "topic"), ("Fancy Bear", "actor"),
                     ("Hybrid threats & grey-zone activity", "topic")]})
