"""A local library of books (roadmap H2, docs/BOOKS.md): PDFs and EPUBs from data/books/, read into the library as
documents of their own kind – searched, matched to actors and topics with their passages and pages like the reports,
but never counted as reports and never exported.

    python -m rozvedka import-books [FOLDER] [--no-index]

Each book's file is copied to data/files/books/<sha256>.<ext> (the original stays where it is). Its metadata – title,
authors, publisher, year, language, ISBN – comes from, in this order of precedence:
  1. data/books/books.yaml, written by hand (`- {file: …, title: …, authors: [...], publisher: …, year: …, isbn: …}`);
  2. Open Library, looked up by ISBN (catalogue data, CC0 – https://openlibrary.org/developers/api), which also gives
     the authors' Wikidata items where it knows them;
  3. the EPUB's own metadata (OPF) or the PDF's document information;
the ISBN from the EPUB metadata or the copyright page (the first pages of the PDF; the check digit is verified). Every
field keeps where it came from. A publishing house is a source of the kind "book" (registry.sync leaves these alone);
a book is a document of type "book", which no report count includes – Documents shows books with that type chosen.
Book text stays on this machine: `export` leaves book files and text out."""
import datetime as dt
import hashlib
import json
import logging
import re
import shutil
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

from . import db
from .config import DATA, FILES

log = logging.getLogger("rozvedka.books")

BOOKS = DATA / "books"                  # the owner's folder: PDFs, EPUBs and books.yaml
STORE = FILES / "books"                 # the copies the library indexes
CACHE = DATA / "books-meta"             # Open Library answers, so a re-import asks again only for new ISBNs
HAND = "books.yaml"
UA = "Rozvedka/0.x (personal research library; https://github.com/iiogurt/Rozvedka)"
OPEN_LIBRARY = "https://openlibrary.org"
MAX_PAGES = 2_000                       # a book is read whole (reports stop at topics.MAX_PAGES)
MAX_CHARS = 4_000_000
SUFFIXES = {".pdf", ".epub"}
LANGS = {"eng": "en", "ger": "de", "fre": "fr", "spa": "es", "ita": "it", "rus": "ru", "ukr": "uk", "pol": "pl",
         "cze": "cs", "dut": "nl", "swe": "sv", "nor": "no", "dan": "da", "fin": "fi", "por": "pt", "est": "et",
         "lav": "lv", "lit": "lt", "hun": "hu", "rum": "ro", "bul": "bg", "hrv": "hr", "slv": "sl", "slo": "sk",
         "gre": "el", "tur": "tr", "jpn": "ja", "chi": "zh", "ara": "ar", "heb": "he"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    doc_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    file TEXT NOT NULL,                  -- the original, relative to data/books/
    format TEXT, isbn TEXT, title TEXT, authors TEXT, publisher TEXT, year INTEGER, lang TEXT,
    meta TEXT,                           -- {field: {value, from}} – where every field came from
    added_at TEXT, updated_at TEXT);
