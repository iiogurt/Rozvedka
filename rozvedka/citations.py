"""Who cites whom: the web addresses in the report texts, tied to the library where they point into it.

`index` reads every http(s) address in the stored texts (once per report) and resolves it:
  - target_doc    – the address is a report of the library (same address after dropping "www.", a trailing slash, case);
  - target_source – the address lies on the site of one other source of the library: the host of its home page (and the
                    sub-domains of it), or, when the home page is deeper in a shared portal like gov.uk, that path; a host
                    two sources share is not guessed at (documents hosted elsewhere do not make a host the source's);
  - otherwise the host is counted as an outside source.
Addresses broken across lines in a PDF are not recovered, so the counts are minimums. Nothing is fetched."""
import re
from urllib.parse import unquote, urlsplit

from . import actors, db, paging, trends

URL = re.compile(r"https?://[^\s<>\"'«»]+", re.I)
TRAIL = ".,;:)]}>'\"»”’"

# hand labels for the most linked outside hosts (a host not listed is shown without a label)
HOST_KINDS = {
    "doi.org": "academic (DOI)", "arxiv.org": "academic", "jstor.org": "academic", "sciencedirect.com": "academic",
    "tandfonline.com": "academic", "springer.com": "academic", "link.springer.com": "academic", "researchgate.net": "academic",
    "archive.ph": "web archive", "archive.org": "web archive", "web.archive.org": "web archive", "archive.is": "web archive",
    "reuters.com": "news", "bbc.com": "news", "bbc.co.uk": "news", "theguardian.com": "news", "nytimes.com": "news",
    "washingtonpost.com": "news", "ft.com": "news", "politico.eu": "news", "politico.com": "news", "apnews.com": "news",
    "aljazeera.com": "news", "dw.com": "news", "spiegel.de": "news", "lemonde.fr": "news", "cnn.com": "news",
    "github.com": "code", "eur-lex.europa.eu": "law", "riigiteataja.ee": "law", "legislation.gov.uk": "law",
    "gesetze-im-internet.de": "law", "ec.europa.eu": "EU institution", "consilium.europa.eu": "EU institution",
    "europarl.europa.eu": "EU institution", "ecdc.europa.eu": "EU agency", "nato.int": "NATO", "un.org": "UN",
    "unodc.org": "UN", "who.int": "UN", "worldbank.org": "international organisation", "imf.org": "international organisation",
    "twitter.com": "social media", "x.com": "social media", "youtube.com": "social media", "facebook.com": "social media",
    "t.me": "social media", "linkedin.com": "social media", "microsoft.com": "security vendor", "mandiant.com": "security vendor",
    "crowdstrike.com": "security vendor", "kaspersky.com": "security vendor", "welivesecurity.com": "security vendor",
    "securelist.com": "security vendor", "trendmicro.com": "security vendor", "paloaltonetworks.com": "security vendor",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS doc_links (
    doc_id INTEGER NOT NULL, url TEXT NOT NULL, host TEXT NOT NULL, raw TEXT, n INTEGER,
    target_doc INTEGER, target_source INTEGER, PRIMARY KEY (doc_id, url));
CREATE INDEX IF NOT EXISTS ix_doc_links_host ON doc_links(host);
CREATE INDEX IF NOT EXISTS ix_doc_links_tdoc ON doc_links(target_doc);
CREATE INDEX IF NOT EXISTS ix_doc_links_tsrc ON doc_links(target_source);
"""


def init() -> None:
    with db.session() as con:
        con.executescript(SCHEMA)


def norm(url: str) -> tuple[str, str]:
    """(host without "www.", comparable address) – ("", "") when it is not a usable address."""
    url = url.strip().rstrip(TRAIL)
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
    except ValueError:
        return "", ""
    host = host[4:] if host.startswith("www.") else host
    if "." not in host or not re.search(r"[a-z]", host.split(".")[-1]):
        return "", ""
    return host, host + unquote(p.path).rstrip("/").lower()


def addresses(text: str) -> dict[str, dict]:
    """{comparable address: {host, raw (first form), n}} in one text."""
    out: dict[str, dict] = {}
    for m in URL.finditer(text or ""):
        host, key = norm(m.group(0))
        if host:
            e = out.setdefault(key, {"host": host, "raw": m.group(0).rstrip(TRAIL)[:300], "n": 0})
            e["n"] += 1
    return out


def index() -> dict:
    """Rebuild doc_links from the stored texts (about half a minute on the Pi)."""
    init()
    rows, resolved_doc, resolved_src = [], 0, 0
    with db.session() as con:
        docs: dict[str, list[int]] = {}
        for r in con.execute("SELECT id, url FROM documents"):
            docs.setdefault(norm(r["url"])[1], []).append(r["id"])
        # a source's site: the host of its home page (a home page deeper in a shared portal such as gov.uk is matched by its path)
        roots: dict[str, set[int]] = {}
        prefixes: list[tuple[str, int]] = []
        for r in con.execute("SELECT id, homepage FROM sources WHERE homepage IS NOT NULL AND homepage != ''"):
            h, key = norm(r["homepage"])
            if not h:
                continue
            if key == h:
                roots.setdefault(h, set()).add(r["id"])
            else:
                prefixes.append((key, r["id"]))
        root_of = {h: next(iter(s)) for h, s in roots.items() if len(s) == 1}

        def site_of(host: str, key: str) -> int | None:
            for prefix, sid in prefixes:
                if key == prefix or key.startswith(prefix + "/"):
                    return sid
            parts = host.split(".")
            for i in range(len(parts) - 1):                 # host, then its parents down to two labels
                sid = root_of.get(".".join(parts[i:]))
                if sid:
                    return sid
            return None

        own = dict(con.execute("SELECT id, source_id FROM documents").fetchall())
        for doc_id, body in con.execute("SELECT rowid, body FROM doc_text"):
            for key, e in addresses(body).items():
                target = next((d for d in docs.get(key, []) if d != doc_id), None)
                src = site_of(e["host"], key)
                if not target and src == own.get(doc_id):
                    continue                         # a report linking to its own agency's site cites nobody else
                if target:
                    resolved_doc += 1
                    ts = own.get(target)
                    src = ts if ts != own.get(doc_id) else None
                elif src:
                    resolved_src += 1
                rows.append((doc_id, key, e["host"], e["raw"], e["n"], target, src))
        con.execute("DELETE FROM doc_links")
        con.executemany("INSERT INTO doc_links VALUES (?,?,?,?,?,?,?)", rows)
    return {"links": len(rows), "reports": len({r[0] for r in rows}), "to_library_reports": resolved_doc,
            "to_other_agencies": resolved_src, "hosts": len({r[2] for r in rows})}


# ── queries ──
# the agency a link points to: the site it lies on, or the publisher of the library report it is the address of
CITED = "COALESCE(l.target_source, (SELECT source_id FROM documents WHERE id=l.target_doc))"


def _scoped(extra: str = "") -> tuple[str, list]:
    where, args, _ = trends.scope()
    return f"{where}{' AND ' + extra if extra else ''}", args


@db.cached
def overview() -> dict:
    where, args = _scoped()
    base = f"""FROM doc_links l JOIN documents d ON d.id=l.doc_id JOIN sources s ON s.id=d.source_id
               JOIN doc_index i ON i.doc_id=d.id WHERE {where}"""
    with db.session() as con:
        init()
        cited_sources = [dict(r) for r in con.execute(
            f"""SELECT l.target_source id, t.agency, t.country, COUNT(DISTINCT l.doc_id) reports, COUNT(DISTINCT d.source_id) agencies
                {base} AND l.target_source IS NOT NULL
                GROUP BY l.target_source ORDER BY reports DESC, agencies DESC LIMIT 40""".replace(
                "FROM doc_links l", "FROM doc_links l JOIN sources t ON t.id=l.target_source", 1), args)]
        hosts = [dict(r) for r in con.execute(
            f"""SELECT l.host, COUNT(DISTINCT l.doc_id) reports, COUNT(DISTINCT d.source_id) agencies
                {base} AND l.target_source IS NULL AND l.target_doc IS NULL
                GROUP BY l.host ORDER BY reports DESC, agencies DESC LIMIT 60""", args)]
        for h in hosts:
            h["kind"] = HOST_KINDS.get(h["host"], HOST_KINDS.get(".".join(h["host"].split(".")[-2:]), ""))
        cited_docs = [dict(r) for r in con.execute(
            f"""SELECT l.target_doc id, t.title, t.year, ts.agency, ts.country, COUNT(DISTINCT l.doc_id) reports
                {base.replace("FROM doc_links l", "FROM doc_links l JOIN documents t ON t.id=l.target_doc JOIN sources ts ON ts.id=t.source_id", 1)}
                AND l.target_doc IS NOT NULL GROUP BY l.target_doc ORDER BY reports DESC, t.year DESC LIMIT 40""", args)]
        totals = dict(con.execute(
            f"""SELECT COUNT(DISTINCT l.doc_id) reports, COUNT(*) links, COUNT(DISTINCT l.host) hosts,
                       SUM(l.target_doc IS NOT NULL) to_reports, SUM(l.target_source IS NOT NULL) to_agencies {base}""", args).fetchone())
        # flows between kinds of publisher: reports of one agency type that link to agencies (sites or reports) of another type;
        # a report counts once per pair of types, and links to its own agency are left out
        flows = [dict(r) for r in con.execute(
            f"""SELECT s.type src, t.type dst, COUNT(DISTINCT l.doc_id) reports
                {base.replace("FROM doc_links l", f"FROM doc_links l JOIN sources t ON t.id={CITED}", 1)} AND t.id != s.id
                GROUP BY s.type, t.type ORDER BY reports DESC""", args)]
        for f in flows:
            f["link"] = f"/documents?type={f['src']}&cite=stype:{f['dst']}&indexed=1"
        n_reports = con.execute(f"SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id JOIN doc_index i ON i.doc_id=d.id WHERE {where}", args).fetchone()[0]
    return {"cited_sources": cited_sources, "hosts": hosts, "cited_docs": cited_docs, "totals": totals, "n_reports": n_reports,
            "flows": flows}


@db.cached
def of_doc(doc_id: int) -> dict:
    """What a report links to, and which library reports link to it."""
    with db.session() as con:
        init()
        mine = [dict(r) for r in con.execute(
            """SELECT l.host, l.url, l.raw, l.n, l.target_doc, l.target_source FROM doc_links l WHERE l.doc_id=?
               ORDER BY l.n DESC, l.host""", (doc_id,))]
        cited = [dict(r) for r in con.execute(
            """SELECT l.target_doc id, d.title, d.year, s.agency FROM doc_links l JOIN documents d ON d.id=l.target_doc
               JOIN sources s ON s.id=d.source_id WHERE l.doc_id=? AND l.target_doc IS NOT NULL ORDER BY d.year DESC""", (doc_id,))]
        by = [dict(r) for r in con.execute(
            """SELECT l.doc_id id, d.title, d.year, s.agency FROM doc_links l JOIN documents d ON d.id=l.doc_id
               JOIN sources s ON s.id=d.source_id WHERE l.target_doc=? ORDER BY d.year DESC""", (doc_id,))]
        agencies = [dict(r) for r in con.execute(
            """SELECT l.target_source id, t.agency, COUNT(*) links FROM doc_links l JOIN sources t ON t.id=l.target_source
               WHERE l.doc_id=? AND l.target_doc IS NULL GROUP BY l.target_source ORDER BY links DESC""", (doc_id,))]
    hosts: dict[str, int] = {}
    for m in mine:
        if not m["target_doc"] and not m["target_source"]:
            hosts[m["host"]] = hosts.get(m["host"], 0) + 1
    return {"links": len(mine), "cited": cited, "cited_by": by, "agencies": agencies,
            "hosts": sorted(hosts.items(), key=lambda kv: (-kv[1], kv[0]))[:8], "n_hosts": len(hosts)}


def clause(cite: str) -> tuple[str, list] | None:
    """Documents-page filter `cite=`: doc:ID reports citing report ID · by:ID reports cited by ID · src:ID reports linking to
    source ID's site · host:HOST reports linking to that outside host · stype:TYPE reports linking to an agency of that type
    (its site or one of its reports in the library), not their own."""
    kind, _, val = (cite or "").partition(":")
    if kind == "doc" and val.isdigit():
        return "d.id IN (SELECT doc_id FROM doc_links WHERE target_doc=?)", [int(val)]
    if kind == "by" and val.isdigit():
        return "d.id IN (SELECT target_doc FROM doc_links WHERE doc_id=? AND target_doc IS NOT NULL)", [int(val)]
    if kind == "src" and val.isdigit():
        return "d.id IN (SELECT doc_id FROM doc_links WHERE target_source=?)", [int(val)]
    if kind == "stype" and re.fullmatch(r"[a-z-]+", val):
        return (f"""d.id IN (SELECT l.doc_id FROM doc_links l JOIN documents dd ON dd.id=l.doc_id JOIN sources t ON t.id={CITED}
                    WHERE t.type=? AND t.id != dd.source_id)""", [val])
    if kind == "host" and val:
        return "d.id IN (SELECT doc_id FROM doc_links WHERE host=? AND target_source IS NULL AND target_doc IS NULL)", [val.lower()]
    return None
