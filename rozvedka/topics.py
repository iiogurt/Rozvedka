"""Topic indexing: extract report text, store it for full-text search, and tag documents with topics.

Taxonomy: sources/topics.yaml (categories → topics → multilingual terms). Text is extracted once per document
(pdftotext, first MAX_PAGES pages, capped at MAX_CHARS) into an SQLite FTS5 table. Classification runs on the
stored text, so editing the taxonomy only needs `index-topics` again – no re-download, no re-extraction.
"""
import bisect
import concurrent.futures as cf
import hashlib
import json
import logging
import math
import re
import shutil
import subprocess
import unicodedata
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import yaml

from . import db
from .config import FILES, ROOT

log = logging.getLogger("rozvedka.topics")
TAXONOMY = ROOT / "sources" / "topics.yaml"
MAX_PAGES = 150          # enough to characterise a report; IPCC volumes have 2,000+ pages
MAX_CHARS = 400_000      # stored text per document (full-text search + classification)
PDFTOTEXT = shutil.which("pdftotext")

# ── normalisation: case- and accent-insensitive, same for text and terms ──
_FOLD = str.maketrans({"ß": "ss", "ø": "o", "æ": "ae", "œ": "oe", "ł": "l", "đ": "d", "ð": "d", "þ": "th",
                       "ı": "i", "’": "'", "‘": "'", "–": "-", "—": "-", "­": ""})
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯＀-￯]")


def normalize(text: str) -> str:
    text = text.lower().translate(_FOLD)
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def term_regex(term: str) -> str:
    """'pravicov* extremis*' → regex for the phrase; CJK terms match as plain substrings."""
    t = normalize(term.strip())
    if _CJK.search(t):
        return re.escape(t)
    parts = []
    for tok in t.split():
        stem = tok.endswith("*")
        body = re.escape(tok.rstrip("*"))
        parts.append(body + (r"\w*" if stem else ""))
    rx = r"[\s\-/]+".join(parts)
    last_is_stem = t.split()[-1].endswith("*")
    return r"(?<!\w)" + rx + ("" if last_is_stem else r"(?!\w)")


# ── taxonomy ──
_WORD = re.compile(r"\w+")


def term_tokens(term: str) -> list[tuple[str, bool]]:
    """'right-wing extrem*' → [('right', False), ('wing', False), ('extrem', True)] (normalised, stem flag)."""
    return [(tok.rstrip("*"), tok.endswith("*")) for tok in re.findall(r"\w+\*?", normalize(term))]


@lru_cache(maxsize=1)
def taxonomy() -> dict:
    """Topics with their terms compiled for fast word-based matching.

    Per topic: exact (word → term), stems (prefix → term), phrases (token tuples), cjk (substrings);
    'regex' is kept for short strings such as titles.
    """
    raw = TAXONOMY.read_bytes()
    data = yaml.safe_load(raw)
    topics = {}
    for ckey, cat in data["categories"].items():
        for tkey, tp in cat["topics"].items():
            terms = [t for lang_terms in tp["terms"].values() for t in lang_terms]
            exact, stems, phrases, cjk = {}, {}, [], []
            for t in terms:
                if _CJK.search(normalize(t)):
                    cjk.append(normalize(t))
                    continue
                toks = term_tokens(t)
                if len(toks) == 1:
                    word, stem = toks[0]
                    (stems if stem else exact)[word] = t
                elif toks:
                    phrases.append((tuple(toks), t))
            alternatives = sorted({term_regex(t) for t in terms}, key=len, reverse=True)
            topics[tkey] = {"key": tkey, "name": tp["name"], "category": ckey, "category_name": cat["name"],
                            "terms": terms, "exact": exact, "stems": stems, "phrases": phrases, "cjk": cjk,
                            "stem_lens": sorted({len(k) for k in stems}), "meta": bool(tp.get("meta")),
                            "regex": re.compile("|".join(alternatives))}
    return {"categories": {k: {"name": c["name"], "topics": list(c["topics"])} for k, c in data["categories"].items()},
            "topics": topics, "hash": hashlib.sha256(raw).hexdigest()[:16]}


