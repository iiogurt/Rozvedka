"""Shared parts of the portal: templates and their helpers, the request guard, the header status. No routes."""
import csv
import datetime as dt
import hashlib
import io
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from . import __version__, build_version, countries, db, guard, nav, publishers, ratings, series, trends, updater
from . import jobs as jobrunner

HERE = Path(__file__).parent

tpl = Jinja2Templates(directory=HERE / "templates")

COUNTRY_NAMES = countries.names()
region_of = countries.region_of
TYPE_NAMES = {
    "intelligence-civil": "Civil intelligence", "intelligence-military": "Military / foreign intelligence",
    "cyber": "Cyber security", "civil-protection": "Civil protection & crisis", "police-ct": "Police / counter-terrorism",
    "eu-body": "EU body", "nato": "NATO", "other": "Other", "think-tank": "Think tank (independent)",
    "commercial": "Commercial analysis (company)",
}
FLAGS = {p.stem for p in (HERE / "static" / "flags").glob("*.svg")}


def flag_url(country: str) -> str:
    code = (country or "").lower()
    return f"/static/flags/{code if code in FLAGS else 'other'}.svg"


def initials(agency: str) -> str:
    """Badge text for agencies without a logo: 'NBÚ' -> 'NBÚ', 'Dept. of the Taoiseach' -> 'DT'."""
    words = [w for w in agency.replace("/", " ").split() if w[:1].isalpha()]
    if len(words) == 1:
        return words[0][:4]
    return "".join(w[0] for w in words if w[0].isupper())[:4] or agency[:3]


def coalition_scope(coalition: str) -> set[str]:
    return countries.scope(coalition)


def coalition_members_of(country: str) -> set[str]:
    """Coalitions a registry entry belongs to (EU bodies count as EU, NATO bodies as NATO)."""
    return set(countries.memberships(country)) | ({country} if country in ("EU", "NATO") else set())


def in_coalition_order(keys) -> list[str]:
    """Coalition keys in the display order of countries.yaml (EU, NATO, Five Eyes, …)."""
    order = list(countries.coalitions())
    return sorted(keys, key=lambda k: order.index(k) if k in order else len(order))


def coalition_tags(country: str) -> list[dict]:
    """Coalition chips for a country, in the order of countries.yaml."""
    mine = countries.memberships(country)
    return [{"key": k, "short": c["short"], "name": c["name"], "since": mine[k]}
            for k, c in countries.coalitions().items() if k in mine]


tpl.env.globals.update(sid=series.sid, COUNTRY_NAMES=COUNTRY_NAMES, TYPE_NAMES=TYPE_NAMES, flag_url=flag_url, initials=initials,
                       coalition_tags=coalition_tags, COALITIONS=countries.coalitions(), VERSION=__version__,
                       BUILD=build_version())

def ico(name: str) -> Markup:
    """An icon of static/icons.svg (Lucide, ISC licence), drawn in the text colour at the text size."""
    return Markup(f'<svg class="ico" aria-hidden="true" viewBox="0 0 24 24"><use href="/static/icons.svg#{escape(name)}"/></svg>')


tpl.env.globals["ico"] = ico
tpl.env.globals["menu"] = nav.menu
tpl.env.filters["num"] = lambda n: f"{n or 0:,}"

_independent: dict = {"at": None, "ids": frozenset(), "levels": {}, "kinds": {}, "books": frozenset()}   # at=None: not loaded yet


def independent_ids() -> frozenset:
    """Sources not run by a state – think tanks and commercial analysts – with their kind and credibility rating;
    refreshed every minute; few rows."""
    if _independent["at"] is None or time.monotonic() - _independent["at"] > 60:
        with db.session() as con:
            rows = con.execute("SELECT id, key, publisher FROM sources WHERE COALESCE(publisher, 'official') NOT IN ('official', 'book')").fetchall()
            _independent["books"] = frozenset(r[0] for r in con.execute("SELECT id FROM sources WHERE publisher='book'"))
        _independent["ids"] = frozenset(r[0] for r in rows)
        _independent["kinds"] = {r[0]: r[2] if r[2] in publishers.KINDS else "independent" for r in rows}
        _independent["levels"] = {r[0]: publishers.profile(r[1], _independent["kinds"][r[0]]) for r in rows}
        _independent["at"] = time.monotonic()
    return _independent["ids"]


def pub_kind(source_id) -> dict | None:
    """{name, plural, mark, type, about} of a source that is not a state agency, else None."""
    return publishers.KINDS[_independent["kinds"][source_id]] if source_id in independent_ids() else None


