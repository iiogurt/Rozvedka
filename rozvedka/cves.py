"""CVE numbers named in the reports, tied to CISA's Known Exploited Vulnerabilities (KEV) catalog.

  - `index` finds every CVE-YYYY-NNNN in the report texts (all spellings of the hyphens), with the places in the text, and the
    actors named within WINDOW characters of one (the same passage – a proximity, not a claim that the actor used it).
  - `fetch_kev` downloads CISA's catalog (CC0 1.0; https://www.cisa.gov/known-exploited-vulnerabilities-catalog) into
    data/gazetteer/kev.json with its version and the retrieval date; the portal shows for each CVE whether it is on the list,
    when it was added, and whether ransomware use is known. The catalog says what is exploited, never who exploits it.
Nothing here calls out: the portal reads the stored file."""
import datetime as dt
import json
import logging
import re
from functools import lru_cache

from . import actors, db, fetch, paging, topics, trends
from .config import DATA

log = logging.getLogger(__name__)
KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
KEV_PAGE = "https://www.cisa.gov/known-exploited-vulnerabilities-catalog"
KEV_LICENSE = "https://www.cisa.gov/sites/default/files/licenses/kev/license.txt"
KEV_FILE = DATA / "gazetteer" / "kev.json"
KEEP = ("vendorProject", "product", "vulnerabilityName", "dateAdded", "shortDescription", "dueDate",
        "knownRansomwareCampaignUse", "cwes")
HY = "-‐‑‒–−"          # the hyphens PDF text uses
PATTERN = re.compile(rf"\bCVE[{HY}](\d{{4}})[{HY}](\d{{4,7}})\b", re.I)
SPANS = 20                                      # places kept per report and CVE

SCHEMA = """
CREATE TABLE IF NOT EXISTS doc_cves (doc_id INTEGER NOT NULL, cve TEXT NOT NULL, n INTEGER, spans TEXT, PRIMARY KEY (doc_id, cve));
CREATE INDEX IF NOT EXISTS ix_doc_cves_cve ON doc_cves(cve);
CREATE TABLE IF NOT EXISTS actor_cves (actor_key TEXT NOT NULL, cve TEXT NOT NULL, doc_id INTEGER NOT NULL,
                                       PRIMARY KEY (actor_key, cve, doc_id));
CREATE INDEX IF NOT EXISTS ix_actor_cves_cve ON actor_cves(cve);
"""


def init() -> None:
    with db.session() as con:
        con.executescript(SCHEMA)


def find(text: str) -> dict[str, list[list[int]]]:
    """{CVE-YYYY-NNNN: [[start, end], …]} in a text."""
    out: dict[str, list] = {}
    this_year = dt.date.today().year
    for m in PATTERN.finditer(text or ""):
        y = int(m.group(1))
        if 1999 <= y <= this_year + 1:
            out.setdefault(f"CVE-{y}-{m.group(2)}", []).append([m.start(), m.end()])
    return out


def index() -> dict:
    """Rebuild doc_cves and actor_cves from the stored texts and the actor index (a few seconds)."""
    init()
    actors.init()
    rows, per_doc = [], {}
    with db.session() as con:
        for doc_id, body in con.execute("SELECT rowid, body FROM doc_text"):
            found = find(body)
            if found:
                per_doc[doc_id] = found
                rows += [(doc_id, c, len(sp), json.dumps(sp[:SPANS])) for c, sp in found.items()]
        con.execute("DELETE FROM doc_cves")
        con.executemany("INSERT INTO doc_cves VALUES (?,?,?,?)", rows)
        pairs = set()
        for doc_id, found in per_doc.items():
            for r in con.execute("""SELECT da.actor_key, da.spans FROM doc_actors da JOIN actors a ON a.key=da.actor_key
                                    WHERE da.doc_id=? AND a.kind != 'country'""", (doc_id,)):
                spans = json.loads(r["spans"] or "[]")
                for cve, cs in found.items():
                    if any(abs(s - c0) <= actors.WINDOW for s, _ in spans for c0, _ in cs):
                        pairs.add((r["actor_key"], cve, doc_id))
        con.execute("DELETE FROM actor_cves")
        con.executemany("INSERT INTO actor_cves VALUES (?,?,?)", sorted(pairs))
    return {"reports": len(per_doc), "cves": len({c for f in per_doc.values() for c in f}), "mentions": len(rows),
            "actor_links": len(pairs)}