def reload() -> None:
    taxonomy.cache_clear()


def _token_matches(word: str, tok: tuple[str, bool]) -> bool:
    base, stem = tok
    return word.startswith(base) if stem else word == base


# ── classification ──
def count_terms(body: str, tp: dict, tokens: list[str], vocab: dict[str, int],
                positions: dict[str, list[int]]) -> dict[str, int]:
    """How often each term of one topic occurs in an already tokenised text."""
    counts: dict[str, int] = {}
    exact, stems, lens = tp["exact"], tp["stems"], tp["stem_lens"]
    for word, n in vocab.items():                   # single-word terms: dictionary lookups per distinct word
        term = exact.get(word)
        if term is None:
            for L in lens:
                if L > len(word):
                    break
                term = stems.get(word[:L])
                if term is not None:
                    break
        if term is not None:
            counts[term] = counts.get(term, 0) + n
    for toks, term in tp["phrases"]:                # phrases: checked only where the first word occurs
        base, stem = toks[0]
        starts = [w for w in positions if w.startswith(base)] if stem else ([base] if base in positions else [])
        n = 0
        for w in starts:
            for i in positions[w]:
                if i + len(toks) <= len(tokens) and all(_token_matches(tokens[i + k], toks[k]) for k in range(1, len(toks))):
                    n += 1
        if n:
            counts[term] = counts.get(term, 0) + n
    for sub in tp["cjk"]:
        n = body.count(sub)
        if n:
            counts[sub] = counts.get(sub, 0) + n
    return counts


def classify(text: str, title: str = "") -> list[dict]:
    """Topics found in a text, best first. Each: key, score, hits, distinct, title_hit, terms (most frequent)."""
    body = normalize(text)
    head = normalize(title or "")
    tokens = _WORD.findall(body)
    words = max(len(tokens), 1)
    vocab: dict[str, int] = {}
    positions: dict[str, list[int]] = {}
    for i, w in enumerate(tokens):
        vocab[w] = vocab.get(w, 0) + 1
        positions.setdefault(w, []).append(i)
    needed = max(3, math.ceil(words / 15_000))
    found = []
    for key, tp in taxonomy()["topics"].items():
        counts = count_terms(body, tp, tokens, vocab, positions)
        title_hit = bool(head and tp["regex"].search(head))
        hits, distinct = sum(counts.values()), len(counts)
        # enough evidence: the title says so, or several different terms appear often enough for the length
        if not (title_hit or (distinct >= 2 and hits >= needed)):
            continue
        density = hits / words * 10_000                  # hits per 10,000 words
        score = round(math.log1p(density) * 10 + min(distinct, 12) * 1.5 + (25 if title_hit else 0), 2)
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:6]
        found.append({"key": key, "score": score, "hits": hits, "distinct": distinct, "title_hit": int(title_hit),
                      "terms": [t for t, _ in top]})
    return sorted(found, key=lambda f: -f["score"])


# ── text extraction ──
def _clean(page: str) -> str:
    page = re.sub(r"[ \t\r]+", " ", page)
    return re.sub(r"\n\s*\n+", "\n", page).strip("\n")


def extract_pages(path: Path) -> tuple[str, list[int]]:
    """Text of a PDF plus the offset where each page starts in it (page n starts at offsets[n-1])."""
    if PDFTOTEXT:
        out = subprocess.run([PDFTOTEXT, "-q", "-enc", "UTF-8", "-l", str(MAX_PAGES), str(path), "-"],
                             capture_output=True, timeout=300)
        pages = out.stdout.decode("utf-8", "replace").split("\f")    # pdftotext ends every page with a form feed
        if pages and not pages[-1].strip():
            pages.pop()
    else:   # slower pure-Python fallback
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        pages = [(p.extract_text() or "") for p in reader.pages[:MAX_PAGES]]
    text, offsets = "", []
    for page in pages:
        if len(text) >= MAX_CHARS:
            break
        offsets.append(len(text))
        text += _clean(page) + "\n"
    return text[:MAX_CHARS], offsets