"""


def init() -> None:
    with db.session() as con:
        con.executescript(SCHEMA)


# ── ISBN ──
def _isbn10_ok(s: str) -> bool:
    if not re.fullmatch(r"\d{9}[\dX]", s):
        return False
    return sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(s)) % 11 == 0


def _isbn13_ok(s: str) -> bool:
    if not re.fullmatch(r"97[89]\d{10}", s):
        return False
    return sum((1 if i % 2 == 0 else 3) * int(c) for i, c in enumerate(s)) % 10 == 0


def to_isbn13(s: str) -> str | None:
    """Any written ISBN ('978-0-14-303943-3', '0-14-303943-3') → its 13 digits, or None when the check digit fails."""
    d = re.sub(r"[^\dXx]", "", s or "").upper()
    if len(d) == 13 and _isbn13_ok(d):
        return d
    if len(d) == 10 and _isbn10_ok(d):
        core = "978" + d[:9]
        check = (10 - sum((1 if i % 2 == 0 else 3) * int(c) for i, c in enumerate(core)) % 10) % 10
        return core + str(check)
    return None


ISBN_RE = re.compile(r"ISBN(?:-1[03])?[:\s]*((?:97[89][\s-]?)?\d[\d\s-]{8,15}[\dXx])", re.I)


def isbns_in(text: str) -> list[str]:
    """The valid ISBNs a text names after the word ISBN, in order (a copyright page lists the print, e-book and paperback ones)."""
    out = []
    for m in ISBN_RE.finditer(text or ""):
        i = to_isbn13(m.group(1))
        if i and i not in out:
            out.append(i)
    return out


# ── reading the files ──
def _xml(z: zipfile.ZipFile, name: str) -> ET.Element:
    return ET.fromstring(z.read(name))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def epub_read(path: Path) -> dict:
    """An EPUB's metadata (OPF: title, creators, publisher, date, language, identifiers) and its text section by section
    in reading order (the spine) – a section stands in for a page: EPUBs have none."""
    from bs4 import BeautifulSoup
    with zipfile.ZipFile(path) as z:
        container = _xml(z, "META-INF/container.xml")
        opf_path = next(e.get("full-path") for e in container.iter() if _local(e.tag) == "rootfile")
        base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
        opf = _xml(z, opf_path)
        meta: dict = {"creators": [], "identifiers": []}
        for e in opf.iter():
            tag, text = _local(e.tag), (e.text or "").strip()
            if not text:
                continue
            if tag == "title" and "title" not in meta:
                meta["title"] = text
            elif tag == "creator":
                meta["creators"].append(text)
            elif tag in ("publisher", "language") and tag not in meta:
                meta[tag] = text
            elif tag == "date" and "date" not in meta:
                meta["date"] = text
            elif tag == "identifier":
                meta["identifiers"].append(text)
        manifest = {e.get("id"): e.get("href") for e in opf.iter() if _local(e.tag) == "item"}
        spine = [e.get("idref") for e in opf.iter() if _local(e.tag) == "itemref"]
        sections = []
        for idref in spine:
            href = manifest.get(idref)
            if not href:
                continue
            try:
                html = z.read(base + href.split("#")[0])
            except KeyError:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for t in soup(["script", "style"]):
                t.decompose()
            head = soup.find(["h1", "h2", "h3", "title"])
            text = soup.get_text("\n")
            if text.strip():
                sections.append({"href": href, "heading": head.get_text(" ", strip=True) if head else None, "text": text})
    meta["isbn"] = next((i for x in meta["identifiers"] for i in [to_isbn13(x)] if i), None)
    return {"meta": meta, "sections": sections}


def epub_pages(path: Path, max_chars: int = MAX_CHARS) -> tuple[str, list[int]]:
    """Text of an EPUB plus the offset where each section starts – the shape topics.extract_pages gives for a PDF."""
    from .topics import _clean
    text, offsets = "", []
    for s in epub_read(path)["sections"]:
        if len(text) >= max_chars:
            break
        offsets.append(len(text))
        text += _clean(s["text"]) + "\n"
    return text[:max_chars], offsets


def pdf_read(path: Path, first: int = 12) -> dict:
    """A PDF's document information (title, author, subject, creation year) and the text of its first pages and its
    last two (where the copyright page and the ISBN are)."""
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001
            return {"meta": {}, "encrypted": True, "pages": 0, "front": ""}
    info = reader.metadata or {}
    n = len(reader.pages)
    front = ""
    try:
        out = subprocess.run(["pdftotext", "-q", "-enc", "UTF-8", "-l", str(first), str(path), "-"], capture_output=True, timeout=120)
        front = out.stdout.decode("utf-8", "replace")
        if n > first:
            out = subprocess.run(["pdftotext", "-q", "-enc", "UTF-8", "-f", str(max(first + 1, n - 1)), str(path), "-"],
                                 capture_output=True, timeout=120)
            front += "\n" + out.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):
        front = "\n".join((p.extract_text() or "") for p in reader.pages[:first])
    meta = {"title": (info.get("/Title") or "").strip() or None, "creators": [a.strip() for a in re.split(r"[;&]| and ", info.get("/Author") or "") if a.strip()],
            "date": (info.get("/CreationDate") or "")[2:6] or None, "isbn": None}
    found = isbns_in(front)
    meta["isbn"] = found[0] if found else None
    meta["isbns"] = found
    return {"meta": meta, "encrypted": False, "pages": n, "front": front}


# ── Open Library ──
def _get_json(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
        time.sleep(1)
        return data
    except Exception as e:  # noqa: BLE001 - a missing record or a timeout leaves the book with what its file says
        log.info("open library %s: %s", url, e)
        return None


def open_library(isbn: str) -> dict | None:
    """{title, authors: [{name, ol, wikidata}], publisher, year, lang, url} of an ISBN's edition, cached in data/books-meta/."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{isbn}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8")) or None
    ed = _get_json(f"{OPEN_LIBRARY}/isbn/{isbn}.json")
    out = None
    if ed:
        authors = []
        keys = [a["key"] for a in ed.get("authors") or []]
        if not keys and ed.get("works"):
            work = _get_json(f"{OPEN_LIBRARY}{ed['works'][0]['key']}.json") or {}
            keys = [a["author"]["key"] for a in work.get("authors") or [] if a.get("author")]
        for k in keys[:8]:
            a = _get_json(f"{OPEN_LIBRARY}{k}.json") or {}
            authors.append({"name": a.get("name") or k, "ol": f"{OPEN_LIBRARY}{k}",
                            "wikidata": (a.get("remote_ids") or {}).get("wikidata")})
        year = re.search(r"(1[5-9]|20)\d\d", ed.get("publish_date") or "")
        lang = ((ed.get("languages") or [{}])[0].get("key") or "").rsplit("/", 1)[-1]
        out = {"title": ": ".join(x for x in (ed.get("title"), ed.get("subtitle")) if x), "authors": authors,
               "publisher": (ed.get("publishers") or [None])[0], "year": int(year.group(0)) if year else None,
               "lang": LANGS.get(lang), "url": f"{OPEN_LIBRARY}{ed.get('key', '')}"}
    cached.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


