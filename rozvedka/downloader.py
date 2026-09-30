"""Download discovered documents to local storage."""
import concurrent.futures as cf
import hashlib
import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import db, fetch
from .config import FILES, MAX_FILE_MB

log = logging.getLogger("rozvedka.download")


def slug(s: str, n: int = 60) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()[:n] or "doc"


def target_path(doc, src) -> Path:
    stem = unquote(urlsplit(doc["url"]).path.rsplit("/", 1)[-1]).rsplit(".", 1)[0]
    name = f"{doc['year'] or 'undated'}_{doc['lang'] or 'xx'}_{slug(stem or doc['title'])}_{doc['id']}.pdf"
    return FILES / slug(src["country"], 10) / slug(src["agency"], 40) / name


def pdf_info(path: Path) -> tuple[int | None, str | None]:
    try:
        from pypdf import PdfReader
        r = PdfReader(str(path))
        title = (r.metadata.title if r.metadata else None) or None
        return len(r.pages), title
    except Exception:  # noqa: BLE001 - metadata is best effort
        return None, None


def download_one(doc_id: int) -> str:
    with db.session() as con:
        doc = con.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        src = con.execute("SELECT * FROM sources WHERE id=?", (doc["source_id"],)).fetchone()
    dest = target_path(doc, src)
    tmp = dest.with_suffix(".part")
    status, error, fields = "failed", None, {}
    try:
        resp = fetch.download(doc["url"], tmp, lenient=src["access"] == "tls-lenient", max_bytes=MAX_FILE_MB * 2**20)
        head = tmp.read_bytes()[:1024] if tmp.exists() else b""
        if resp.status == 404 or resp.status == 410:
            status, error = ("missing" if doc["origin"] == "pattern" else "failed"), f"http {resp.status}"
        elif resp.status != 200:
            error = f"http {resp.status}"
        elif b"%PDF" not in head:
            if "html" in (resp.content_type or "") or head.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
                # still a report worth listing – the site only hands the file to a real browser
                status, error = "browser-only", "site returned a web page, not the file – open the original link in a browser"
            else:
                status, error = "skipped", f"not a PDF ({resp.content_type or 'unknown type'})"
        else:
            data = tmp.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            with db.session() as con:
                dup = con.execute("SELECT id, local_path FROM documents WHERE sha256=? AND id!=? AND local_path IS NOT NULL",
                                  (sha, doc_id)).fetchone()
            if dup:
                status, error = "duplicate", f"same file as document #{dup['id']}"
                fields = {"sha256": sha, "size": len(data)}
            else:
                tmp.replace(dest)
                pages, pdf_title = pdf_info(dest)
                status = "downloaded"
                fields = {"sha256": sha, "size": len(data), "local_path": str(dest.relative_to(FILES)),
                          "pages_count": pages, "mime": "application/pdf",
                          "downloaded_at": datetime.now().isoformat(timespec="seconds")}
                if pdf_title and len(pdf_title) > 8 and re.fullmatch(r"[\w .%-]+\.pdf", doc["title"] or "", re.I):
                    fields["title"] = pdf_title[:300]
    except fetch.Blocked:
        error = "blocked by robots.txt"
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"[:300]
    finally:
        tmp.unlink(missing_ok=True)
    fields.update(status=status, error=error)
    with db.session() as con:
        con.execute(f"UPDATE documents SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                    (*fields.values(), doc_id))
    log.info("#%d %s %s %s", doc_id, status, doc["url"][:90], error or "")
    return status


def download(country: str | None = None, retry_failed: bool = False, limit: int | None = None, workers: int = 4) -> dict:
    statuses = ("new", "failed") if retry_failed else ("new",)
    q = f"""SELECT d.id FROM documents d JOIN sources s ON s.id=d.source_id
            WHERE d.status IN ({','.join('?' * len(statuses))}) AND d.hidden=0 AND s.access!='manual'"""
    args = list(statuses)
    if country:
        q += " AND s.country=?"; args.append(country.upper())
    q += " ORDER BY d.year DESC NULLS LAST, d.id"
    if limit:
        q += f" LIMIT {int(limit)}"
    with db.session() as con:
        ids = [r["id"] for r in con.execute(q, args)]
    stats: dict[str, int] = {}
    # per-host delay in fetch keeps this polite even with several workers
    with cf.ThreadPoolExecutor(workers) as ex:
        for st in ex.map(download_one, ids):
            stats[st] = stats.get(st, 0) + 1
    with db.session() as con:
        con.execute("INSERT INTO runs(kind,finished_at,summary) VALUES('download',datetime('now'),?)", (str(stats),))
    return stats
