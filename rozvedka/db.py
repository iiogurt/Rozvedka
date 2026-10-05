import sqlite3
from contextlib import contextmanager

from .config import DB_PATH, DATA

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


# columns added after the first release; ALTER TABLE brings older databases up to date
MIGRATIONS = {
    "documents": {"year_source": "TEXT",      # where the year came from when not from the title/URL (rozvedka/dating.py)
                  "dataset": "TEXT"},         # the dataset a report was imported from (rozvedka/dataset.py)
    "sources": {"name_local": "TEXT", "name_en": "TEXT", "homepage": "TEXT", "description": "TEXT",
                "logo_url": "TEXT", "logo_path": "TEXT", "hq_address": "TEXT", "lat": "REAL", "lon": "REAL",
                "hq_precision": "TEXT", "domains": "TEXT"},
}


def init():
    with session() as con:
        con.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
            for col, typ in cols.items():
                if col not in have:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
