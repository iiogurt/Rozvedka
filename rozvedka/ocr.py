"""Text for scanned reports – optical character recognition with Tesseract (through OCRmyPDF).

Reports whose PDF has (almost) no text layer – fewer than 2,000 characters, or fewer than 120 per page – are
recognised page by page in the report's language plus English. Only the recognised text is stored, with its page
breaks; the original PDF is never changed. The text is marked as OCR (engine, version, languages, date) wherever it
is shown, because recognition makes mistakes. Afterwards the report goes through topics, dates and actors like any
other.

    python -m rozvedka ocr [--limit N] [--workers 3]

Needs the Debian packages `ocrmypdf` and `tesseract-ocr` with the language data (`tesseract-ocr-spa` …).
"""
import concurrent.futures as cf
import datetime as dt
import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import db, topics
from .config import FILES

log = logging.getLogger("rozvedka.ocr")
OCRMYPDF = shutil.which("ocrmypdf")
TESSERACT = shutil.which("tesseract")
MIN_CHARS, MIN_PER_PAGE = 2000, 120
TIMEOUT = 60 * 60                      # seconds per report
# report language (ISO 639-1, as in the library) → Tesseract language data
LANGS = {"en": "eng", "es": "spa", "ro": "ron", "sk": "slk", "ja": "jpn", "nl": "nld", "de": "deu", "cs": "ces",
         "fr": "fra", "zh": "chi_sim", "et": "est", "ru": "rus", "nb": "nor", "no": "nor", "it": "ita", "pl": "pol",
         "el": "ell", "bg": "bul"}


def available() -> bool:
    return bool(OCRMYPDF and TESSERACT)


def tesseract_version() -> str:
    try:
        return subprocess.run([TESSERACT, "--version"], capture_output=True, text=True).stdout.split("\n")[0].strip()
    except Exception:  # noqa: BLE001
        return "tesseract"


def installed_langs() -> set[str]:
    try:
        out = subprocess.run([TESSERACT, "--list-langs"], capture_output=True, text=True).stdout
        return set(out.split()[1:]) if out else set()
    except Exception:  # noqa: BLE001
        return set()


def langs_for(lang: str | None, have: set[str]) -> str:
    wanted = [LANGS.get((lang or "").split("+")[0])] + ["eng"]
    return "+".join(dict.fromkeys(x for x in wanted if x and x in have)) or "eng"


def candidates(con, limit: int | None = None) -> list[dict]:
    """Downloaded reports without a usable text layer that have not been recognised yet."""
    sql = f"""SELECT d.id, d.local_path, d.lang, d.pages_count, i.chars FROM doc_index i JOIN documents d ON d.id=i.doc_id
              WHERE d.hidden=0 AND d.local_path IS NOT NULL AND i.ocr IS NULL
                AND (i.chars < {MIN_CHARS} OR i.chars < {MIN_PER_PAGE} * COALESCE(d.pages_count, 1))
              ORDER BY COALESCE(d.pages_count, 1)"""
    return [dict(r) for r in con.execute(sql + (f" LIMIT {int(limit)}" if limit else ""))]


def recognise(doc: dict, langs: str) -> dict:
    """Worker: OCR the first topics.MAX_PAGES pages; returns the text with page offsets (or the error)."""
    src = FILES / doc["local_path"]
    with tempfile.TemporaryDirectory() as tmp:
        sidecar = Path(tmp) / "text.txt"
        last = min(doc["pages_count"] or topics.MAX_PAGES, topics.MAX_PAGES)
        cmd = [OCRMYPDF, "-q", "--force-ocr", "--output-type", "none", "--sidecar", str(sidecar), "-l", langs,
               "--jobs", "1", "--pages", f"1-{last}", str(src), "-"]
        try:
            run = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"id": doc["id"], "error": f"timeout after {TIMEOUT} s"}
        if run.returncode != 0 or not sidecar.exists():
            return {"id": doc["id"], "error": (run.stderr.strip().splitlines() or [f"exit {run.returncode}"])[-1][:300]}
        pages = sidecar.read_text(encoding="utf-8", errors="replace").split("\f")
    text, offsets = "", []
    for page in pages:
        if len(text) >= topics.MAX_CHARS:
            break
        offsets.append(len(text))
        text += topics._clean(page) + "\n"
    return {"id": doc["id"], "text": text[:topics.MAX_CHARS], "pages": offsets, "error": None}


def run(limit: int | None = None, workers: int = 3) -> dict:
    """Recognise the candidates and replace their (near-empty) text; then index topics, dates and actors."""
    if not available():
        return {"error": "ocrmypdf/tesseract not installed"}
    topics.init()
    have = installed_langs()
    version = tesseract_version()
    with db.session() as con:
        todo = candidates(con, limit)
    stats = {"candidates": len(todo), "recognised": 0, "failed": 0, "no_gain": 0}
    con = db.connect()
    try:
        with cf.ProcessPoolExecutor(workers) as ex:
            futures = {ex.submit(recognise, d, langs_for(d["lang"], have)): d for d in todo}
            for n, fut in enumerate(cf.as_completed(futures), 1):
                d = futures[fut]
                r = fut.result()
                meta = {"engine": version, "langs": langs_for(d["lang"], have), "date": dt.date.today().isoformat()}
                if r["error"]:
                    stats["failed"] += 1
                    con.execute("UPDATE doc_index SET ocr=? WHERE doc_id=?", (json.dumps({**meta, "error": r["error"]}), d["id"]))
                elif len(r["text"].strip()) <= (d["chars"] or 0):
                    stats["no_gain"] += 1
                    con.execute("UPDATE doc_index SET ocr=? WHERE doc_id=?", (json.dumps({**meta, "no_gain": True}), d["id"]))
                else:
                    stats["recognised"] += 1
                    title = con.execute("SELECT title FROM documents WHERE id=?", (d["id"],)).fetchone()[0]
                    con.execute("DELETE FROM doc_text WHERE rowid=?", (d["id"],))
                    con.execute("INSERT INTO doc_text(rowid, title, body) VALUES(?,?,?)", (d["id"], title, r["text"]))
                    con.execute("""UPDATE doc_index SET chars=?, words=?, pages=?, extracted_at=?, ocr=?, taxonomy_hash=NULL
                                   WHERE doc_id=?""",
                                (len(r["text"]), len(r["text"].split()), json.dumps(r["pages"]),
                                 dt.datetime.now().isoformat(timespec="seconds"), json.dumps({**meta, "chars": len(r["text"])}),
                                 d["id"]))
                    cols = {c[1] for c in con.execute("PRAGMA table_info(doc_index)")}
                    if "actors_hash" in cols:
                        con.execute("UPDATE doc_index SET actors_hash=NULL WHERE doc_id=?", (d["id"],))
                con.commit()
                log.info("ocr %d/%d #%d %s", n, len(todo), d["id"], "failed: " + r["error"] if r["error"] else "ok")
    finally:
        con.close()
    if stats["recognised"]:
        from . import actor_sources, actors, dating
        stats["topics"] = topics.index()
        stats["dates"] = dating.date_documents()
        if actor_sources.GAZETTEER.exists():
            stats["actors"] = actors.index()
    return stats
