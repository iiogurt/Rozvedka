"""Discover report documents on registry pages (no downloading)."""
import json
import logging
import re
from datetime import datetime, timedelta
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from . import db, fetch, progress, registry
from .config import FOLLOW_LIMIT

log = logging.getLogger("rozvedka.crawl")
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)   # some sites serve XHTML as XML

DOC_RE = re.compile(
    r"(\.pdf($|[?#]))|__blob=publicationFile|/document/download/|/attachments/[^/]+/download|/file\.html$|/doc/[^/]+\.pdf|"
    r"/documents/[^?#]*\.pdf/|"   # Liferay document library: /documents/<ids>/<name>.pdf/<uuid>?download=true
    r"/bitstreams?/[^?#]+/download|"  # DSpace repositories: /bitstreams/<uuid>/download
    r"/library/\?itemid=",            # Episerver media libraries (Icelandic government: stjornarradid.is/library/?itemid=…)
    re.I)
JUNK_RE = re.compile(
    r"cookie|privacy|gdpr|ochrana-osobnich|osobnych-udajov|datenschutz|impressum|"
    r"formular|formulář|tlacivo|application-form|zadost|vacanc|kari[eé]r|career|stellenangebot|tender|zakázk|"
    r"rfc.?2350|eidas",            # a CERT's RFC 2350 self-description, trust-service lists: not reports
    re.I)
