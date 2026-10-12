import copy
import datetime as dt
import functools
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH, DATA, ROOT

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY,
    key         TEXT UNIQUE NOT NULL,          -- country/agency
    country     TEXT NOT NULL,
    agency      TEXT NOT NULL,
    name_local  TEXT,                          -- official name in the original language
    name_en     TEXT,                          -- official English name
    homepage    TEXT,
    description TEXT,
    logo_url    TEXT,                          -- optional override from the registry
    logo_path   TEXT,                          -- fetched logo, relative to data/logos
    hq_address  TEXT,                          -- publicly listed headquarters / contact address
    lat         REAL,
    lon         REAL,
    hq_precision TEXT,                         -- address | street | city
    domains     TEXT,                          -- extra official domains, comma-separated
    type        TEXT,
    access      TEXT,
    frequency   TEXT,
    report_types TEXT,
    notes       TEXT,
    active      INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS pages (
    id          INTEGER PRIMARY KEY,
    source_id   INTEGER NOT NULL REFERENCES sources(id),
    url         TEXT NOT NULL,
    lang        TEXT,
    kind        TEXT,
    note        TEXT,
    verified    INTEGER DEFAULT 1,
    last_crawled TEXT,
    last_status TEXT,
    active      INTEGER DEFAULT 1,
    UNIQUE(source_id, url)
);
CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY,
    source_id   INTEGER NOT NULL REFERENCES sources(id),
    page_id     INTEGER REFERENCES pages(id),
    url         TEXT UNIQUE NOT NULL,
    title       TEXT,
    lang        TEXT,
    year        INTEGER,
    status      TEXT DEFAULT 'new',           -- new | downloaded | failed | skipped
    error       TEXT,
    local_path  TEXT,
    sha256      TEXT,
    size        INTEGER,
    pages_count INTEGER,
    mime        TEXT,
    origin      TEXT DEFAULT 'crawl',         -- crawl | pattern | manual
    hidden      INTEGER DEFAULT 0,
    discovered_at TEXT DEFAULT (datetime('now')),
    downloaded_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_docs_source ON documents(source_id);
CREATE INDEX IF NOT EXISTS ix_docs_status ON documents(status);
CREATE INDEX IF NOT EXISTS ix_docs_sha ON documents(sha256);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    kind TEXT, started_at TEXT DEFAULT (datetime('now')), finished_at TEXT, summary TEXT
);
"""


def connect() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


@contextmanager
def session():
    con = connect()
    try:
        yield con
        con.commit()
    finally:
        con.close()


def version() -> tuple:
    """Changes whenever anything is written to the database (file and write-ahead log: time, size) – the key of cached results."""
    out = [str(DB_PATH), dt.date.today().isoformat()]       # the day too: pages show ages and "this year"
    for suffix in ("", "-wal"):
        try:
            st = DB_PATH.with_name(DB_PATH.name + suffix).stat()
            out += [st.st_mtime_ns, st.st_size]
        except OSError:
            out += [0, 0]
    try:        # hand-edited data files (series, registry, taxonomy …) count as part of the data
        out += [f.stat().st_mtime_ns for f in sorted((ROOT / "sources").glob("*.yaml"))]
    except OSError:
        pass
    return tuple(out)


def cached(fn):
    """Keep the result of a read-only query function until the database changes (arguments must be hashable).
    Callers get their own copy, so they may modify what they receive."""
    store: dict = {}

    @functools.wraps(fn)
    def wrapper(*args, **kw):
        key = (args, tuple(sorted(kw.items())))
        v = version()
        hit = store.get(key)
        if hit is None or hit[0] != v:
            if len(store) > 64:
                store.clear()
            hit = store[key] = (v, fn(*args, **kw))
        return copy.deepcopy(hit[1])
    wrapper.cache_clear = store.clear
    return wrapper


# columns added after the first release; ALTER TABLE brings older databases up to date
MIGRATIONS = {
    "documents": {"year_source": "TEXT",      # where the year came from when not from the title/URL (rozvedka/dating.py)
                  "dataset": "TEXT",          # the dataset a report was imported from (rozvedka/dataset.py)
                  "doc_type": "TEXT", "doc_type_why": "TEXT",    # kind of publication and the rule behind it (rozvedka/doctypes.py)
                  "work_id": "INTEGER", "work_why": "TEXT"},     # the file representing its report, and why (rozvedka/works.py)
    "sources": {"name_local": "TEXT", "name_en": "TEXT", "homepage": "TEXT", "description": "TEXT",
                "logo_url": "TEXT", "logo_path": "TEXT", "hq_address": "TEXT", "lat": "REAL", "lon": "REAL",
                "hq_precision": "TEXT", "domains": "TEXT",
                "publisher": "TEXT DEFAULT 'official'"},   # official (run by a state or states) | independent (think tank)
    "pages": {"follow": "TEXT"},                  # regex: publication pages to open from a list page (think tanks)
}


def init():
    with session() as con:
        con.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
            for col, typ in cols.items():
                if col not in have:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