# ── the KEV catalog ──
def fetch_kev() -> dict:
    r = fetch.get(KEV_URL)
    if r.status != 200:
        return {"error": f"HTTP {r.status}"}
    d = json.loads(r.text)
    vulns = {v["cveID"]: {k: v.get(k) for k in KEEP} for v in d["vulnerabilities"]}
    KEV_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEV_FILE.write_text(json.dumps({
        "meta": {"title": d.get("title"), "version": d.get("catalogVersion"), "released": d.get("dateReleased"),
                 "retrieved": dt.date.today().isoformat(), "url": KEV_URL, "page": KEV_PAGE,
                 "license": "CC0 1.0", "license_url": KEV_LICENSE},
        "vulns": vulns}), encoding="utf-8")
    _kev.cache_clear()
    return {"entries": len(vulns), "version": d.get("catalogVersion")}


@lru_cache(maxsize=1)
def _kev_cached(mtime: float) -> dict:
    return json.loads(KEV_FILE.read_text(encoding="utf-8"))


def _kev() -> dict:
    return _kev_cached(KEV_FILE.stat().st_mtime) if KEV_FILE.exists() else {"meta": None, "vulns": {}}


_kev.cache_clear = _kev_cached.cache_clear


def kev_meta() -> dict | None:
    return _kev()["meta"]


def kev_of(cve: str) -> dict | None:
    return _kev()["vulns"].get(cve)


def kev_ids() -> list[str]:
    return sorted(_kev()["vulns"])


# ── queries for the portal ──
def _kev_view(cve: str) -> dict:
    k = kev_of(cve)
    return {"on_kev": bool(k), "kev": k}


@db.cached
def _counts() -> list[dict]:
    """Every CVE named in reports in scope: reports, agencies, countries, years."""
    where, args, _ = trends.scope()
    with db.session() as con:
        init()
        return [dict(r) for r in con.execute(
            f"""SELECT c.cve, COUNT(DISTINCT c.doc_id) docs, COUNT(DISTINCT d.source_id) agencies,
                       COUNT(DISTINCT s.country) countries, MIN(d.year) y0, MAX(d.year) y1
                FROM doc_cves c JOIN documents d ON d.id=c.doc_id JOIN sources s ON s.id=d.source_id
                JOIN doc_index i ON i.doc_id=d.id WHERE {where} GROUP BY c.cve""", args)]


def overview(kev: str = "", q: str = "", ransomware: int = 0, sort: str = "reports") -> dict:
    rows = [{**r, **_kev_view(r["cve"])} for r in _counts()]
    total = len(rows)
    if kev == "yes":
        rows = [r for r in rows if r["on_kev"]]
    elif kev == "no":
        rows = [r for r in rows if not r["on_kev"]]
    if ransomware:
        rows = [r for r in rows if r["on_kev"] and r["kev"]["knownRansomwareCampaignUse"] == "Known"]
    if q.strip():
        n = q.strip().lower()
        rows = [r for r in rows if n in r["cve"].lower() or (r["kev"] and n in " ".join(
            str(r["kev"][k] or "") for k in ("vendorProject", "product", "vulnerabilityName")).lower())]
    keys = {"reports": lambda r: (-r["docs"], r["cve"]), "agencies": lambda r: (-r["agencies"], r["cve"]),
            "cve": lambda r: r["cve"], "added": lambda r: ("" if not r["on_kev"] else r["kev"]["dateAdded"], r["cve"])}
    rows.sort(key=keys.get(sort, keys["reports"]), reverse=sort in ("added", "cve"))
    return {"rows": rows, "total": total, "n_kev": sum(1 for r in _counts() if kev_of(r["cve"])), "meta": kev_meta()}