# ── putting it together ──
def hand_entries(folder: Path) -> dict[str, dict]:
    p = folder / HAND
    rows = (yaml.safe_load(p.read_text(encoding="utf-8")) or []) if p.exists() else []
    return {r["file"]: r for r in rows if isinstance(r, dict) and r.get("file")}


def merge(hand: dict, ol: dict | None, own: dict) -> dict:
    """{field: {value, from}} – books.yaml first, then Open Library, then the file's own metadata."""
    year = lambda v: int(m.group(0)) if (m := re.search(r"(1[5-9]|20)\d\d", str(v or ""))) else None
    own_authors = [{"name": n} for n in own.get("creators") or []]
    candidates = {
        "title": [(hand.get("title"), "books.yaml"), ((ol or {}).get("title"), "Open Library"), (own.get("title"), "the file")],
        "authors": [([{"name": n} for n in hand["authors"]] if hand.get("authors") else None, "books.yaml"),
                    ((ol or {}).get("authors") or None, "Open Library"), (own_authors or None, "the file")],
        "publisher": [(hand.get("publisher"), "books.yaml"), ((ol or {}).get("publisher"), "Open Library"), (own.get("publisher"), "the file")],
        "year": [(year(hand.get("year")), "books.yaml"), ((ol or {}).get("year"), "Open Library"), (year(own.get("date")), "the file")],
        "lang": [(hand.get("language"), "books.yaml"), ((ol or {}).get("lang"), "Open Library"),
                 ((own.get("language") or "")[:2].lower() or None, "the file")],
    }
    out = {k: next(({"value": v, "from": f} for v, f in c if v), {"value": None, "from": None}) for k, c in candidates.items()}
    out["isbn"] = {"value": hand.get("isbn") and to_isbn13(str(hand["isbn"])) or own.get("isbn"),
                   "from": "books.yaml" if hand.get("isbn") else ("the file" if own.get("isbn") else None)}
    if ol:
        out["open_library"] = {"value": ol["url"], "from": "Open Library"}
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _source(con, publisher: str | None) -> int:
    """The source of a publishing house (kind "book"), made on first use."""
    name = publisher or "Unknown publisher"
    key = f"BOOK/{name}"[:200]
    row = con.execute("SELECT id FROM sources WHERE key=?", (key,)).fetchone()
    if row:
        return row["id"]
    con.execute("""INSERT INTO sources(key, country, agency, name_en, type, access, publisher, active, notes)
                   VALUES(?, 'OTHER', ?, ?, 'book', 'manual', 'book', 1, 'publisher of books in the local library')""",
                (key, name, name))
    return con.execute("SELECT id FROM sources WHERE key=?", (key,)).fetchone()["id"]


