"""To collect: what the crawler cannot fetch and needs a person – and the hand import of those reports.

Four lists: editions missing from confirmed report series, reports listed but refused to scripts ("browser-only",
failed), sources without automatic access (bot-protected or never yielding a report), and PDFs waiting in the
inbox folder (data/inbox/). A report added by hand keeps the official URL it came from, the date it was added and
whether that URL is on the agency's official domains.
"""
import datetime as dt
import re
import shutil
import tempfile
from pathlib import Path

from . import crawler, db, downloader, series
from .config import DATA, MAX_FILE_MB

INBOX = DATA / "inbox"

SCHEMA = """
CREATE TABLE IF NOT EXISTS collect_checks (      -- "checked, nothing new": when a source was last looked at by hand
    source_id INTEGER PRIMARY KEY, checked_at TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS uploads (             -- provenance of reports added by hand
    doc_id INTEGER PRIMARY KEY, added_at TEXT, via TEXT, original_name TEXT, official INTEGER);
"""


def init() -> None:
    with db.session() as con:
        con.executescript(SCHEMA)
    INBOX.mkdir(parents=True, exist_ok=True)


def _source(con, source_id: int):
    src = con.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if not src:
        raise ValueError("unknown source")
    return src


def official(src, url: str) -> bool:
    """Whether a URL is on one of the agency's official domains (home page, report pages, registry `domains`)."""
    with db.session() as con:
        pages = [r["url"] for r in con.execute("SELECT url FROM pages WHERE source_id=?", (src["id"],))]
    fams = crawler.official_families(src, None) | {crawler.domain_family(u) for u in pages}
    return crawler.domain_family(url) in fams