def detail(cve: str, size: int = 25, page: int | str = 1) -> dict | None:
    cve = cve.upper()
    where, args, _ = trends.scope()
    with db.session() as con:
        init()
        docs = [dict(r) for r in con.execute(
            f"""SELECT c.doc_id, c.n, c.spans, d.title, d.year, d.lang, d.local_path, d.url, s.id source_id, s.agency, s.country,
                       i.pages FROM doc_cves c JOIN documents d ON d.id=c.doc_id JOIN sources s ON s.id=d.source_id
                JOIN doc_index i ON i.doc_id=d.id WHERE c.cve=? AND {where}
                ORDER BY d.year DESC NULLS LAST, c.n DESC""", (cve, *args))]
        if not docs and not kev_of(cve):
            return None
        acts = [dict(r) for r in con.execute(
            f"""SELECT a.key, a.label, a.kind, COUNT(DISTINCT ac.doc_id) docs FROM actor_cves ac JOIN actors a ON a.key=ac.actor_key
                JOIN documents d ON d.id=ac.doc_id JOIN sources s ON s.id=d.source_id JOIN doc_index i ON i.doc_id=d.id
                WHERE ac.cve=? AND {where} AND {actors.NOT_BEFORE_FOUNDED}
                GROUP BY a.key ORDER BY docs DESC, a.label LIMIT 25""", (cve, *args))]
        pg = paging.paginate(len(docs), page, size, f"/cves/{cve}", {"per_page": size if size != 25 else ""},
                             anchor="#reports", default=25)
        shown = []
        for d in docs[pg["offset"]:pg["offset"] + size]:
            body = (con.execute("SELECT body FROM doc_text WHERE rowid=?", (d["doc_id"],)).fetchone() or [""])[0] or ""
            s, e = json.loads(d["spans"])[0]
            pages = json.loads(d["pages"]) if d["pages"] else None
            p = topics.page_of(pages, s)
            shown.append({**{k: d[k] for k in ("doc_id", "n", "title", "year", "lang", "agency", "country", "source_id")},
                          **actors._snippet(body, s, e), "page": p,
                          "open": f"/doc/{d['doc_id']}" + (f"#page={p}" if p else "") if d["local_path"] else d["url"]})
    return {"cve": cve, **_kev_view(cve), "reports": len(docs), "agencies": len({d["source_id"] for d in docs}),
            "years": sorted({d["year"] for d in docs if d["year"]}), "shown": shown, "pg": pg, "actors": acts,
            "meta": kev_meta()}


def of_actor(key: str, limit: int = 25) -> list[dict]:
    """CVEs named within one passage of the actor: reports counted with the same rules as the actor page."""
    where, args, _ = trends.scope()
    with db.session() as con:
        init()
        rows = [dict(r) for r in con.execute(
            f"""SELECT ac.cve, COUNT(DISTINCT ac.doc_id) docs FROM actor_cves ac JOIN actors a ON a.key=ac.actor_key
                JOIN documents d ON d.id=ac.doc_id JOIN sources s ON s.id=d.source_id JOIN doc_index i ON i.doc_id=d.id
                WHERE ac.actor_key=? AND {where} AND {actors.NOT_BEFORE_FOUNDED} GROUP BY ac.cve""", (key, *args))]
    rows = [{**r, **_kev_view(r["cve"])} for r in rows]
    rows.sort(key=lambda r: (-r["docs"], not r["on_kev"], r["cve"]))
    return rows[:limit]


def of_doc(doc_id: int) -> list[dict]:
    with db.session() as con:
        init()
        rows = [dict(r) for r in con.execute("SELECT cve, n FROM doc_cves WHERE doc_id=? ORDER BY n DESC, cve", (doc_id,))]
    return [{**r, **_kev_view(r["cve"])} for r in rows]