def import_books(folder: Path | None = None, lookup: bool = True, index: bool = True) -> dict:
    """Read every PDF and EPUB of the folder into the library (new ones added, the metadata of known ones refreshed from
    books.yaml and Open Library); then extract their text and match topics and actors unless index is False."""
    folder = Path(folder or BOOKS)
    init()
    folder.mkdir(parents=True, exist_ok=True)
    STORE.mkdir(parents=True, exist_ok=True)
    hand = hand_entries(folder)
    now = dt.datetime.now().isoformat(timespec="seconds")
    stats = {"files": 0, "added": 0, "updated": 0, "unreadable": [], "without_isbn": [], "open_library": 0}
    for path in sorted(p for p in folder.rglob("*") if p.suffix.lower() in SUFFIXES and p.is_file()):
        rel = str(path.relative_to(folder))
        stats["files"] += 1
        fmt = path.suffix.lower()[1:]
        try:
            read = epub_read(path) if fmt == "epub" else pdf_read(path)
        except Exception as e:  # noqa: BLE001 - one broken file must not stop the import
            stats["unreadable"].append(f"{rel}: {type(e).__name__}: {e}"[:200])
            continue
        if read.get("encrypted"):
            stats["unreadable"].append(f"{rel}: encrypted (DRM) – cannot be read")
            continue
        h = hand.get(rel, {})
        own = read["meta"]
        isbn = to_isbn13(str(h["isbn"])) if h.get("isbn") else own.get("isbn")
        ol = open_library(isbn) if (isbn and lookup) else None
        stats["open_library"] += 1 if ol else 0
        m = merge(h, ol, own)
        if not m["isbn"]["value"]:
            stats["without_isbn"].append(rel)
        sha = _sha256(path)
        with db.session() as con:
            known = con.execute("SELECT d.id, d.local_path FROM documents d JOIN books b ON b.doc_id=d.id WHERE d.sha256=? OR b.file=?",
                                (sha, rel)).fetchone()
            sid = _source(con, m["publisher"]["value"])
            title = m["title"]["value"] or path.stem.replace("_", " ")
            local = f"books/{sha[:24]}.{fmt}"
            if not (STORE / local.split("/", 1)[1]).exists():
                shutil.copy2(path, STORE / local.split("/", 1)[1])
            fields = (sid, title, m["lang"]["value"] or "en", m["year"]["value"], local, sha, path.stat().st_size,
                      read.get("pages") or len(read.get("sections") or []))
            if known:
                con.execute("""UPDATE documents SET source_id=?, title=?, lang=?, year=?, local_path=?, sha256=?, size=?,
                               pages_count=? WHERE id=?""", (*fields, known["id"]))
                doc_id = known["id"]
                stats["updated"] += 1
            else:
                con.execute("""INSERT INTO documents(source_id, title, lang, year, local_path, sha256, size, pages_count, url,
                               status, doc_type, doc_type_why, discovered_at, downloaded_at)
                               VALUES(?,?,?,?,?,?,?,?,?, 'downloaded', 'book', 'a book of the local library', ?, ?)""",
                            (*fields, f"book:{m['isbn']['value'] or 'no-isbn'}:{sha[:16]}", now, now))   # one per file: a PDF and an EPUB may share an ISBN
                doc_id = con.execute("SELECT id FROM documents WHERE sha256=? AND url LIKE 'book:%'", (sha,)).fetchone()["id"]
                stats["added"] += 1
            con.execute("""INSERT INTO books(doc_id, file, format, isbn, title, authors, publisher, year, lang, meta, added_at, updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(doc_id) DO UPDATE SET file=excluded.file,
                           format=excluded.format, isbn=excluded.isbn, title=excluded.title, authors=excluded.authors,
                           publisher=excluded.publisher, year=excluded.year, lang=excluded.lang, meta=excluded.meta,
                           updated_at=excluded.updated_at""",
                        (doc_id, rel, fmt, m["isbn"]["value"], title, json.dumps(m["authors"]["value"] or [], ensure_ascii=False),
                         m["publisher"]["value"], m["year"]["value"], m["lang"]["value"], json.dumps(m, ensure_ascii=False), now, now))
    if index and (stats["added"] or stats["updated"]):
        from . import actors, topics
        stats["index-topics"] = topics.index()
        if (DATA / "gazetteer").exists():
            stats["index-actors"] = actors.index()
    log.info("books: %s", {k: v if not isinstance(v, list) else len(v) for k, v in stats.items()})
    return stats


# ── reading ──
def listing(offset: int = 0, limit: int = 100, q: str = "") -> tuple[int, list[dict]]:
    """The books, newest import first, with what the library found in them: pages, the actors and topics named most."""
    from . import actors
    init()
    actors.init()
    where, args = "1=1", []
    if q:
        where, args = "(b.title LIKE ? OR b.authors LIKE ? OR b.publisher LIKE ?)", [f"%{q}%"] * 3
    with db.session() as con:
        total = con.execute(f"SELECT COUNT(*) FROM books b WHERE {where}", args).fetchone()[0]
        rows = [dict(r) for r in con.execute(
            f"""SELECT b.*, d.pages_count, d.source_id, d.id AS id, i.taxonomy_hash IS NOT NULL AS indexed FROM books b
                JOIN documents d ON d.id=b.doc_id LEFT JOIN doc_index i ON i.doc_id=d.id
                WHERE {where} ORDER BY b.added_at DESC, b.title LIMIT ? OFFSET ?""", (*args, limit, offset))]
        for r in rows:
            r["authors"] = json.loads(r["authors"] or "[]")
            r["meta"] = json.loads(r["meta"] or "{}")
            r["actors"] = [dict(a) for a in con.execute(
                """SELECT a.key, a.label, a.kind, da.hits FROM doc_actors da JOIN actors a ON a.key=da.actor_key
                   WHERE da.doc_id=? AND a.kind != 'country' ORDER BY da.hits DESC LIMIT 8""", (r["doc_id"],))]
            r["topics"] = [dict(t) for t in con.execute(
                "SELECT topic, score FROM doc_topics WHERE doc_id=? ORDER BY score DESC LIMIT 5", (r["doc_id"],))]
    return total, rows


def book_ids() -> frozenset:
    """Sources of the kind "book" (publishing houses of the local library)."""
    with db.session() as con:
        return frozenset(r[0] for r in con.execute("SELECT id FROM sources WHERE publisher='book'"))
