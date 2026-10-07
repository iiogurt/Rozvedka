"""Reports, not files: the language versions, summaries and file variants of one report are grouped into a *work*,
so that every count is per report. One file represents the work (the one with most text; English unless another
version has 30 % more); the others stay in the library, on the report page and on Documents ("other languages"),
but are not counted again (trends.LISTED).

Rules, in order – files are grouped when any rule links them, always within one agency:
  A. series   – the edition of one year of a confirmed yearly report series (sources/series.yaml), any language;
  B. address  – the same address once language markers are removed (…/en/…, _en.pdf, -de.pdf, ?lang=fr), same year;
  C. title    – the same year and title once a trailing language or "summary" word is removed ("TE-SAT 2025 –
                Zusammenfassung", "VLA 2021 (et)"); a title without a year only for files in one folder, each in
                another language.
Corrections by hand in sources/works.yaml: `separate` lists addresses that are never grouped."""
import logging
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

from . import db, topics
from .config import ROOT

log = logging.getLogger("rozvedka.works")

# SQL: the file that represents its report (a file not grouped with others represents itself)
PRIMARY = "(d.work_id IS NULL OR d.work_id = d.id)"
WORKS_FILE = ROOT / "sources" / "works.yaml"
EN_PREFERENCE = 1.3          # English wins unless another language version has 30 % more text (translations run longer)

LANGS = ("en|de|fr|it|nl|cs|sk|pl|sv|da|nb|no|fi|et|lv|lt|es|pt|ro|bg|hr|sl|hu|el|ru|uk|ja|ko|zh|ga|mt|is|sq|mk|tr|lb|"
         "eng|deu|ger|fra|fre|ita|esp|spa|nld|ces|pol|swe|fin|est|lav|lit|por|ron|rum|bul|hrv|slv|hun|ell|rus")
SUMMARY_WORDS = (
    r"executive summary|summary|zusammenfassung|kurzfassung|resume|synthese|resumen ejecutivo|resumen|sintesi|"
    r"samenvatting|shrnuti|suhrn|streszczenie|sammanfattning|sammendrag|tiivistelma|kokkuvote|kopsavilkums|santrauka|"
    r"rezumat|резюме|обобщение|sazetak|povzetek|osszefoglalo|περιληψη|achoimre feidhmiuchain|achoimre|"
    r"sommarju ezekuttiv|sommarju|resumo|sumario executivo|kratak pregled|english|deutsch|francais|espanol|italiano|"
    r"nederlands|english version|version|versie|fassung|translation|traduction")
_TAIL = re.compile(rf"\s*([-–—:|(,]\s*)?({SUMMARY_WORDS}|\(?[a-z]{{2}}\)?)\s*\)?\s*$")


def address_key(url: str) -> str:
    """The address without its language markers: …/en/x_en.pdf and …/de/x_de.pdf give the same key."""
    p = urlsplit(url or "")
    path = unquote(p.path).lower()
    path = re.sub(rf"/({LANGS})(?=/)", "/", path)                       # /en/ folders
    path = re.sub(rf"[-_.]({LANGS})(?=[-_.]|$)", "", path)               # _en, -de., .fr.
    path = re.sub(r"-[dfie](?=\.pdf$)", "", path)                        # Swiss federal sites: -d.pdf, -f.pdf, -i.pdf, -e.pdf
    query = "&".join(x for x in p.query.split("&") if x and not re.match(r"(lang|language|locale|hl)=", x, re.I))
    return p.netloc.lower().removeprefix("www.") + path + ("?" + query if query else "")


def address_lang(url: str) -> str | None:
    """The language an address names (…/en/…, en_x.pdf, x-en.pdf, x_EN.pdf), if it names exactly one."""
    path = unquote(urlsplit(url or "").path).lower()
    found = set(re.findall(r"(?:^|[/_. -])(en|de|fr|it|nl|cs|sk|pl|sv|da|nb|fi|et|lv|lt|es|pt|ro|bg|hr|sl|hu|el|ru|ja|zh|ga|mt|is|sq|mk|tr|uk)"
                           r"(?=[/_. -]|$)", path.rsplit(".", 1)[0] if "." in path.rsplit("/", 1)[-1] else path))
    return found.pop() if len(found) == 1 else None