# accessibility-statement pages – matched on URL only, since report links often say "barrierefrei"
JUNK_URL_RE = re.compile(r"accessib|pristupnost|barrierefreiheit|toegankelijkheid|/jobs?/", re.I)
REPORT_WORDS = re.compile(
    r"report|annual|review|overview|assessment|threat|landscape|yearbook|situation|"
    r"zpr[aá]v|spr[aá]v|raport|bericht|lagebild|risikobild|verslag|jaarverslag|dreigingsbeeld|rapport|relazion|informe|"
    r"relat[oó]rio|ataskait|gr[eė]sm|p[aā]rskat|aastaraamat|katsaus|[oö]versikt|l[aä]gesbild|vurdering|risikovurdering|"
    r"izvje|poro[cč]il|доклад|evkonyv|évkönyv|jelent|tesat|iocta|socta|fimi|(19[89]\d|20[0-4]\d)|"
    r"publikation|publication|publicaties|risk|risiko|dokumenti|lagebericht|"
    r"sk[yý]rsl|rapor|извешт|проценк|publikacii|yay[iı]nlar",
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
GENERIC_TITLES = re.compile(
    r"^\s*((download|stáhnout|stiahnuť|stiahnut|pobierz|herunterladen|télécharger|downloaden|ladda ner|lataa|"
    r"descargar|scarica|descarcă|изтегли|preuzmi|prenesi|letöltés|here|zde|tu|více|more|read more|open|otevřít|"
    r"view|zobrazit)\s*)?(pdf|file|soubor|dokument|document)?\s*(\(?[\d.,]+\s*[mk]i?b\)?|\(pdf[^)]*\))?\s*$", re.I)
# link texts that are calls to action, not titles ("Click here to access our report")
_CTA_WORDS = re.compile(
    r"(?<!\w)(click|klikn\w*|cliquez|download\w*|télécharg\w*|herunterladen|stáhn\w*|stiahn\w*|pobierz|scarica|"
    r"descarg\w*|consultez|here|hier|ici|zde|tady)(?!\w)", re.I)


class _CallToAction:
    """Short link text built around 'click/download/here' with no year in it – not a real title."""
    @staticmethod
    def match(text: str) -> bool:
        t = (text or "").strip()
        return len(t) <= 80 and bool(_CTA_WORDS.search(t)) and not YEAR_RE.search(t)


CALL_TO_ACTION = _CallToAction()
# kept but hidden by default: administrative documents that are not security reports
LOW_RELEVANCE_RE = re.compile((
    r"contract|procurement|corrigendum|questionnaire|formulier|zakázk|veřejn[aá] zak|кандидат|конкурс|класиране|"
    r"interes public|acces la informa|poskytov[aá]n[ií] informac|106/1999|access to information|freedom of information|"
    r"human resources|recruit|n[aá]bor|vacanc|stellenausschreibung|budget|rozpo[cč]et|bilan[tț] contabil|"
    r"sluzebni|služební|výběrov[eé] řízen|ausschreibung|relationarea .* cu publicul|"
    r"protocolo de servicio|política de tratamiento de datos|politica de relacionamiento|política de relacionamiento|"
    r"carta de trato digno|lenguaje claro|participación ciudadana|manuales de comunicación|"
    r"reporte complementario|informe de emergencia n|boletín informativo sísmico|boletin informativo sismico"
).replace(" ", r"[\s_-]+"), re.I)   # filenames use _ or - where titles use spaces


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
    # years after the current one are horizons ("NATO 2030", "Trends 2035"), not publication years
    now = datetime.now().year
    for s in (title, unquote(urlsplit(url).path.rsplit("/", 1)[-1]), unquote(urlsplit(url).path)):
        years = [y for y in map(int, YEAR_RE.findall(s or "")) if y <= now]
        if years:
            return years[0] if s is title else max(years)
    return None


_SIZE_SUFFIX = re.compile(r"\s*[\(\[]\s*(?:pdf[,\s]*)?[\d.,]+\s*[kmg]i?b\s*[\)\]]\s*$", re.I)


def _title_for(a) -> str:
    t = _SIZE_SUFFIX.sub("", " ".join(a.get_text(" ", strip=True).split()))
    if GENERIC_TITLES.match(t) or CALL_TO_ACTION.match(t) or len(t) < 4:
        t = a.get("title") or a.get("aria-label") or ""
    if GENERIC_TITLES.match(t) or CALL_TO_ACTION.match(t) or len(t) < 4:
        parent = a.find_parent(["li", "tr", "article", "div", "p"])
        if parent:
            t = " ".join(parent.get_text(" ", strip=True).split())[:200]
        if CALL_TO_ACTION.match(t):
            t = ""   # the surrounding text is the same call to action – use the filename instead
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
    base_tag = soup.find("base", href=True)
    if base_tag:   # e.g. bund.de sites resolve every relative link against <base href>
        base = urljoin(base, base_tag["href"])
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


def is_poor_title(title: str | None, url: str) -> bool:
    return (not title or bool(GENERIC_TITLES.match(title)) or bool(CALL_TO_ACTION.match(title))
            or title == humanize_filename(url) or bool(re.fullmatch(r"[\w .%()-]+\.pdf", title, re.I)))


def domain_family(url_or_host: str) -> str:
    """'assets.publishing.service.gov.uk' -> 'gov.uk', 'www.bis.cz' -> 'bis.cz' (government domain families)."""
    host = urlsplit(url_or_host).hostname if "//" in url_or_host else url_or_host
    return ".".join((host or "").lower().split(".")[-2:])


def official_families(src, page_url: str | None) -> set[str]:
    fams = {domain_family(page_url or ""), domain_family(src["homepage"] or "")}
    fams |= {domain_family(d.strip()) for d in (src["domains"] or "").split(",") if d.strip()}
    return fams - {""}


def _store(con, source_id, page_id, docs, page_lang, allowed, families: set[str] | None = None) -> int:
    new = 0
    for d in docs:
        if families and domain_family(d["url"]) not in families:
            continue   # cited third-party document (footnote, partner report) – not this agency's publication
        lang = guess_lang(d["url"], d["title"], page_lang, allowed)
        year = guess_year(d["title"], d["url"])
        hidden = 1 if LOW_RELEVANCE_RE.search(d["title"] + " " + unquote(d["url"])) else 0
        old = con.execute("SELECT id, title FROM documents WHERE url=?", (d["url"],)).fetchone()
        if old is None:
            con.execute(
                "INSERT INTO documents(source_id,page_id,url,title,lang,year,origin,hidden) VALUES(?,?,?,?,?,?,?,?)",
                (source_id, page_id, d["url"], d["title"], lang, year, d.get("origin", "crawl"), hidden))
            new += 1
        elif is_poor_title(old["title"], d["url"]) and not is_poor_title(d["title"], d["url"]):
            # a later crawl found a better title (e.g. from the linking sub-page) – keep that one
            con.execute("UPDATE documents SET title=?, year=COALESCE(year, ?) WHERE id=?", (d["title"], year, old["id"]))
    return new


def get_page(url: str, src) -> fetch.Response:
    if src["access"] == "browser-js":
        return fetch.render(url)
    resp = fetch.get(url, lenient=src["access"] == "tls-lenient")
    if resp.status == 200 and fetch.CHROMIUM and fetch.looks_like_js_shell(resp):
        log.debug("rendering JS page %s", url)
        try:
            return fetch.render(url)
        except Exception as e:  # noqa: BLE001 - a failed render must not lose the page we already have
            log.debug("render failed for %s: %s", url, e)
    return resp


def crawl_page(con, src, page, allowed_langs) -> tuple[str, int]:
    resp = get_page(page["url"], src)
    if resp.status != 200:
        return f"http {resp.status}", 0
    # the agency's own page may redirect to another of its domains (crisiscentrum.be → crisiscenter.be): trust that too
    families = official_families(src, page["url"]) | ({domain_family(resp.url)} if getattr(resp, "url", None) else set())
    if "pdf" in resp.content_type:
        return "ok", _store(con, src["id"], page["id"], [{"url": page["url"], "title": page["note"] or src["agency"]}],
                            page["lang"], allowed_langs)
    docs, subs = extract(resp.text, resp.url)
    if not docs and fetch.CHROMIUM and src["access"] != "browser-js":
        # nothing found in the raw HTML – the list may be built by JavaScript; try once in a browser
        try:
            rendered = fetch.render(page["url"])
            r_docs, r_subs = extract(rendered.text, page["url"])
            if len(r_docs) + len(r_subs) > len(docs) + len(subs):
                docs, subs = r_docs, r_subs
        except Exception as e:  # noqa: BLE001
            log.debug("render fallback failed for %s: %s", page["url"], e)
    followed = 0
    # archive pages often link to one sub-page per report ("Annual report 2021" → its page with the PDF); follow those
    # one level deep when the page has few documents of its own, or more year-specific report pages than documents
    # (the few PDFs then are usually site navigation)
    yearly = [(u, t) for u, t in subs if YEAR_RE.search(unquote(u) + " " + t)]
    if len(docs) < 3 or len(yearly) > len(docs):
        page_url = page["url"].rstrip("/")
        for url, sub_title in (subs if len(docs) < 3 else yearly):
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
                                                                  page["lang"], allowed_langs, families)


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


