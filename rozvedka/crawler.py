"""Discover report documents on registry pages (no downloading)."""
import logging
import re
from datetime import datetime
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup

from . import db, fetch, registry
from .config import FOLLOW_LIMIT

log = logging.getLogger("rozvedka.crawl")

DOC_RE = re.compile(
    r"(\.pdf($|[?#]))|__blob=publicationFile|/document/download/|/attachments/[^/]+/download|/file\.html$|/doc/[^/]+\.pdf",
    re.I)
JUNK_RE = re.compile(
    r"cookie|privacy|gdpr|ochrana-osobnich|osobnych-udajov|datenschutz|impressum|"
    r"formular|formulář|tlacivo|application-form|zadost|vacanc|kari[eé]r|career|stellenangebot|tender|zakázk",
    re.I)
# accessibility-statement pages – matched on URL only, since report links often say "barrierefrei"
JUNK_URL_RE = re.compile(r"accessib|pristupnost|barrierefreiheit|toegankelijkheid|/jobs?/", re.I)
REPORT_WORDS = re.compile(
    r"report|annual|review|overview|assessment|threat|landscape|yearbook|situation|"
    r"zpr[aá]v|spr[aá]v|raport|bericht|lagebild|risikobild|verslag|jaarverslag|dreigingsbeeld|rapport|relazion|informe|"
    r"relat[oó]rio|ataskait|gr[eė]sm|p[aā]rskat|aastaraamat|katsaus|[oö]versikt|l[aä]gesbild|vurdering|risikovurdering|"
    r"izvje|poro[cč]il|доклад|evkonyv|évkönyv|jelent|tesat|iocta|socta|fimi|(19[89]\d|20[0-4]\d)",
    re.I)
YEAR_RE = re.compile(r"(?<!\d)(19[89]\d|20[0-4]\d)(?!\d)")

LANG_TOKENS = {
    "en": r"en|eng|english|anglicky|angl|englisch|anglais|engels",
    "cs": r"cs|cz|cze|cesky|česky|cestina", "sk": r"sk|slovensky", "pl": r"pl|polski", "de": r"de|deu|ger|deutsch",
    "fr": r"fr|fra|francais|français", "nl": r"nl|ned|nederlands", "et": r"et|est|eesti", "lv": r"lv|latv",
    "lt": r"lt|liet", "fi": r"fi|fin|suomi", "sv": r"sv|swe|se|svenska", "da": r"da|dk|dansk", "it": r"ita|italiano",
    "es": r"es|esp|español", "pt": r"pt|por", "hu": r"hu|hun", "ro": r"ro|rou", "bg": r"bg|bul", "hr": r"hr|hrv",
    "sl": r"sl|slo|slv", "el": r"el|gr|gre", "ru": r"ru|rus|русский|russian",
}
GENERIC_TITLES = re.compile(r"^(pdf|download|stáhnout|stiahnuť|herunterladen|télécharger|downloaden|ladda ner|lataa|"
                            r"here|zde|tu|více|more|read more|open|\s*|\(pdf.*\)|\d+(\.\d+)? ?[mk]b)$", re.I)


LANG_NAMES = {
    "en": r"english|in english|anglicky|anglická verze|englisch|anglais|engels|englanniksi|på engelska|på engelsk|"
          r"in inglese|en inglés|em inglês|angol|английски|engleski|angleško|angliski|anglų|angļu|inglise",
    "ru": r"русский|на русском|russian|rusky|по-русски|vene keeles|krievu",
    "de": r"deutsch|german|německy|allemand|duits",
    "fr": r"français|french|francouzsky|französisch|frans",
    "sv": r"svenska|swedish|ruotsiksi|på svenska",
}


