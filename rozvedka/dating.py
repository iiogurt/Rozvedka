"""Dates for undated reports, each with the evidence it came from.

The year of a report is normally taken from its title or address when it is found (crawler.guess_year). For the
reports where that gives nothing, this module looks, in order, at
  1. a report heading on the first pages – "Annual Report 2023", "Jahresbericht 2022", "Výroční zpráva … za rok
     2021", "Informe Anual 2020", "2023年版": the year the report covers;
  2. a publication date on the first pages – "March 2024", "15. 3. 2024", "© 2024";
(The creation date in the PDF's metadata was tested and is not used: it is the publication date, a year after the
covered year about half of the time.) The chosen year is stored with `documents.year_source` (e.g. 'text: “Annual Report 2023” (p. 1)'); years set by hand
are marked 'set by hand' and never changed. Nothing is overwritten: only reports without a year are dated.
"""
import datetime as dt
import json
import logging
import re
import unicodedata
from collections import Counter
from pathlib import Path

import yaml

from . import db, topics
from .config import FILES, ROOT

log = logging.getLogger("rozvedka.dating")

YEAR = r"((?:19|20)\d{2})"
# words naming a periodic report or the period it covers, in the languages of the library (folded, lowercase)
REPORT_WORDS = (r"(annual|yearly|activity|public|national|security|threat|situation|status|risk|cyber|intelligence)?\s*"
                r"(report|review|overview|assessment|yearbook|outlook|landscape|panorama|white paper|bilan|annuaire|"
                r"bericht|jahresbericht|lagebild|lagebericht|weissbuch|verfassungsschutzbericht|zprava|vyrocni zprava|"
                r"sprava|rapport|rapport annuel|rapport d.activite|informe|informe anual|memoria|relazione|relatorio|"
                r"verslag|jaarverslag|raport|raport roczny|sprawozdanie|aastaraamat|aastaulevaade|ulevaade|vuosikertomus|"
                r"katsaus|arsrapport|arsredovisning|lagesbild|arsberetning|arbok|izvjesce|porocilo|evkonyv|prehled|"
                r"overzicht|tilannekuva|libro blanco|livre blanc)")
PERIOD_WORDS = (r"(za rok|v roce|for the year|for the period|fiscal year|financial year|in the year|im jahr|fur das jahr|"
                r"jahr|annee|ano|anno|roku|w roku|aastal|vuonna|ar|year|rok|el ano|del ano|de l.annee)")
_HEADING = [re.compile(REPORT_WORDS + r"\W{0,6}(?:\w+\W+){0,6}?" + PERIOD_WORDS + r"?\W{0,4}" + YEAR + r"(?!\d)"),
            re.compile(YEAR + r"(?:\s*[-/]\s*\d{2,4})?\W{0,4}" + REPORT_WORDS),
            re.compile(PERIOD_WORDS + r"\W{1,4}" + YEAR + r"(?!\d)"),
            re.compile(YEAR + r"\s*年")]                       # Japanese/Chinese: 2023年版, 2023年度
