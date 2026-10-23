"""MITRE ATT&CK technique numbers (T1566, T1059.001 …) named in the reports, tied to MITRE's technique list.

  - `index` finds every technique number in the report texts, with the places in the text.
  - `fetch` downloads the Enterprise, Mobile and ICS ATT&CK catalogs (STIX 2.1, github.com/mitre-attack/attack-stix-data) into
    data/gazetteer/attack_techniques.json: for each technique its name, tactics, address, whether MITRE has retired it, and the
    groups MITRE lists as using it, with the catalog versions and the retrieval date; also the software (malware and tools)
    and campaigns, and which group uses which software and which campaign MITRE attributes to which group (for the
    connection graph, rozvedka/ties.py). MITRE's terms permit this use with the copyright notice shown on the pages.
    Once the catalog is stored, only numbers that are in it count (a pattern like "T1234" can also be a part number).
Nothing here calls out except `fetch`: the portal reads the stored file."""
import datetime as dt
import json
import logging
import re
from functools import lru_cache

from . import actor_sources, actors, db, paging, topics, trends
from .config import DATA

log = logging.getLogger(__name__)
FILE = DATA / "gazetteer" / "attack_techniques.json"
ATTACK_BASE = "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/{0}/{0}.json"
MATRICES = ("enterprise-attack", "mobile-attack", "ics-attack")
PAGE = "https://attack.mitre.org/"
TERMS = "https://attack.mitre.org/resources/legal-and-branding/terms-of-use/"
PATTERN = re.compile(r"(?<![\w.])T(1\d{3})(?:\.(\d{3}))?(?!\w)")
SPANS = 20                                      # places kept per report and technique

SCHEMA = """
CREATE TABLE IF NOT EXISTS doc_techniques (doc_id INTEGER NOT NULL, technique TEXT NOT NULL, n INTEGER, spans TEXT,
                                           PRIMARY KEY (doc_id, technique));
CREATE INDEX IF NOT EXISTS ix_doc_techniques_t ON doc_techniques(technique);
"""


def init() -> None:
    with db.session() as con:
        con.executescript(SCHEMA)


def find(text: str) -> dict[str, list[list[int]]]:
    """{T1566.001: [[start, end], …]} in a text."""
    out: dict[str, list] = {}
    for m in PATTERN.finditer(text or ""):
        out.setdefault(f"T{m.group(1)}" + (f".{m.group(2)}" if m.group(2) else ""), []).append([m.start(), m.end()])
    return out


def index() -> dict:
    """Rebuild doc_techniques from the stored texts (a few seconds)."""
    init()
    rows, docs = [], set()
    with db.session() as con:
        for doc_id, body in con.execute("SELECT rowid, body FROM doc_text"):
            for t, sp in find(body).items():
                docs.add(doc_id)
                rows.append((doc_id, t, len(sp), json.dumps(sp[:SPANS])))
        con.execute("DELETE FROM doc_techniques")
        con.executemany("INSERT INTO doc_techniques VALUES (?,?,?,?)", rows)
    return {"reports": len(docs), "techniques": len({r[1] for r in rows}), "mentions": len(rows)}