# ── adding a report by hand ──
def add_file(source_id: int, url: str, path: Path, title: str = "", lang: str = "", year: str | int = "",
             via: str = "upload", original_name: str = "") -> dict:
    """A PDF from the owner's browser or the inbox → a report of the source, with its official URL.

    The file must be a PDF; an identical file (same SHA-256) is not stored twice. When the URL is already known
    (a report listed but blocked), the file is attached to that report."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("the official URL must start with http:// or https://")
    if path.stat().st_size > MAX_FILE_MB * 2**20:
        raise ValueError(f"file larger than {MAX_FILE_MB} MB")
    if b"%PDF" not in path.read_bytes()[:1024]:
        raise ValueError("not a PDF file")
    init()
    with db.session() as con:
        src = _source(con, source_id)
        row = con.execute("SELECT * FROM documents WHERE url=?", (url,)).fetchone()
        if row and row["source_id"] != source_id:
            raise ValueError(f"this URL belongs to another source (document #{row['id']})")
        y = int(year) if str(year).strip().isdigit() else crawler.guess_year(title or original_name, url)
        if row is None:
            con.execute("""INSERT INTO documents(source_id,url,title,lang,year,origin) VALUES(?,?,?,?,?,'upload')""",
                        (source_id, url, (title or original_name or url.rsplit("/", 1)[-1]).strip()[:300],
                         lang.strip().lower(), y))
            row = con.execute("SELECT * FROM documents WHERE url=?", (url,)).fetchone()
        else:   # complete what the owner filled in
            con.execute("""UPDATE documents SET title=COALESCE(NULLIF(?,''), title), lang=COALESCE(NULLIF(?,''), lang),
                           year=COALESCE(?, year), hidden=0 WHERE id=?""",
                        (title.strip()[:300], lang.strip().lower(), y, row["id"]))
            row = con.execute("SELECT * FROM documents WHERE id=?", (row["id"],)).fetchone()
    dest = downloader.target_path(row, src)
    tmp = dest.with_suffix(".upload")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, tmp)
    try:
        status, error, fields = downloader.store_pdf(row, dest, tmp)
    finally:
        tmp.unlink(missing_ok=True)
    fields.update(status=status, error=error)
    is_official = official(src, url)
    with db.session() as con:
        con.execute(f"UPDATE documents SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", (*fields.values(), row["id"]))
        if status == "downloaded":
            con.execute("INSERT OR REPLACE INTO uploads VALUES(?,?,?,?,?)",
                        (row["id"], dt.datetime.now().isoformat(timespec="seconds"), via, original_name, int(is_official)))
    return {"doc_id": row["id"], "status": status, "error": error, "official": is_official}


def add_upload(source_id: int, url: str, fileobj, filename: str, **kw) -> dict:
    """Same as add_file for a file uploaded through the portal (streamed to a temporary file)."""
    with tempfile.NamedTemporaryFile(dir=DATA, suffix=".pdf", delete=False) as tmp:
        shutil.copyfileobj(fileobj, tmp, length=1 << 20)
        tmp_path = Path(tmp.name)
    try:
        return add_file(source_id, url, tmp_path, original_name=filename, **kw)
    finally:
        tmp_path.unlink(missing_ok=True)


def checked(source_id: int, note: str = "") -> None:
    init()
    with db.session() as con:
        con.execute("INSERT OR REPLACE INTO collect_checks VALUES(?,?,?)",
                    (source_id, dt.datetime.now().isoformat(timespec="seconds"), note.strip()))


# ── the lists ──
def _sources(con, source: str = "") -> dict[int, dict]:
    sql = "SELECT * FROM sources WHERE active=1"
    args = []
    if source:
        sql += " AND key=?"; args.append(source)
    return {r["id"]: dict(r) for r in con.execute(sql, args)}


def _pages(con) -> dict[int, list]:
    out: dict[int, list] = {}
    for r in con.execute("SELECT source_id, url, lang, kind, verified FROM pages WHERE active=1 ORDER BY kind, lang"):
        out.setdefault(r["source_id"], []).append(dict(r))
    return out


def missing_editions(source: str = "", today: dt.date | None = None) -> list[dict]:
    """Missing editions of confirmed series, plus the latest expected one per language; with the source's
    documents of that year and language that are not counted in the series (perhaps the edition itself)."""
    today = today or dt.date.today()
    init()
    out = []
    with db.session() as con:
        srcs = {s["key"]: s for s in _sources(con, source).values()}
        pages = _pages(con)
        for s in series.load()["series"]:
            if s["source"] not in srcs:
                continue
            c = series.coverage(con, s, today)
            src = srcs[s["source"]]
            for row in c["rows"]:
                expected = [cell for cell in row["cells"] if cell["state"] == "expected"]
                wanted = [cell for cell in row["cells"] if cell["state"] == "missing"] + expected[:1]
                for cell in wanted:
                    counted = set(cell["docs"])
                    cands = [dict(r) for r in con.execute(
                        f"""SELECT d.id, d.title, d.url, d.status, d.local_path FROM documents d
                            WHERE d.source_id=? AND d.year=? AND (d.lang=? OR d.lang IS NULL OR d.lang='')
                              AND {series.LISTED} ORDER BY d.title""", (src["id"], cell["year"], row["lang"]))
                             if r["id"] not in counted]
                    out.append({"source": src, "series": s["name"], "year": cell["year"], "lang": row["lang"],
                                "state": cell["state"], "candidates": cands[:8],
                                "pages": [p for p in pages.get(src["id"], []) if not p["lang"] or row["lang"] in p["lang"]]
                                or pages.get(src["id"], [])})
    out.sort(key=lambda m: (m["state"] != "missing", -m["year"], m["source"]["key"], m["lang"]))
    return out


def blocked(source: str = "") -> list[dict]:
    """Reports the library knows but could not download: the site hands the file only to a browser, or failed."""
    with db.session() as con:
        srcs = _sources(con, source)
        rows = [dict(r) for r in con.execute(
            """SELECT d.id, d.source_id, d.title, d.url, d.year, d.lang, d.status, d.error FROM documents d
               WHERE d.hidden=0 AND d.status IN ('browser-only','failed') ORDER BY d.status, d.year DESC NULLS LAST""")]
    return [{**r, "source": srcs[r["source_id"]]} for r in rows if r["source_id"] in srcs]


def manual_sources(source: str = "") -> list[dict]:
    """Sources the crawler cannot read (bot-protected, unverified pages) or that never yielded a report."""
    init()
    with db.session() as con:
        srcs = _sources(con, source)
        counts = dict(con.execute("""SELECT source_id, COUNT(*) FROM documents WHERE hidden=0 AND local_path IS NOT NULL
                                     GROUP BY source_id""").fetchall())
        latest = dict(con.execute("SELECT source_id, MAX(year) FROM documents WHERE hidden=0 GROUP BY source_id").fetchall())
        checks = {r["source_id"]: dict(r) for r in con.execute("SELECT * FROM collect_checks")}
        pages = _pages(con)
    out = []
    for sid, s in srcs.items():
        unverified = [p for p in pages.get(sid, []) if not p["verified"]]
        if s["access"] == "manual" or unverified or not counts.get(sid):
            out.append({"source": s, "pages": pages.get(sid, []), "docs": counts.get(sid, 0), "latest": latest.get(sid),
                        "check": checks.get(sid),
                        "why": "bot-protected – open in a browser" if s["access"] == "manual"
                               else "some report pages blocked" if unverified else "no report found automatically"})
    out.sort(key=lambda x: ((x["check"] or {}).get("checked_at") or "", x["docs"], x["source"]["key"]))
    return out


# ── the inbox folder ──
def _guess_source(srcs: dict[int, dict], folder: str) -> int | None:
    f = re.sub(r"[^a-z0-9]+", "", folder.lower())
    for sid, s in srcs.items():
        if f and f in (re.sub(r"[^a-z0-9]+", "", s["key"].lower()), re.sub(r"[^a-z0-9]+", "", s["agency"].lower())):
            return sid
    return None


def inbox() -> list[dict]:
    """PDFs in data/inbox/ (any sub-folder; a folder named after the source – 'CZ_BIS', 'BIS' – preselects it)."""
    if not INBOX.exists():
        return []
    with db.session() as con:
        srcs = _sources(con)
    out = []
    for f in sorted(INBOX.rglob("*")):
        if not f.is_file() or f.name.startswith("."):
            continue
        rel = f.relative_to(INBOX)
        folder = rel.parts[0] if len(rel.parts) > 1 else ""
        _, pdf_title = downloader.pdf_info(f) if f.suffix.lower() == ".pdf" else (None, None)
        name = f.stem
        out.append({"path": rel.as_posix(), "name": f.name, "size": f.stat().st_size, "is_pdf": f.suffix.lower() == ".pdf",
                    "source_id": _guess_source(srcs, folder), "title": (pdf_title if downloader.good_pdf_title(pdf_title) else
                                                                       downloader.slug(name, 120).replace("-", " ")),
                    "year": crawler.guess_year(name, "") or "", "lang": crawler.guess_lang(f.name, name, "", set(), ) or ""})
    return out


def import_inbox(rel: str, source_id: int, url: str, **kw) -> dict:
    path = (INBOX / rel).resolve()
    if not path.is_relative_to(INBOX.resolve()) or not path.is_file():
        raise ValueError("file not in the inbox")
    result = add_file(source_id, url, path, via="inbox", original_name=path.name, **kw)
    if result["status"] in ("downloaded", "duplicate"):
        path.unlink()
    return result


def freshness() -> dict:
    """How old the data is – there is no periodic job; updates are started by hand."""
    with db.session() as con:
        crawl = con.execute("SELECT MAX(last_crawled) FROM pages").fetchone()[0]
        dl = con.execute("SELECT MAX(downloaded_at) FROM documents").fetchone()[0]
    def age(ts):
        if not ts:
            return None
        return (dt.datetime.now() - dt.datetime.fromisoformat(ts[:19])).days
    return {"last_crawl": crawl, "crawl_days": age(crawl), "last_download": dl, "download_days": age(dl)}


def status_counts(source: str = "") -> dict:
    return {"missing": len(missing_editions(source)), "blocked": len(blocked(source)),
            "manual": len(manual_sources(source)), "inbox": len(inbox())}