def extract_text(path: Path) -> str:
    return extract_pages(path)[0]


def page_of(offsets: list[int] | None, pos: int) -> int | None:
    """1-based page number of a text offset, or None when page offsets are not known."""
    if not offsets:
        return None
    return bisect.bisect_right(offsets, pos)


# ── database ──
SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS doc_text USING fts5(
    title, body, tokenize = "unicode61 remove_diacritics 2");        -- rowid = documents.id
CREATE TABLE IF NOT EXISTS doc_index (
    doc_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    chars INTEGER, words INTEGER, extracted_at TEXT, error TEXT,
    taxonomy_hash TEXT, classified_at TEXT,
    pages TEXT);                                                    -- JSON: text offset where each page starts
CREATE TABLE IF NOT EXISTS doc_topics (
    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    topic TEXT NOT NULL, score REAL, hits INTEGER, distinct_terms INTEGER, title_hit INTEGER, terms TEXT,
    PRIMARY KEY (doc_id, topic));
CREATE INDEX IF NOT EXISTS ix_doc_topics_topic ON doc_topics(topic, score DESC);
"""


def init() -> None:
    with db.session() as con:
        con.executescript(SCHEMA)
        cols = {r["name"] for r in con.execute("PRAGMA table_info(doc_index)")}
        if "pages" not in cols:
            con.execute("ALTER TABLE doc_index ADD COLUMN pages TEXT")
        if "ocr" not in cols:   # JSON: engine, languages, date – the text came from optical character recognition
            con.execute("ALTER TABLE doc_index ADD COLUMN ocr TEXT")


def _process(doc: dict) -> dict:
    """Worker (separate process): extract a PDF's text and classify it."""
    try:
        text, pages = extract_pages(FILES / doc["local_path"])
    except Exception as e:  # noqa: BLE001 - one broken PDF must not stop the run
        return {"id": doc["id"], "text": None, "pages": None, "error": f"{type(e).__name__}: {e}"[:300], "found": []}
    return {"id": doc["id"], "text": text, "pages": pages, "error": None, "found": classify(text, doc["title"] or "")}


def _classify_only(item: tuple[int, str, str]) -> dict:
    """Worker: re-classify stored text (after the taxonomy changed)."""
    doc_id, body, title = item
    return {"id": doc_id, "found": classify(body or "", title or "")}


def _write_topics(con, doc_id: int, found: list[dict], tax_hash: str, now: str) -> None:
    con.execute("DELETE FROM doc_topics WHERE doc_id=?", (doc_id,))
    con.executemany(
        "INSERT INTO doc_topics(doc_id, topic, score, hits, distinct_terms, title_hit, terms) VALUES(?,?,?,?,?,?,?)",
        [(doc_id, f["key"], f["score"], f["hits"], f["distinct"], f["title_hit"],
          json.dumps(f["terms"], ensure_ascii=False)) for f in found])
    con.execute("UPDATE doc_index SET taxonomy_hash=?, classified_at=? WHERE doc_id=?", (tax_hash, now, doc_id))


