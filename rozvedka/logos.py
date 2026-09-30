"""Fetch each agency's logo from its home page into data/logos/ (not committed: logos are the agencies' marks)."""
import hashlib
import logging
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from . import db, fetch, registry
from .config import DATA

log = logging.getLogger("rozvedka.logos")
LOGOS = DATA / "logos"
MAX_BYTES = 2 * 2**20
IMAGE_TYPES = {"image/svg+xml": "svg", "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
               "image/gif": "gif", "image/x-icon": "ico", "image/vnd.microsoft.icon": "ico"}
LOGO_HINT = re.compile(r"logo|brand|emblem|znak|wappen|herb|crest|signet", re.I)
# shared marks of government web portals – an agency's own logo is preferred over these
PORTAL_MARK = re.compile(r"/be\.svg|logo[_-]?be\b|belogo|blgm|rijksoverheid|marianne|republique|gov[_-]?logo|"
                         r"gov-light|vigipirate|logoslider", re.I)
# other organisations' marks that sit on agency home pages: awards, sponsors, campaigns, EU funding, partners
FOREIGN_MARK = re.compile(r"capital|award|arbeitgeber|azur|partner|sponsor|/eu/|efrp|fundusz|renow|podcast|"
                          r"kampagn|campaign|mikrotik|mindigital|eccc|enisa|cyclone|csirt|zertifizierung|initiative|"
                          r"footer|white|fb-|vigipirate|/bip|gnosis", re.I)


def _size(sizes: str | None) -> int:
    m = re.search(r"(\d+)x(\d+)", sizes or "")
    return int(m.group(1)) if m else 0


def agency_tokens(agency: str) -> set[str]:
    """'OCAD/OCAM/CUTA' -> {'ocad','ocam','cuta'}; used to recognise the agency's own logo file."""
    return {t for t in re.split(r"[^a-z0-9]+", agency.lower()) if len(t) >= 3}


def candidates(html: str, base: str, agency: str = "") -> list[str]:
    """Logo URLs from a home page, best first."""
    tokens = agency_tokens(agency)
    scored = _raw_candidates(html)
    rescored = []
    for score, url in scored:
        fname = urlsplit(urljoin(base, url)).path.lower()
        own = any(t in fname.rsplit("/", 1)[-1] for t in tokens)   # filename, not folders like /BSI/Logos/
        if own:
            score += 50
        if PORTAL_MARK.search(fname):
            score -= 80
        if FOREIGN_MARK.search(fname) and not own:
            score -= 120   # below even the favicon: better an icon than someone else's logo
        rescored.append((score, url))
    seen, out = set(), []
    for _, url in sorted(rescored, key=lambda t: -t[0]):
        full = urljoin(base, url.strip())
        if full not in seen and full.startswith("http"):
            seen.add(full)
            out.append(full)
    return out


