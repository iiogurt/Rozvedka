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
from collections import Counter

from . import db, topics
from .config import FILES

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
           r"listopadu|prosince)[a-z]*")
_DATES = [re.compile(r"\b\d{1,2}\.?\s*" + _MONTHS + r"\.?\s+(?:de\s+)?" + YEAR + r"(?!\d)"),
          re.compile(r"\b" + _MONTHS + r"\.?\s+(?:\d{1,2},?\s+)?(?:de\s+)?" + YEAR + r"(?!\d)"),
          re.compile(r"\b\d{1,2}\s?[./]\s?\d{1,2}\s?[./]\s?" + YEAR + r"(?!\d)"),
          re.compile(r"(?:©|\(c\)|copyright)\s*" + YEAR + r"(?!\d)")]


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


def from_text(body: str, pages: list[int] | None) -> tuple[int, str] | None:
    """The year of a report from its first pages, and the evidence: a report heading first (on the cover page
    before the next two pages), then a publication date."""
    end = pages[2] if pages and len(pages) > 2 else 6000
    head = body[:max(end, 1500)][:12000]
    text = topics.normalize(head)
    cover_end = pages[1] if pages and len(pages) > 1 else 2500
    for kind, patterns in (("heading", _HEADING), ("date", _DATES)):
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


def estimate(con, doc_id: int) -> tuple[int, str] | None:
    row = con.execute("""SELECT d.local_path, t.body, i.pages FROM documents d LEFT JOIN doc_text t ON t.rowid=d.id
                         LEFT JOIN doc_index i ON i.doc_id=d.id WHERE d.id=?""", (doc_id,)).fetchone()
    if row is None:
        return None
    if row["body"]:
        got = from_text(row["body"], json.loads(row["pages"]) if row["pages"] else None)
        if got:
            return got
    return None      # PDF creation dates are a year off too often (blind check: 47 % exact) – not used for the year


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
            stats["from " + ("PDF metadata" if source.startswith("PDF") else
                             "a publication date" if "publication date" in source else "a report heading")] += 1
    log.info("dated %s", dict(stats))
    return {"undated_before": len(ids), **stats}


def check(sample: int = 400) -> dict:
    """Accuracy on reports whose year is known from the title: estimate blind, compare."""
    with db.session() as con:
        ids = [r[0] for r in con.execute(
            """SELECT d.id FROM documents d JOIN doc_index i ON i.doc_id=d.id WHERE d.year IS NOT NULL
               AND d.year_source IS NULL AND d.hidden=0 AND i.chars > 2000 ORDER BY random() LIMIT ?""", (sample,))]
        known = dict(con.execute(f"SELECT id, year FROM documents WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()) if ids else {}
        res = Counter()
        for doc_id in ids:
            got = estimate(con, doc_id)
            kind = "none" if not got else "pdf" if got[1].startswith("PDF") else "date" if "publication date" in got[1] else "heading"
            res[f"{kind} n"] += 1
            if got:
                diff = got[0] - known[doc_id]
                res[f"{kind} exact"] += diff == 0
                res[f"{kind} ±1"] += abs(diff) <= 1
    return dict(res)