# ── MITRE's catalog ──
def _clean(text: str, limit: int = 400) -> str:
    """MITRE's relationship text without its citation markers, shortened: "[APT28](…) has used X.(Citation: …)" → "APT28 has used X." """
    text = re.sub(r"\(Citation:[^)]*\)", "", text or "")
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def fetch() -> dict:
    out, versions = {}, {}
    software, campaigns, relations, allgroups = {}, {}, [], {}
    for matrix in MATRICES:          # Enterprise first: its entry wins where a number is in two matrices
        bundle = actor_sources._get(ATTACK_BASE.format(matrix), timeout=600)
        objs = bundle["objects"]
        versions[matrix] = next((o.get("x_mitre_version") for o in objs if o["type"] == "x-mitre-collection"), None)

        def live(o):
            return not (o.get("revoked") or o.get("x_mitre_deprecated"))

        def mitre_ref(o):
            return next((r for r in o.get("external_references", []) if r.get("source_name") == "mitre-attack"), None)

        groups = {o["id"]: [mitre_ref(o)["external_id"], o["name"]] for o in objs
                  if o["type"] == "intrusion-set" and live(o) and mitre_ref(o)}
        # retired techniques stay: reports still cite their numbers
        techs = {o["id"]: {"id": mitre_ref(o)["external_id"], "name": o["name"], "url": mitre_ref(o)["url"], "groups": [],
                           "matrix": matrix, "retired": not live(o),
                           "tactics": [p["phase_name"] for p in o.get("kill_chain_phases", [])
                                       if p.get("kill_chain_name", "").startswith("mitre-")]}
                 for o in objs if o["type"] == "attack-pattern" and mitre_ref(o)}
        for o in objs:
            if o["type"] == "relationship" and o.get("relationship_type") == "uses" and live(o) \
                    and o["source_ref"] in groups and o["target_ref"] in techs:
                techs[o["target_ref"]]["groups"].append(groups[o["source_ref"]])
        for t in techs.values():
            out.setdefault(t["id"], {**t, "groups": sorted(t["groups"])})
        soft = {o["id"]: {"id": mitre_ref(o)["external_id"], "name": o["name"], "type": o["type"], "url": mitre_ref(o)["url"],
                          "aliases": [a for a in o.get("x_mitre_aliases", []) if a != o["name"]][:10]}
                for o in objs if o["type"] in ("malware", "tool") and live(o) and mitre_ref(o)}
        camps = {o["id"]: {"id": mitre_ref(o)["external_id"], "name": o["name"], "url": mitre_ref(o)["url"],
                           "first": (o.get("first_seen") or "")[:10], "last": (o.get("last_seen") or "")[:10]}
                 for o in objs if o["type"] == "campaign" and live(o) and mitre_ref(o)}
        allgroups.update({g[0]: g[1] for g in groups.values()})
        for v in soft.values():
            software.setdefault(v["id"], v)
        for v in camps.values():
            campaigns.setdefault(v["id"], v)
        ids = {k: v["id"] for k, v in {**soft, **camps}.items()} | {k: g[0] for k, g in groups.items()}
        for o in objs:
            if o["type"] != "relationship" or not live(o) or o["source_ref"] not in ids or o["target_ref"] not in ids:
                continue
            rel, src, dst = o.get("relationship_type"), o["source_ref"], o["target_ref"]
            if (rel == "uses" and src.split("--")[0] in ("intrusion-set", "campaign") and dst.split("--")[0] in ("malware", "tool")) \
                    or (rel == "attributed-to" and src.startswith("campaign--") and dst.startswith("intrusion-set--")):
                relations.append([ids[src], rel, ids[dst], _clean(o.get("description", ""))])
    for t in out.values():          # a sub-technique is shown after its parent
        if "." in t["id"] and t["id"].split(".")[0] in out:
            t["parent"] = out[t["id"].split(".")[0]]["name"]
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({"meta": {"versions": versions, "retrieved": dt.date.today().isoformat(),
                                         "url": ATTACK_BASE, "page": PAGE, "terms": TERMS},
                                "techniques": out, "software": software, "campaigns": campaigns,
                                "groups": allgroups,
                                "relations": sorted({tuple(r) for r in relations})}), encoding="utf-8")
    _stored.cache_clear()
    return {"techniques": len(out), "retired": sum(1 for t in out.values() if t["retired"]), "software": len(software),
            "campaigns": len(campaigns), "relations": len(relations), "versions": versions}


@lru_cache(maxsize=1)
def _stored(mtime: float) -> dict:
    return json.loads(FILE.read_text(encoding="utf-8"))


def _catalog() -> dict:
    return _stored(FILE.stat().st_mtime) if FILE.exists() else {"meta": None, "techniques": {}}


def meta() -> dict | None:
    return _catalog()["meta"]


def known(t: str) -> dict | None:
    return _catalog()["techniques"].get(t)


def _view(t: str) -> dict:
    k = known(t)
    return {"technique": t, "info": k, "title": (f"{k['parent']}: {k['name']}" if k.get("parent") else k["name"]) if k else ""}


def _only_known(rows: list[dict]) -> list[dict]:
    return [r for r in rows if known(r["technique"])] if meta() else rows


# ── queries for the portal ──
@db.cached
def _counts() -> list[dict]:
    where, args, _ = trends.scope()
    with db.session() as con:
        init()
        return [dict(r) for r in con.execute(
            f"""SELECT t.technique, COUNT(DISTINCT t.doc_id) docs, COUNT(DISTINCT d.source_id) agencies,
                       COUNT(DISTINCT s.country) countries, MIN(d.year) y0, MAX(d.year) y1
                FROM doc_techniques t JOIN documents d ON d.id=t.doc_id JOIN sources s ON s.id=d.source_id
                JOIN doc_index i ON i.doc_id=d.id WHERE {where} GROUP BY t.technique""", args)]


# ATT&CK's tactics in the order of its matrices (Enterprise kill chain first, then what only ICS or Mobile has)
TACTIC_ORDER = ("reconnaissance", "resource-development", "initial-access", "execution", "persistence", "privilege-escalation",
                "stealth", "defense-evasion", "defense-impairment", "credential-access", "discovery", "lateral-movement",
                "collection", "command-and-control", "exfiltration", "impact", "evasion", "inhibit-response-function",
                "impair-process-control", "network-effects", "remote-service-effects")
GRID_ROWS = 12          # techniques listed per tactic; the rest behind "more"


def tactic_name(t: str) -> str:
    return t.replace("-", " ").replace("command and control", "command & control").capitalize()


def of_tactic(tactic: str) -> list[str]:
    """Every technique number of the catalog under this tactic."""
    return sorted(k for k, v in _catalog()["techniques"].items() if tactic in v["tactics"])