def _raw_candidates(html: str) -> list[tuple[int, str]]:
    soup = BeautifulSoup(html, "html.parser")
    scored: list[tuple[int, str]] = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        own_attrs = " ".join([src.rsplit("/", 1)[-1], img.get("alt", ""), " ".join(img.get("class", [])), img.get("id", "")])
        # the image itself must say it is a logo – a "logo" container alone also holds photos and banners
        if src and not src.startswith("data:") and LOGO_HINT.search(own_attrs):
            in_header = img.find_parent(["header"]) is not None
            home_link = img.find_parent("a", href=re.compile(r"^(/|\./|https?://[^/]+/?)$")) is not None
            scored.append((100 + (20 if in_header else 0) + (20 if home_link else 0)
                           + (10 if src.lower().split("?")[0].endswith(".svg") else 0), src))
    for link in soup.find_all("link", href=True):
        rel = " ".join(link.get("rel", [])).lower()
        if "apple-touch-icon" in rel:
            scored.append((80 + min(_size(link.get("sizes")), 180) // 10, link["href"]))
        elif "icon" in rel:
            big = _size(link.get("sizes")) >= 64 or link["href"].lower().endswith(".svg")
            scored.append((60 if big else 30, link["href"]))
    # og:image is deliberately not used: on agency sites it is usually a photo or banner
    scored.append((10, "/favicon.ico"))
    return scored


def _digest(name: str | None) -> str | None:
    return hashlib.sha256((LOGOS / name).read_bytes()).hexdigest() if name and (LOGOS / name).exists() else None


def _save(src_id: int, url: str, lenient: bool) -> str | None:
    tmp = LOGOS / f"{src_id}.part"
    resp = fetch.download(url, tmp, lenient=lenient, max_bytes=MAX_BYTES)
    data = tmp.read_bytes() if tmp.exists() else b""
    tmp.unlink(missing_ok=True)
    ctype = resp.content_type.split(";")[0].strip().lower()
    ext = IMAGE_TYPES.get(ctype)
    if not ext and data.lstrip()[:5] in (b"<?xml", b"<svg ") and b"<svg" in data[:2000]:
        ext = "svg"   # some servers send SVG as text/xml or octet-stream
    if resp.status != 200 or not ext or len(data) < 100:
        return None
    for old in LOGOS.glob(f"{src_id}.*"):
        old.unlink()
    path = LOGOS / f"{src_id}.{ext}"
    path.write_bytes(data)
    return path.name


def _logo_urls(s) -> list[str]:
    urls = [s["logo_url"]] if s["logo_url"] else []
    if s["homepage"]:
        try:
            resp = fetch.get(s["homepage"], lenient=s["access"] == "tls-lenient")
            if resp.status == 200:
                urls += candidates(resp.text, resp.url, s["agency"])
            else:
                urls.append(urljoin(s["homepage"], "/favicon.ico"))
        except Exception as e:  # noqa: BLE001 - a missing logo is cosmetic
            log.info("%s: home page failed (%s)", s["key"], e)
    return urls[:8]


def _fetch_first(s, urls: list[str], avoid: set[str]) -> str | None:
    """Save the first candidate that is an image and not one of the `avoid` digests."""
    for url in urls:
        try:
            name = _save(s["id"], url, s["access"] == "tls-lenient")
        except Exception as e:  # noqa: BLE001
            log.debug("%s: %s failed (%s)", s["key"], url, e)
            continue
        if name and _digest(name) not in avoid:
            return name
    return None


def fetch_logos(refresh: bool = False) -> dict:
    registry.sync()
    LOGOS.mkdir(parents=True, exist_ok=True)
    stats = {"saved": 0, "kept": 0, "failed": 0, "deduplicated": 0}
    with db.session() as con:
        sources = con.execute("SELECT * FROM sources WHERE active=1 ORDER BY country, agency").fetchall()
    urls_by_id: dict[int, list[str]] = {}
    for s in sources:
        if s["logo_path"] and (LOGOS / s["logo_path"]).exists() and not refresh and not s["logo_url"]:
            stats["kept"] += 1
            continue
        urls_by_id[s["id"]] = _logo_urls(s)
        name = _fetch_first(s, urls_by_id[s["id"]], set())
        with db.session() as con:
            con.execute("UPDATE sources SET logo_path=? WHERE id=?", (name, s["id"]))
        stats["saved" if name else "failed"] += 1
        log.info("%-28s %s", s["key"], name or "no logo")

    # Several agencies on one government portal (belgium.be, gov.pl, …) all get the portal's mark.
    # For those, try their remaining candidates for something of their own.
    with db.session() as con:
        rows = con.execute("SELECT * FROM sources WHERE active=1 AND logo_path IS NOT NULL").fetchall()
    by_digest: dict[str, list] = {}
    for r in rows:
        by_digest.setdefault(_digest(r["logo_path"]), []).append(r)
    shared = {d for d, group in by_digest.items() if d and len(group) > 1}
    for d in shared:
        for s in by_digest[d]:
            if s["logo_url"]:
                continue   # chosen by hand in the registry
            urls = urls_by_id.get(s["id"]) or _logo_urls(s)
            # only candidates that are plausibly the agency's own mark
            own_urls = [u for u in urls if not FOREIGN_MARK.search(urlsplit(u).path) and not PORTAL_MARK.search(urlsplit(u).path)]
            name = _fetch_first(s, own_urls, shared)
            if name:
                with db.session() as con:
                    con.execute("UPDATE sources SET logo_path=? WHERE id=?", (name, s["id"]))
                stats["deduplicated"] += 1
                log.info("%-28s own logo instead of shared portal mark: %s", s["key"], name)
            else:
                # nothing distinct: restore the shared logo (_fetch_first may have overwritten the file)
                restored = _fetch_first(s, urls, set())
                with db.session() as con:
                    con.execute("UPDATE sources SET logo_path=? WHERE id=?", (restored, s["id"]))
    return stats