_MONTHS = (r"(jan|feb|mar|apr|ma[iy]|jun|jul|aug|sep|o[ck]t|nov|de[cz]|janvier|fevrier|mars|avril|juin|juillet|aout|"
           r"septembre|octobre|novembre|decembre|enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|"
           r"noviembre|diciembre|gennaio|febbraio|aprile|maggio|giugno|luglio|settembre|ottobre|dicembre|januari|"
           r"februari|maart|mei|juni|juli|augustus|oktober|stycznia|lutego|marca|kwietnia|maja|czerwca|lipca|sierpnia|"
           r"wrzesnia|pazdziernika|listopada|grudnia|ledna|unora|brezna|dubna|kvetna|cervna|cervence|srpna|zari|rijna|"
           r"listopadu|prosince|"
           # Nordic, Baltic, Finnish, Hungarian, Croatian/Slovene, Romanian, Portuguese, Greek, Bulgarian, Irish, Maltese
           r"januar|februar|marts|marz|maj|august|oktober|desember|tammikuu|helmikuu|maaliskuu|huhtikuu|toukokuu|kesakuu|"
           r"heinakuu|elokuu|syyskuu|lokakuu|marraskuu|joulukuu|jaanuar|veebruar|marts|aprill|juuni|juuli|septembr|"
           r"novembr|detsembr|janvar|februar|marts|aprilis|maijs|junijs|julijs|augusts|septembris|oktobris|novembris|"
           r"decembris|sausio|vasario|kovo|balandzio|geguzes|birzelio|liepos|rugpjucio|rugsejo|spalio|lapkricio|"
           r"gruodzio|januar|februar|marcius|aprilis|majus|junius|julius|augusztus|szeptember|oktober|november|"
           r"december|sijecnja|veljace|ozujka|travnja|svibnja|lipnja|srpnja|kolovoza|rujna|listopada|studenoga|"
           r"prosinca|januarja|februarja|marca|aprila|maja|junija|julija|avgusta|septembra|oktobra|novembra|"
           r"decembra|ianuarie|februarie|martie|aprilie|iunie|iulie|septembrie|octombrie|noiembrie|decembrie|"
           r"janeiro|fevereiro|marco|maio|junho|julho|setembro|outubro|novembro|dezembro|"
           r"ιανουαρ|φεβρουαρ|μαρτ|απριλ|μαι|ιουν|ιουλ|αυγουστ|σεπτεμβρ|οκτωβρ|νοεμβρ|δεκεμβρ|"
           r"януари|февруари|март|април|май|юни|юли|август|септември|октомври|ноември|декември|"
           r"eanair|feabhra|marta|aibrean|bealtaine|meitheamh|iuil|lunasa|mean fomhair|deireadh fomhair|samhain|nollaig|"
           r"jannar|frar|marzu|april|mejju|gunju|lulju|awwissu|settembru|ottubru|novembru|dicembru)[a-zα-ωа-я]*")
_DATES = [re.compile(r"\b\d{1,2}\.?\s*" + _MONTHS + r"\.?\s+(?:de\s+)?" + YEAR + r"(?!\d)"),
          re.compile(r"\b" + _MONTHS + r"\.?\s+(?:\d{1,2},?\s+)?(?:de\s+)?" + YEAR + r"(?!\d)"),
          re.compile(r"\b\d{1,2}\s?[./]\s?\d{1,2}\s?[./]\s?" + YEAR + r"(?!\d)"),
          re.compile(r"(?:©|\(c\)|copyright)\s*" + YEAR + r"(?!\d)"),
          # year first: "2024. gada 18. julija" (lv), "2024 m. liepos 18 d." (lt), "2024. julius 18." (hu)
          re.compile(r"(?<!\d)" + YEAR + r"\.?\s*(?:m\.|gada|г\.)?\s*(?:\d{1,2}\.\s*" + _MONTHS + r"|" + _MONTHS + r"\s+\d{1,2}\.?(?!\d))"),
          # imprint and series numbers: "Utgitt av DSB 2025", "Published by … 2019", "Traficomin julkaisuja 11/2025"
          re.compile(r"(?:utgitt|utgjeven|udgivet|utgiven|published|herausgegeben|edited|vydal|vydano|wydano|julkaisija|"
                     r"kiadta|publie|publicado|pubblicato|uitgegeven)\b[^\n]{0,80}?(?<!\d)" + YEAR + r"(?!\d)"),
          re.compile(r"julkaisuja\s+\d{1,3}\s*/\s*" + YEAR + r"(?!\d)")]   # not "No. 153/1994": that cites a law


# Japanese era years: 令和3年版 = 2021, 平成29年版 = 2017 (Reiwa from 2019, Heisei 1989–2019, Showa 1926–1989)
_ERA = re.compile(r"(令和|平成|昭和)\s*(\d{1,2}|元)\s*年")
_ERA_START = {"令和": 2018, "平成": 1988, "昭和": 1925}
# a date stamp in a file name: 20260611_report.pdf, strategy_v20241008.pdf
_STAMP = re.compile(r"(?<!\d)((?:19|20)\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)")


def era_year(m) -> int:
    return _ERA_START[m.group(1)] + (1 if m.group(2) == "元" else int(m.group(2)))