def guess_lang(url: str, text: str, page_lang: str, allowed: set[str]) -> str:
    """Language from filename tokens (report_EN.pdf), a /xx/ path segment, or link text ("English")."""
    default = page_lang.split("+")[0] if page_lang else ""
    path = urlsplit(url).path
    stem = unquote(path.rsplit("/", 1)[-1]).lower().rsplit(".", 1)[0]
    segs = {s.lower() for s in path.split("/")[:-1]}
    for lang in sorted(allowed, key=lambda l: l == default):   # try non-default languages first
        if re.search(rf"(?<![a-z])({LANG_TOKENS.get(lang, lang)})(?![a-z])", stem) or lang in segs:
            return lang
    for lang, names in LANG_NAMES.items():
        if lang != default and re.search(rf"(?<!\w)({names})(?!\w)", text.lower()):
            return lang
    return default


def guess_year(title: str, url: str) -> int | None:
    for s in (title, unquote(urlsplit(url).path.rsplit("/", 1)[-1]), unquote(urlsplit(url).path)):
        years = [int(y) for y in YEAR_RE.findall(s or "")]
        if years:
            return years[0] if s is title else max(years)
    return None


def _title_for(a) -> str:
    t = " ".join(a.get_text(" ", strip=True).split())
    if GENERIC_TITLES.match(t) or len(t) < 4:
        t = a.get("title") or a.get("aria-label") or ""
    if GENERIC_TITLES.match(t) or len(t) < 4:
        parent = a.find_parent(["li", "tr", "article", "div", "p"])
        if parent:
            t = " ".join(parent.get_text(" ", strip=True).split())[:200]
    if GENERIC_TITLES.match(t) or len(t) < 4 or t.startswith(("/", "http")):
        t = humanize_filename(a["href"])
    return t[:300]


def humanize_filename(url: str) -> str:
    """'/content/vyrocni-zprava-archivu-bis-2024-web.pdf' -> 'vyrocni zprava archivu bis 2024 web'"""
    stem = unquote(urlsplit(url).path.rsplit("/", 1)[-1]).rsplit(".", 1)[0]
    return re.sub(r"[-_+]+", " ", stem).strip() or url