def index(reextract: bool = False, limit: int | None = None, workers: int = 4, batch: int = 25) -> dict:
    """Extract + classify new downloads, then re-classify documents classified with an older taxonomy.

    Work runs in separate processes (all CPU cores); results are written in batches and appear in the portal
    while the run continues.
    """
    init()
    tax_hash = taxonomy()["hash"]
    stats = {"extracted": 0, "extract_errors": 0, "classified": 0}
    now = lambda: datetime.now().isoformat(timespec="seconds")  # noqa: E731
    with db.session() as con:
        q = """SELECT d.id, d.local_path, d.title FROM documents d LEFT JOIN doc_index i ON i.doc_id = d.id
               WHERE d.status = 'downloaded' AND d.local_path IS NOT NULL"""
        if not reextract:   # new downloads, and text extracted before page offsets were recorded
            q += " AND (i.extracted_at IS NULL OR (i.pages IS NULL AND i.error IS NULL))"
        else:               # recognised (OCR) text is kept: pdftotext would only bring back the empty layer
            q += " AND (i.ocr IS NULL OR i.ocr LIKE '%\"error\"%' OR i.ocr LIKE '%no_gain%')"
        todo = [dict(r) for r in con.execute(q + (f" LIMIT {int(limit)}" if limit else ""))]

    con = db.connect()
    con.execute("PRAGMA synchronous=NORMAL")     # WAL + NORMAL: safe on crash, far fewer SD-card flushes
    index_cols = {r["name"] for r in con.execute("PRAGMA table_info(doc_index)")}
    try:
        with cf.ProcessPoolExecutor(workers) as ex:
            futures = [ex.submit(_process, d) for d in todo]
            for n, fut in enumerate(cf.as_completed(futures), 1):
                r = fut.result()
                con.execute("DELETE FROM doc_text WHERE rowid=?", (r["id"],))
                title = next(d["title"] for d in todo if d["id"] == r["id"])
                if r["text"] is not None:
                    con.execute("INSERT INTO doc_text(rowid, title, body) VALUES(?,?,?)", (r["id"], title, r["text"]))
                con.execute("""INSERT INTO doc_index(doc_id, chars, words, extracted_at, error, pages) VALUES(?,?,?,?,?,?)
                               ON CONFLICT(doc_id) DO UPDATE SET chars=excluded.chars, words=excluded.words,
                                 extracted_at=excluded.extracted_at, error=excluded.error, pages=excluded.pages,
                                 taxonomy_hash=NULL""",   # (actor positions are reset below: they point into the old text)
                            (r["id"], len(r["text"] or ""), len((r["text"] or "").split()), now(), r["error"],
                             json.dumps(r["pages"]) if r["pages"] is not None else None))
                if "actors_hash" in index_cols:
                    con.execute("UPDATE doc_index SET actors_hash=NULL WHERE doc_id=?", (r["id"],))
                if r["error"]:
                    stats["extract_errors"] += 1
                else:
                    _write_topics(con, r["id"], r["found"], tax_hash, now())
                    stats["extracted"] += 1
                    stats["classified"] += 1
                if n % batch == 0:
                    con.commit()
                    log.info("indexed %d/%d", n, len(todo))
            con.commit()

            # documents extracted earlier but classified with an older taxonomy version
            stale = con.execute("""SELECT i.doc_id, t.body, d.title FROM doc_index i JOIN doc_text t ON t.rowid=i.doc_id
                                   JOIN documents d ON d.id=i.doc_id
                                   WHERE i.taxonomy_hash IS NULL OR i.taxonomy_hash != ?""", (tax_hash,)).fetchall()
            for n, r in enumerate(ex.map(_classify_only, [tuple(x) for x in stale], chunksize=8), 1):
                _write_topics(con, r["id"], r["found"], tax_hash, now())
                stats["classified"] += 1
                if n % batch == 0:
                    con.commit()
                    log.info("re-classified %d/%d", n, len(stale))
            con.commit()
    finally:
        con.close()
    return stats


MAIN_TOPICS = 3   # a report's main topics: the ones with the highest keyword score


def main_topic_clause() -> tuple[str, list]:
    """SQL: document d has topic ? among its MAIN_TOPICS non-meta topics (bind the topic after the returned args)."""
    meta = [t for t, v in taxonomy()["topics"].items() if v.get("meta")]
    sql = f"""d.id IN (SELECT doc_id FROM (SELECT doc_id, topic, ROW_NUMBER() OVER (PARTITION BY doc_id
                  ORDER BY score DESC, topic) rk FROM doc_topics WHERE topic NOT IN ({','.join('?' * len(meta))}))
              WHERE rk <= {MAIN_TOPICS} AND topic=?)"""
    return sql, meta


def fts_query(q: str) -> str:
    """User search text → safe FTS5 query: every word must occur (prefix match); quoted phrases kept."""
    phrases = re.findall(r'"([^"]+)"', q)
    rest = re.sub(r'"[^"]+"', " ", q)
    parts = [f'"{p.replace(chr(34), "")}"' for p in phrases]
    parts += [f'"{w}"*' for w in re.findall(r"\w+", rest)]
    return " AND ".join(parts)