_MONTH_BEFORE = re.compile(_MONTHS + r"\.?\s+(?:\d{1,2},?\s+)?(?:de\s+)?(?:19|20)\d{2}\W*$")


def _ok(y: int) -> bool:
    return 1990 <= y <= dt.date.today().year


def _year_of(m) -> int | None:
    """The covered year of a match: the end of a range ("2021-2022 report" → 2022), else the year."""
    years = [g for g in m.groups() if g and re.fullmatch(r"(19|20)\d{2}", g)]
    rng = re.search(r"((?:19|20)\d{2})\s*[-/–]\s*((?:19|20)?\d{2})(?!\d)", m.group(0))
    if rng:
        end = rng.group(2)
        return int(end if len(end) == 4 else rng.group(1)[:2] + end)
    return int(years[-1]) if years else None


def from_text(body: str, pages: list[int] | None, kinds=("heading", "date"), cover: bool = True) -> tuple[int, str] | None:
    """The year of a report from its first pages, and the evidence: a report heading first (on the cover page
    before the next two pages), then a publication date."""
    end = pages[2] if pages and len(pages) > 2 else 6000
    head = body[:max(end, 1500)][:12000]
    text = topics.normalize(head)
    cover_end = pages[1] if pages and len(pages) > 1 else 2500
    for kind, patterns in (("heading", _HEADING), ("date", _DATES)):
        if kind not in kinds:
            continue
        found = []
        for rx in patterns:
            for m in rx.finditer(text):
                if kind == "heading":
                    ym = re.search(r"(19|20)\d{2}", m.group(0))
                    at = m.start() + (ym.start() if ym else 0)
                    if _MONTH_BEFORE.search(text[max(0, at - 25):at + 4]):
                        continue       # "published in December 2013", "12 February 2022 …" are dates, not the covered year
                y = _year_of(m)
                if y and _ok(y):
                    found.append((y, m.start(), m.end()))
        if kind == "heading":
            found += [(era_year(m), m.start(), m.end()) for m in _ERA.finditer(text) if _ok(era_year(m))]
        if not found:
            continue
        cover = [f for f in found if f[1] < cover_end] if kind == "heading" else []
        pool = cover or found
        counts = Counter(y for y, _, _ in pool)
        year = max(counts, key=lambda y: (counts[y], y))
        _, s, e = next(f for f in pool if f[0] == year)
        page = sum(1 for p in (pages or []) if p <= s) if pages else None
        quote = " ".join(head[s:e].split())[:80]   # normalize() keeps offsets for the alphabetic scripts used
        return year, f"text: “{quote}”" + (f" (p. {max(page, 1)})" if page else "") + \
            (f", {counts[year]}×" if counts[year] > 1 else "") + ("" if kind == "heading" else " – publication date")
    if cover and "date" in kinds and COVER_RULE and pages and len(pages) > 1 and pages[1] <= COVER_MAX:      # a title page, not a page of prose
        years = [(int(m.group(0)), m.start(), m.end()) for m in re.finditer(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text[:cover_end])]
        years = [y for y in years if _ok(y[0])]
        if years and len({y for y, _, _ in years}) == 1:
            y, s, e = years[0]
            return y, f"text: “{' '.join(head[max(0, s - 30):e + 10].split())}” – the only year on the cover"
    return None


COVER_RULE = True
COVER_MAX = 800      # characters: a cover is a title page; on a page of prose a lone year is often a reference