@db.cached
def grid() -> dict:
    """The ATT&CK matrix as the reports name it: a column per tactic (ATT&CK's order), its techniques ranked by reports.
    A column's total counts the reports naming any technique of the tactic, once each; a technique under several tactics
    is listed under each."""
    if not meta():
        return {"cols": [], "reports": 0}
    where, args, _ = trends.scope()
    with db.session() as con:
        init()
        pairs = [(r[0], r[1]) for r in con.execute(
            f"""SELECT t.doc_id, t.technique FROM doc_techniques t JOIN documents d ON d.id=t.doc_id
                JOIN sources s ON s.id=d.source_id JOIN doc_index i ON i.doc_id=d.id WHERE {where}""", args)]
    by_t: dict[str, set] = {}
    for doc, t in pairs:
        if known(t):
            by_t.setdefault(t, set()).add(doc)
    cols = {}
    for t, docs in by_t.items():
        for tac in known(t)["tactics"]:
            c = cols.setdefault(tac, {"tactic": tac, "name": tactic_name(tac), "docs": set(), "techniques": []})
            c["docs"] |= docs
            c["techniques"].append({**_view(t), "docs": len(docs), "link": f"/documents?technique={t}&indexed=1"})
    order = {t: i for i, t in enumerate(TACTIC_ORDER)}
    out = []
    for c in sorted(cols.values(), key=lambda c: (order.get(c["tactic"], 99), c["tactic"])):
        c["techniques"].sort(key=lambda x: (-x["docs"], x["technique"]))
        out.append({"tactic": c["tactic"], "name": c["name"], "reports": len(c["docs"]), "named": len(c["techniques"]),
                    "in_catalog": len(of_tactic(c["tactic"])), "link": f"/documents?technique=tactic:{c['tactic']}&indexed=1",
                    "techniques": c["techniques"][:GRID_ROWS], "more": len(c["techniques"]) - GRID_ROWS,
                    "list": f"/techniques?tactic={c['tactic']}"})
    top = max((x["docs"] for c in out for x in c["techniques"]), default=1)
    return {"cols": out, "reports": len({d for docs in by_t.values() for d in docs}), "top": top, "rows": GRID_ROWS}


def figures() -> list[tuple[str, int, str]]:
    """(label, number, Documents link) of every number of the tactic grid, for tools/check_links.py."""
    g = grid()
    return [(f"tactic {c['tactic']}", c["reports"], c["link"]) for c in g["cols"]] + \
           [(f"technique {x['technique']}", x["docs"], x["link"]) for c in g["cols"] for x in c["techniques"]]


def overview(q: str = "", tactic: str = "", sort: str = "reports") -> dict:
    allrows = [{**r, **_view(r["technique"])} for r in _only_known(_counts())]
    tactics = sorted({x for r in allrows if r["info"] for x in r["info"]["tactics"]})
    rows = allrows
    if tactic:
        rows = [r for r in rows if r["info"] and tactic in r["info"]["tactics"]]
    if q.strip():
        n = q.strip().lower()
        rows = [r for r in rows if n in r["technique"].lower() or n in r["title"].lower()]
    keys = {"reports": lambda r: (-r["docs"], r["technique"]), "agencies": lambda r: (-r["agencies"], r["technique"]),
            "id": lambda r: r["technique"], "name": lambda r: (r["title"].lower(), r["technique"])}
    rows.sort(key=keys.get(sort, keys["reports"]))
    return {"rows": rows, "total": len(allrows), "tactics": tactics, "meta": meta(),
            "unknown": len(_counts()) - len(allrows) if meta() else 0}


def detail(t: str, size: int = 25, page: int | str = 1) -> dict | None:
    t = t.upper()
    if meta() and not known(t):
        return None                                  # not a technique of the catalog
    where, args, _ = trends.scope()
    with db.session() as con:
        init()
        docs = [dict(r) for r in con.execute(
            f"""SELECT c.doc_id, c.n, c.spans, d.title, d.year, d.lang, d.local_path, d.url, s.id source_id, s.agency, s.country,
                       i.pages FROM doc_techniques c JOIN documents d ON d.id=c.doc_id JOIN sources s ON s.id=d.source_id
                JOIN doc_index i ON i.doc_id=d.id WHERE c.technique=? AND {where}
                ORDER BY d.year DESC NULLS LAST, c.n DESC""", (t, *args))]
        if not docs and not known(t):
            return None
        info = known(t)
        groups = []
        for g_id, name in (info["groups"] if info else []):
            r = con.execute("SELECT key, label FROM actors WHERE json_extract(data, '$.attack.id')=?", (g_id,)).fetchone()
            groups.append({"id": g_id, "name": name, "actor": dict(r) if r else None})
        pg = paging.paginate(len(docs), page, size, f"/techniques/{t}", {"per_page": size if size != 25 else ""},
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
    return {**_view(t), "reports": len(docs), "agencies": len({d["source_id"] for d in docs}),
            "years": sorted({d["year"] for d in docs if d["year"]}), "shown": shown, "pg": pg, "meta": meta(),
            "groups": groups}


def of_doc(doc_id: int) -> list[dict]:
    with db.session() as con:
        init()
        rows = [dict(r) for r in con.execute(
            "SELECT technique, n FROM doc_techniques WHERE doc_id=? ORDER BY n DESC, technique", (doc_id,))]
    return [{**r, **_view(r["technique"])} for r in _only_known(rows)]