def title_key(title: str) -> str:
    """The title without file-size noise and without a trailing language or "summary" word."""
    t = topics.normalize(title or "")
    t = re.sub(r"\(pdf[^)]*\)|\bpdf\b|\d+([.,]\d+)?\s*(kb|mb)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    for _ in range(3):
        shorter = _TAIL.sub("", t).strip()
        if shorter == t:
            break
        t = shorter
    return t


def _folder(url: str) -> str:
    p = urlsplit(url or "")
    return p.netloc.lower() + unquote(p.path).rsplit("/", 1)[0]


def load_separate(path: Path | None = None) -> set[str]:
    path = path or WORKS_FILE
    if not path.exists():
        return set()
    return set((yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("separate") or [])


def group() -> dict:
    """Recompute every work: documents.work_id (the representing file) and work_why (the rule that linked them)."""
    from . import series          # series → actors → trends → works: imported here, not at module load
    separate = load_separate()
    editions = series.doc_index()
    per_year = {e["id"]: (series.get(e["id"]) or {}).get("per_year", 1) for e in editions.values()}
    with db.session() as con:
        docs = [dict(r) for r in con.execute(
            """SELECT d.id, d.source_id, d.url, d.title, d.lang, d.year, COALESCE(i.chars, 0) chars FROM documents d
               LEFT JOIN doc_index i ON i.doc_id=d.id
               WHERE d.hidden=0 AND d.status NOT IN ('missing','duplicate','skipped')""")]
        by_id = {d["id"]: d for d in docs}
        parent = {d["id"]: d["id"] for d in docs}
        why: dict[int, set] = defaultdict(set)

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def link(members, rule):
            members = [m for m in members if by_id[m]["url"] not in separate]
            if len(members) < 2:
                return
            for m in members:
                why[m].add(rule)
            for m in members[1:]:
                parent[find(m)] = find(members[0])

        buckets: dict[tuple, list] = defaultdict(list)
        for d in docs:                                                    # A. series edition of a year
            e = editions.get(d["id"])
            if e and per_year.get(e["id"], 1) == 1:
                buckets[("A", e["id"], e["year"])].append(d["id"])
        for d in docs:                                                    # B. address without language markers
            buckets[("B", d["source_id"], d["year"], address_key(d["url"]))].append(d["id"])
        for d in docs:                                                    # C. title without a language / summary tail
            k = title_key(d["title"])
            if d["year"] and len(k) >= 8:
                buckets[("C", d["source_id"], d["year"], k)].append(d["id"])
        labels = {"A": "an edition of the same report series and year", "B": "the same address in another language",
                  "C": "the same title in another language or as a summary"}
        for key, members in buckets.items():
            if len(members) < 2:
                continue
            if key[0] == "C" and not re.search(r"(19|20)\d{2}", key[3]):
                # a title without a year can be shared by different documents (one generic link text for a whole
                # folder): only files in one folder, each in another language, are taken as versions of one report
                by_folder = defaultdict(list)
                for m in members:
                    by_folder[_folder(by_id[m]["url"])].append(m)
                for ms in by_folder.values():
                    if len({by_id[m]["lang"] for m in ms}) == len(ms):
                        link(ms, labels["C"])
            else:
                link(members, labels[key[0]])

        works: dict[int, list] = defaultdict(list)
        for d in docs:
            works[find(d["id"])].append(d)
        rows, grouped = [], 0
        for members in works.values():
            if len(members) == 1:
                rows.append((None, None, members[0]["id"]))
                continue
            grouped += 1
            def weight(d):     # the address knows the language better than the stored tag when it names one
                lang = address_lang(d["url"]) or d["lang"]
                return d["chars"] * (EN_PREFERENCE if lang == "en" else 1), -d["id"]
            rep = max(members, key=weight)
            for d in members:
                rows.append((rep["id"], "; ".join(sorted(why[d["id"]])) or "grouped with the others", d["id"]))
        con.execute("UPDATE documents SET work_id=NULL, work_why=NULL")
        con.executemany("UPDATE documents SET work_id=?, work_why=? WHERE id=?", rows)
    variants = sum(1 for r in rows if r[0] is not None and r[0] != r[2])
    out = {"works_with_several_files": grouped, "files_not_counted_again": variants}
    log.info("works %s", out)
    return out


def members(con, doc_id: int) -> list[dict]:
    """Every file of the report a file belongs to (itself included), the representing file first."""
    r = con.execute("SELECT work_id FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not r or r["work_id"] is None:
        return []
    return [dict(x) for x in con.execute(
        """SELECT d.id, d.title, d.lang, d.url, d.local_path, d.work_why, d.pages_count FROM documents d
           WHERE d.work_id=? ORDER BY d.id != d.work_id, d.lang, d.id""", (r["work_id"],))]