def extract(html: str, base: str) -> tuple[list[dict], list[tuple[str, str]]]:
    """Return (documents, candidate sub-pages) found on a page."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    docs, subs, seen = [], [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        url = urldefrag(urljoin(base, href))[0]
        if url in seen or not url.startswith("http"):
            continue
        seen.add(url)
        title = _title_for(a)
        if JUNK_RE.search(url) or JUNK_RE.search(title) or JUNK_URL_RE.search(url):
            continue
        if DOC_RE.search(url):
            docs.append({"url": url, "title": title})
        elif urlsplit(url).netloc == urlsplit(base).netloc and REPORT_WORDS.search(unquote(url) + " " + title):
            subs.append((url, title))
    return docs, subs


def _store(con, source_id, page_id, docs, page_lang, allowed) -> int:
    new = 0
    for d in docs:
        lang = guess_lang(d["url"], d["title"], page_lang, allowed)
        year = guess_year(d["title"], d["url"])
        cur = con.execute(
            "INSERT OR IGNORE INTO documents(source_id,page_id,url,title,lang,year,origin) VALUES(?,?,?,?,?,?,?)",
            (source_id, page_id, d["url"], d["title"], lang, year, d.get("origin", "crawl")))
        new += cur.rowcount
    return new


def get_page(url: str, src) -> fetch.Response:
    if src["access"] == "browser-js":
        return fetch.render(url)
    resp = fetch.get(url, lenient=src["access"] == "tls-lenient")
    if resp.status == 200 and fetch.CHROMIUM and fetch.looks_like_js_shell(resp):
        log.debug("rendering JS page %s", url)
        return fetch.render(url)
    return resp


def crawl_page(con, src, page, allowed_langs) -> tuple[str, int]:
    resp = get_page(page["url"], src)
    if resp.status != 200:
        return f"http {resp.status}", 0
    if "pdf" in resp.content_type:
        return "ok", _store(con, src["id"], page["id"], [{"url": page["url"], "title": page["note"] or src["agency"]}],
                            page["lang"], allowed_langs)
    docs, subs = extract(resp.text, resp.url)
    followed = 0
    if len(docs) < 3:
        # archive pages often link to one sub-page per report; follow those one level deep
        page_url = page["url"].rstrip("/")
        for url, sub_title in subs:
            if followed >= FOLLOW_LIMIT or url.rstrip("/") == page_url:
                continue
            followed += 1
            try:
                r = get_page(url, src)
                if r.status == 200 and "pdf" in r.content_type:
                    docs.append({"url": url, "title": sub_title})
                elif r.status == 200:
                    sub_docs, _ = extract(r.text, r.url)
                    for d in sub_docs:
                        # a bare filename says little; prefix the title of the page that linked it
                        if d["title"] == humanize_filename(d["url"]) and sub_title:
                            d["title"] = f"{sub_title} – {d['title']}"
                    docs += sub_docs
            except Exception as e:  # noqa: BLE001 - one bad sub-page must not stop the crawl
                log.debug("sub-page %s failed: %s", url, e)
    uniq = {d["url"]: d for d in docs}
    return f"ok ({len(uniq)} docs, {followed} sub-pages)", _store(con, src["id"], page["id"], uniq.values(),
                                                                  page["lang"], allowed_langs)


def add_patterns(con, src) -> int:
    pat = registry.patterns().get(src["key"])
    if not pat or not pat["template"].lower().endswith(".pdf"):
        return 0
    y0, y1 = pat["years"]
    docs = []
    for year in range(y0, y1 + 1):
        for lang in pat.get("langs", [""]):
            docs.append({"url": pat["template"].format(year=year, lang=lang),
                         "title": f"{src['agency']} {year} ({lang})", "origin": "pattern", "lang": lang})
    new = 0
    for d in docs:
        cur = con.execute(
            "INSERT OR IGNORE INTO documents(source_id,url,title,lang,year,origin) VALUES(?,?,?,?,?,?)",
            (src["id"], d["url"], d["title"], d["lang"], guess_year(d["title"], d["url"]), "pattern"))
        new += cur.rowcount
    return new


def crawl(country: str | None = None, agency: str | None = None) -> dict:
    registry.sync()
    stats = {"pages": 0, "new_docs": 0, "errors": 0, "skipped": 0}
    with db.session() as con:
        q = "SELECT * FROM sources WHERE active=1"
        args = []
        if country:
            q += " AND country=?"; args.append(country.upper())
        if agency:
            q += " AND agency=?"; args.append(agency)
        for src in con.execute(q, args).fetchall():
            pages = con.execute("SELECT * FROM pages WHERE source_id=? AND active=1", (src["id"],)).fetchall()
            allowed_langs = {l for p in pages if p["lang"] for l in p["lang"].split("+")} | {"en"}
            stats["new_docs"] += add_patterns(con, src)
            for page in pages:
                stats["pages"] += 1
                if src["access"] == "manual" or (src["access"] == "browser-js" and not fetch.CHROMIUM):
                    status, new = f"skipped ({src['access']})", 0
                    stats["skipped"] += 1
                else:
                    try:
                        status, new = crawl_page(con, src, page, allowed_langs)
                    except fetch.Blocked:
                        status, new = "blocked by robots.txt", 0
                        stats["errors"] += 1
                    except Exception as e:  # noqa: BLE001
                        status, new = f"error: {type(e).__name__}: {e}"[:300], 0
                        stats["errors"] += 1
                stats["new_docs"] += new
                con.execute("UPDATE pages SET last_crawled=?, last_status=? WHERE id=?",
                            (datetime.now().isoformat(timespec="seconds"), status, page["id"]))
                con.commit()
                log.info("%-5s %-18s %-5s %s -> %s, +%d", src["country"], src["agency"][:18], page["lang"],
                         page["url"][:80], status, new)
        con.execute("INSERT INTO runs(kind,finished_at,summary) VALUES('crawl',datetime('now'),?)", (str(stats),))
    return stats