def from_address(title: str, url: str) -> tuple[int, str] | None:
    """A year the crawler's title/URL rule misses: a Japanese era year in the title, a year in a file name passed
    as a query parameter (…?file=…Spring-2026.pdf), or a date stamp in the file name (20260611_….pdf)."""
    from urllib.parse import parse_qsl, unquote, urlsplit
    m = _ERA.search(unicodedata.normalize("NFKC", title or ""))
    if m and _ok(era_year(m)):
        return era_year(m), f"title: “{m.group(0)}” (Japanese era year)"
    parts = urlsplit(url or "")
    for _, v in parse_qsl(parts.query):
        name = unquote(v).split("?", 1)[0].rsplit("/", 1)[-1]
        if re.search(r"\.(pdf|docx?|epub)$", name, re.I):
            ys = [int(y) for y in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", name) if _ok(int(y))]
            if ys:
                return ys[0], f"address: file name “{name[:80]}”"
    name = unquote(parts.path).rsplit("/", 1)[-1]
    m = _STAMP.search(name)
    if m and _ok(int(m.group(1))):
        return int(m.group(1)), f"address: date stamp “{m.group(0)}” in “{name[:80]}” – publication date"
    return None


def from_pdf(path) -> tuple[int, str] | None:
    """Creation year from the PDF metadata – kept for the accuracy check only (see the module docstring)."""
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        from pypdf import PdfReader
        meta = PdfReader(str(path)).metadata
        created = meta.creation_date if meta else None
    except Exception:  # noqa: BLE001 - metadata is best effort
        return None
    if created and _ok(created.year):
        return created.year, f"PDF metadata: created {created.date().isoformat()}"
    return None


FOLDER_MIN = 3     # dated reports in the same folder, all from one year (leave-one-out check: 98 % exact)


def folder_of(url: str) -> str:
    """Site and folder of a report's address (for viewer links such as …/pdfjs/?file=/x/y.pdf: the file's folder)."""
    from urllib.parse import parse_qsl, unquote, urlsplit
    parts = urlsplit(url or "")
    path = next((unquote(v) for k, v in parse_qsl(parts.query) if k == "file" and "/" in v), unquote(parts.path))
    return parts.netloc + path.rsplit("/", 1)[0] + "/"


def from_folder(con, doc_id: int, url: str, cover_text: str = "") -> tuple[int, str] | None:
    """The year shared by all other dated reports in the same folder of the site (at least FOLDER_MIN of them).
    Years that themselves came from this rule do not count, so it cannot feed on itself; a report whose first page
    names another year is left alone (shared upload folders hold files of many years)."""
    folder = folder_of(url)
    netloc = folder.split("/", 1)[0]
    years = [r[1] for r in con.execute(
        """SELECT url, year FROM documents WHERE id != ? AND year IS NOT NULL AND hidden=0
           AND status NOT IN ('missing','duplicate','skipped') AND (year_source IS NULL OR year_source NOT LIKE 'folder:%')
           AND url LIKE ?""", (doc_id, f"%{netloc}%")) if folder_of(r[0]) == folder]
    own = {int(y) for y in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", cover_text) if _ok(int(y))}
    if len(years) >= FOLDER_MIN and len(set(years)) == 1 and own <= {years[0]}:
        return years[0], f"folder: all {len(years)} dated reports in {folder} are from {years[0]}"
    return None


def estimate(con, doc_id: int) -> tuple[int, str] | None:
    row = con.execute("""SELECT d.local_path, d.title, d.url, t.body, i.pages FROM documents d LEFT JOIN doc_text t ON t.rowid=d.id
                         LEFT JOIN doc_index i ON i.doc_id=d.id WHERE d.id=?""", (doc_id,)).fetchone()
    if row is None:
        return None
    got = from_address(row["title"], row["url"])
    if got:
        return got
    pages = json.loads(row["pages"]) if row["pages"] else None
    heading = from_text(row["body"], pages, kinds=("heading",)) if row["body"] else None
    first = (row["body"] or "")[:pages[1] if pages and len(pages) > 1 else 1500]
    return (heading or from_folder(con, doc_id, row["url"], first)
            or (from_text(row["body"], pages, kinds=("date",), cover=True) if row["body"] else None))      # PDF creation dates are a year off too often (blind check: 47 % exact) – not used for the year


def date_documents(limit: int | None = None) -> dict:
    """Give every undated report a year where the evidence allows (never overwrites a year)."""
    stats = Counter()
    with db.session() as con:
        ids = [r[0] for r in con.execute(
            """SELECT id FROM documents WHERE year IS NULL AND hidden=0 AND status NOT IN ('missing','duplicate','skipped')
               ORDER BY id""" + (f" LIMIT {int(limit)}" if limit else ""))]
        for doc_id in ids:
            got = estimate(con, doc_id)
            if not got:
                stats["no evidence"] += 1
                continue
            year, source = got
            con.execute("UPDATE documents SET year=?, year_source=? WHERE id=? AND year IS NULL", (year, source, doc_id))
            stats["from " + LABELS[kind_of(source)]] += 1
    log.info("dated %s", dict(stats))
    stats["year conflicts"] = find_conflicts()
    return {"undated_before": len(ids), **stats}


LABELS = {"heading": "a report heading", "date": "a publication date", "address": "the title or address",
          "folder": "reports in the same folder", "cover": "the only year on the cover"}


def kind_of(source: str) -> str:
    """The rule behind a year's evidence text."""
    return ("address" if source.startswith(("address", "title")) else "folder" if source.startswith("folder")
            else "cover" if "only year on the cover" in source
            else "date" if "publication date" in source else "heading")


def check(sample: int = 100_000) -> dict:
    """Accuracy on reports whose year is known from the title: estimate blind, compare."""
    with db.session() as con:
        ids = [r[0] for r in con.execute(
            """SELECT d.id FROM documents d JOIN doc_index i ON i.doc_id=d.id WHERE d.year IS NOT NULL
               AND d.year_source IS NULL AND d.hidden=0 AND i.chars > 2000 ORDER BY random() LIMIT ?""", (sample,))]
        known = dict(con.execute(f"SELECT id, year FROM documents WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()) if ids else {}
        res = Counter()
        for doc_id in ids:
            got = estimate(con, doc_id)
            kind = "none" if not got else kind_of(got[1])
            res[f"{kind} n"] += 1
            if got:
                diff = got[0] - known[doc_id]
                res[f"{kind} exact"] += diff == 0
                res[f"{kind} ±1"] += abs(diff) <= 1
    return dict(res)


# ── year conflicts: a stored year that strong evidence contradicts, listed for review – never changed silently ──
CONFLICT_SCHEMA = """
CREATE TABLE IF NOT EXISTS year_conflicts (       -- found by find_conflicts(); rebuilt whenever reports are dated
    doc_id INTEGER PRIMARY KEY, stored INTEGER, found INTEGER, kind TEXT, evidence TEXT, checked_at TEXT);
"""
CONFLICT_KINDS = {"era": "Japanese era year in the title", "stamp": "date stamp in the file name",
                  "heading": "report heading on the cover"}
YEAR_REVIEWS = ROOT / "sources" / "year_reviews.yaml"
REVIEWS_HEADER = """# Year reviews – conflicts between a report's stored year and strong evidence, decided in the portal
# (Documents → Year conflicts). Each entry: the report (official URL), the stored year, the year found and its evidence,
# and the verdict: "use" sets the report's year to the year found (re-applied on every rebuild, so it holds after an
# import), "keep" keeps the stored year and stops listing that conflict. Written by the portal; editable by hand.
"""


def init_conflicts(con) -> None:
    con.executescript(CONFLICT_SCHEMA)


def load_reviews(path: Path | None = None) -> list[dict]:
    path = path or YEAR_REVIEWS
    if not path.exists():
        return []
    return [r for r in (yaml.safe_load(path.read_text(encoding="utf-8")) or []) if isinstance(r, dict)]


def save_reviews(rows: list[dict], path: Path | None = None) -> None:
    path = path or YEAR_REVIEWS
    path.write_text(REVIEWS_HEADER + yaml.safe_dump(rows, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")


def against(title: str, url: str, year: int, body: str | None, pages: list[int] | None) -> tuple[int, str, str] | None:
    """(year found, kind, evidence) when strong evidence contradicts the stored year, else None. Strong means:
    a Japanese era year in the title; a date stamp in the file name that is neither the stored year nor the year
    after it (reports are published the year after the one they cover); a report heading on the cover page naming
    another year, unless the title itself carries the stored year."""
    got = from_address(title, url)
    if got and "Japanese era" in got[1] and got[0] != year:
        return got[0], "era", got[1]
    if got and "date stamp" in got[1] and got[0] not in (year, year + 1):
        return got[0], "stamp", got[1]
    if body and str(year) not in (title or ""):
        h = from_text(body, pages, kinds=("heading",))
        if h and h[0] != year and "(p. 1)" in h[1]:
            return h[0], "heading", h[1]
    return None


def find_conflicts() -> int:
    """Re-apply the "use" verdicts of year_reviews.yaml, then rebuild the list of conflicts over every listed report
    with a year not set by hand. Conflicts with a "keep" verdict for the same stored and found year are left out."""
    now = dt.datetime.now().isoformat(" ", "seconds")
    reviews = load_reviews()
    kept = {(r["url"], r.get("stored"), r.get("found")) for r in reviews if r.get("verdict") == "keep"}
    with db.session() as con:
        init_conflicts(con)
        for r in reviews:
            if r.get("verdict") == "use" and r.get("found"):
                con.execute("""UPDATE documents SET year=?, year_source='set by hand' WHERE url=? AND year IS ?
                               AND (year_source IS NULL OR year_source != 'set by hand')""", (r["found"], r["url"], r.get("stored")))
        found = []
        for r in con.execute("""SELECT d.id, d.title, d.url, d.year, t.body, i.pages FROM documents d
                                LEFT JOIN doc_text t ON t.rowid=d.id LEFT JOIN doc_index i ON i.doc_id=d.id
                                WHERE d.year IS NOT NULL AND d.hidden=0 AND d.status NOT IN ('missing','duplicate','skipped')
                                AND (d.year_source IS NULL OR d.year_source != 'set by hand')"""):
            got = against(r["title"], r["url"], r["year"], r["body"], json.loads(r["pages"]) if r["pages"] else None)
            if got and (r["url"], r["year"], got[0]) not in kept:
                found.append((r["id"], r["year"], *got, now))
        con.execute("DELETE FROM year_conflicts")
        con.executemany("INSERT INTO year_conflicts VALUES(?,?,?,?,?,?)", found)
    log.info("year conflicts: %d", len(found))
    return len(found)


# a conflict is open while the report still has the stored year and the year was not set by hand since
OPEN = "c.stored = d.year AND (d.year_source IS NULL OR d.year_source != 'set by hand') AND d.hidden=0"


def conflicts(kind: str = "", source: int | None = None) -> list[dict]:
    with db.session() as con:
        init_conflicts(con)
        sql = f"""SELECT c.*, d.title, d.url, d.lang, d.local_path, d.year_source, d.source_id, s.agency, s.country
                  FROM year_conflicts c JOIN documents d ON d.id=c.doc_id JOIN sources s ON s.id=d.source_id
                  WHERE {OPEN}"""
        args: list = []
        if kind:
            sql += " AND c.kind=?"; args.append(kind)
        if source:
            sql += " AND d.source_id=?"; args.append(source)
        sql += " ORDER BY s.country, s.agency, c.stored, d.title"
        return [dict(r) for r in con.execute(sql, args)]


def conflict_of(doc_id: int) -> dict | None:
    with db.session() as con:
        init_conflicts(con)
        r = con.execute(f"SELECT c.* FROM year_conflicts c JOIN documents d ON d.id=c.doc_id WHERE c.doc_id=? AND {OPEN}",
                        (doc_id,)).fetchone()
        return dict(r) if r else None


def resolve(doc_ids: list[int], use_found: bool) -> int:
    """Use the year found (the report's year is then 'set by hand', as after an edit) or keep the stored year;
    the verdict is written to year_reviews.yaml with its evidence."""
    now = dt.datetime.now().isoformat(" ", "seconds")
    reviews = {r["url"]: r for r in load_reviews()}
    n = 0
    with db.session() as con:
        init_conflicts(con)
        for doc_id in doc_ids:
            c = con.execute(f"""SELECT c.*, d.url FROM year_conflicts c JOIN documents d ON d.id=c.doc_id
                                WHERE c.doc_id=? AND {OPEN}""", (doc_id,)).fetchone()
            if not c:
                continue
            reviews[c["url"]] = {"url": c["url"], "stored": c["stored"], "found": c["found"], "evidence": c["evidence"],
                                 "verdict": "use" if use_found else "keep", "checked": now}
            if use_found:
                con.execute("UPDATE documents SET year=?, year_source='set by hand' WHERE id=?", (c["found"], doc_id))
            con.execute("DELETE FROM year_conflicts WHERE doc_id=?", (doc_id,))
            n += 1
    if n:
        save_reviews(list(reviews.values()))
    return n