def fix_future_years(con) -> int:
    """Re-guess years stored before guess_year ignored horizon years (a report cannot be from the future)."""
    rows = con.execute("SELECT id, title, url FROM documents WHERE year > ?", (datetime.now().year,)).fetchall()
    for r in rows:
        con.execute("UPDATE documents SET year=? WHERE id=?", (guess_year(r["title"], r["url"]), r["id"]))
    return len(rows)


def selection(con, country: str | None = None, agency: str | None = None, source_ids=None,
              stale_days: int | None = None) -> list[tuple]:
    """The (source, its active pages) a crawl will visit: optionally one country, one agency, chosen sources, or the
    sources not checked for `stale_days` days (their pages crawled longest ago or never)."""
    q, args = "SELECT * FROM sources WHERE active=1", []
    if country:
        q += " AND country=?"; args.append(country.upper())
    if agency:
        q += " AND agency=?"; args.append(agency)
    if source_ids:
        ids = [int(i) for i in source_ids]
        q += f" AND id IN ({','.join('?' * len(ids))})"; args += ids
    out = []
    cutoff = (datetime.now() - timedelta(days=stale_days)).isoformat(timespec="seconds") if stale_days else None
    for src in con.execute(q + " ORDER BY country, agency", args).fetchall():
        pages = con.execute("SELECT * FROM pages WHERE source_id=? AND active=1", (src["id"],)).fetchall()
        if cutoff and pages and all((p["last_crawled"] or "") >= cutoff for p in pages):
            continue          # checked recently enough
        out.append((src, pages))
    return out


def crawl(country: str | None = None, agency: str | None = None, source_ids=None, stale_days: int | None = None) -> dict:
    """Visit the report pages and record new reports (links only). Reports progress per page; a cancelled crawl stops
    between pages – what was found so far is kept."""
    started = datetime.now().isoformat(timespec="seconds")
    registry.sync()
    stats = {"pages": 0, "new_docs": 0, "errors": 0, "skipped": 0, "sources": {}}
    with db.session() as con:
        stats["years_fixed"] = fix_future_years(con)
        chosen = selection(con, country, agency, source_ids, stale_days)
        total = sum(len(p) for _, p in chosen)
        log.info("checking %d report pages of %d sources", total, len(chosen))
        for src, pages in chosen:
            per = stats["sources"].setdefault(src["key"], {"pages": 0, "new": 0, "errors": 0, "skipped": 0})
            allowed_langs = {l for p in pages if p["lang"] for l in p["lang"].split("+")} | {"en"}
            found = add_patterns(con, src)
            stats["new_docs"] += found
            per["new"] += found
            for page in pages:
                progress.tick("Checking report pages", stats["pages"], total, note=f"{src['country']} {src['agency']}")
                stats["pages"] += 1
                per["pages"] += 1
                if src["access"] == "manual" or (src["access"] == "browser-js" and not fetch.CHROMIUM):
                    status, new = f"skipped ({src['access']})", 0
                    stats["skipped"] += 1
                    per["skipped"] += 1
                elif not page["verified"]:
                    status, new = "skipped (blocked page – open in browser)", 0
                    stats["skipped"] += 1
                    per["skipped"] += 1
                else:
                    try:
                        status, new = crawl_page(con, src, page, allowed_langs)
                    except fetch.Blocked:
                        status, new = "blocked by robots.txt", 0
                        stats["errors"] += 1
                        per["errors"] += 1
                    except Exception as e:  # noqa: BLE001
                        status, new = f"error: {type(e).__name__}: {e}"[:300], 0
                        stats["errors"] += 1
                        per["errors"] += 1
                stats["new_docs"] += new
                per["new"] += new
                con.execute("UPDATE pages SET last_crawled=?, last_status=? WHERE id=?",
                            (datetime.now().isoformat(timespec="seconds"), status, page["id"]))
                con.commit()
                log.info("%-5s %-18s %-5s %s -> %s, +%d", src["country"], src["agency"][:18], page["lang"],
                         page["url"][:80], status, new)
        progress.tick("Checking report pages", stats["pages"], total)
        stats["sources"] = {k: v for k, v in stats["sources"].items() if v["new"] or v["errors"]}   # keep the run short
        con.execute("INSERT INTO runs(kind,started_at,finished_at,summary) VALUES('crawl',?,?,?)",
                    (started, datetime.now().isoformat(timespec="seconds"), json.dumps(stats, ensure_ascii=False)))
    return stats