def pub_mark(source_id, compact: bool = False) -> Markup:
    """The badge that marks a publisher that is not a state agency next to its name, wherever a source or report is shown –
    its kind by the symbol (◆ think tank, ■ commercial analyst) and class, its credibility rating by the colour, opening its
    profile. Compact (narrow rows): the coloured symbol alone, the label in its tooltip."""
    if source_id in independent_ids():
        p, k = _independent["levels"][source_id], pub_kind(source_id)
        text = "" if compact else f"{k['name']} · {escape(p['label'])}"
        cls = "pub-ind" if k["type"] == "think-tank" else "pub-ind pub-com"
        return Markup(f'<a class="{cls} pub-lv-{p["level"]}{" pub-compact" if compact else ""}" href="/publisher/{int(source_id)}" '
                      f'title="{escape(k["about"][0].upper() + k["about"][1:])}. Credibility: {escape(p["label"])} – '
                      f'{escape(p["about"])}. Open its profile">{text}</a>')
    if source_id in _independent["books"]:          # a publishing house of the local book library: not a source of reports
        return Markup(f'<a class="pub-book{" pub-compact" if compact else ""}" href="/books" title="A book of the local library – '
                      f'a secondary source as of its publication, never counted as a report">{"" if compact else "book"}</a>')
    return Markup("")


def pub_profile(source_id):
    return _independent["levels"].get(source_id) if source_id in independent_ids() else None


tpl.env.globals.update(pub_mark=pub_mark, is_independent=lambda sid: sid in independent_ids(), pub_kind=pub_kind,
                       rating=ratings.profile, REGIMES=ratings.REGIMES, pub_profile=pub_profile,
                       PUB_LEVELS=publishers.LEVELS, PUB_KINDS=publishers.KINDS)


def asset(path: str) -> str:
    """URL of a static file with a content stamp (`/static/style.css?v=1a2b3c4d`): a changed file gets a new URL,
    so browsers never keep an old stylesheet or script after an update."""
    f = HERE / "static" / path
    try:
        stat = f.stat()
    except OSError:
        return f"/static/{path}"
    key = (path, stat.st_mtime_ns, stat.st_size)
    if key not in _stamps:
        _stamps[key] = hashlib.sha1(f.read_bytes()).hexdigest()[:8]
    return f"/static/{path}?v={_stamps[key]}"


_stamps: dict[tuple, str] = {}
tpl.env.globals["asset"] = asset


def _page_name(doc_id, page) -> str:
    from . import books
    return books.page_name(doc_id, page)


tpl.env.globals["page_name"] = _page_name       # "p. 123" as printed in a book, "section 4" of an EPUB, else "p. 7"


async def request_guard(request: Request, call_next):
    """No login: refuse unknown host names (DNS rebinding) and changes requested by other sites (CSRF) – rozvedka/guard.py."""
    host = request.headers.get("host", "")
    if not guard.allowed_host(host):
        return PlainTextResponse(f"Host {host!r} is not allowed. Use the machine's address or name, or add it to "
                                 "ROZVEDKA_ALLOWED_HOSTS.", status_code=421)
    if not guard.same_site(request.method, host, request.headers.get("origin"), request.headers.get("referer")):
        return PlainTextResponse("Refused: this request came from another site.", status_code=403)
    response = await call_next(request)
    for k, v in guard.HEADERS.items():
        response.headers.setdefault(k, v)
    return response


async def static_cache(request: Request, call_next):
    """Stamped static files never change (cache for a year); anything else under /static is revalidated each time."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = ("public, max-age=31536000, immutable" if "v" in request.query_params
                                             else "no-cache")
    return response

_age_cache: dict = {}


def header_status() -> dict:
    """For the header's Update button: how old the data is (last check of the report pages) and the running job."""
    now = time.time()
    if now - _age_cache.get("at", 0) > 30:
        with db.session() as con:
            since = updater.all_checked_since(con)
            latest = con.execute("SELECT MAX(last_crawled) FROM pages").fetchone()[0]
        _age_cache.update(at=now, last=since, latest=latest,
                          days=(dt.datetime.now() - dt.datetime.fromisoformat(since[:19])).days if since else None)
    j = jobrunner.state()
    running = j if j and j["status"] == "running" else None
    pct = int(100 * running["progress"]["done"] / running["progress"]["total"]) if running and running["progress"]["total"] else None
    return {"last": _age_cache["last"], "latest": _age_cache["latest"], "days": _age_cache["days"],
            "job": running and running["title"], "pct": pct}


tpl.env.globals["header_status"] = header_status
tpl.env.filters["days_ago"] = lambda ts: (dt.datetime.now() - dt.datetime.fromisoformat(ts[:19])).days


def _back_to(request: Request, fallback: str = "/sources/coverage"):
    return RedirectResponse(request.headers.get("referer") or fallback, status_code=303)


def _abs(request: Request, link: str) -> str:
    return str(request.base_url).rstrip("/") + link


def _csv(name: str, header: list[str], rows) -> Response:
    """Chart data as CSV; every row keeps the link to the documents it counts."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="rozvedka-{name}.csv"'})


def _years_desc():
    with db.session() as con:
        return [r[0] for r in con.execute("SELECT DISTINCT year FROM documents WHERE year >= ? ORDER BY year DESC",
                                          (trends.MIN_YEAR,))]
