"""ICIJ Offshore Leaks: offshore companies and the people behind them, from leaked records – journalistic, not official.

The International Consortium of Investigative Journalists publishes the entities, officers, intermediaries and their links
from the Offshore Leaks, Panama, Bahamas, Paradise and Pandora Papers (database ODbL, contents CC BY-SA; cite ICIJ). The
records are leaked documents of offshore service providers, cleaned by journalists: not an official register, often years
old ("current through 2015"), and a name in them is no evidence of wrongdoing. They are kept only for what the sanctions
lists already name, and every link from them is marked as coming from leaked records (layer "icij", group "leaks").

A list entry is the ICIJ record with the same name (sanctions.normalise) in the same country:
- companies – a distinctive name (gleif.distinctive) and only records in that country carry it (the same company can be
  in several leaks);
- people – a name of two words and 12 letters or more that at most three ICIJ records carry, all in the entry's country:
  "Zhang Wei" or "Yang Fan" are names of thousands; a match is still only the same name and country, shown as such.
Then one step out: the companies they are officers, shareholders or beneficial owners of, the people and companies that
are officers of them, and their intermediaries (registered addresses and ICIJ's own "same name as" guesses left out).

    python -m rozvedka fetch-icij         # download (~72 MB), match, keep (a few minutes), then build-graph
"""
import csv
import datetime as dt
import io
import json
import logging
import zipfile
from functools import lru_cache

from . import fetch, gleif, sanctions
from .config import DATA

log = logging.getLogger("rozvedka.icij")
DIR = DATA / "icij"
ZIP = DIR / "full-oldb.zip"
FILE = DIR / "icij.json"
URL = "https://offshoreleaks-data.icij.org/offshoreleaks/csv/full-oldb.LATEST.zip"
NODE = "https://offshoreleaks.icij.org/nodes/{}"
ABOUT = "https://offshoreleaks.icij.org/pages/database"
LICENCE = "ODbL 1.0 (database), CC BY-SA (contents) – © ICIJ"
NODE_FILES = {"entity": "nodes-entities.csv", "officer": "nodes-officers.csv", "intermediary": "nodes-intermediaries.csv"}
RELS = {"officer_of", "intermediary_of"}
MAX_PEOPLE = 3          # ICIJ records carrying a person's name at most
MIN_PERSON = 12         # letters of a person's name at least


@lru_cache(maxsize=1)
def _iso3() -> dict[str, str]:
    from . import ratings
    s = ratings.load()
    return {v: k for k, v in (s.get("iso2to3_all") or s.get("iso2to3") or {}).items()}


def countries(codes: str) -> set[str]:
    """ICIJ's "RUS;CYP" → {"RU", "CY"}."""
    return {_iso3().get(c.strip(), "") for c in (codes or "").split(";") if c.strip()} - {""}


def list_names() -> tuple[dict, dict, dict]:
    """The list entries' usable names: people's and companies' normalised names → entry keys, and each entry's countries."""
    people: dict[str, set] = {}
    orgs: dict[str, set] = {}
    where: dict[str, set] = {}
    for lst, spec in sanctions.LISTS.items():
        path = sanctions.DIR / spec["file"]
        if not path.exists():
            continue
        for e in sanctions._entries(path, lst):
            d, key = e["details"], f"{lst}:{e['ref']}"
            where[key] = ({gleif.country(a["country"]) for a in d["addresses"] if a}
                          | {gleif.country(c) for _k, _v, c in d["ids"] if c}) - {""}
            for nm in e["names"]:
                n = sanctions.normalise(nm)
                if e["type"] == "person":
                    if len(n.split()) >= 2 and len(n.replace(" ", "")) >= MIN_PERSON:
                        people.setdefault(n, set()).add(key)
                elif gleif.distinctive(nm):
                    orgs.setdefault(n, set()).add(key)
    return people, orgs, where


def _rows(z, name):
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", newline=""))


def _node(r: dict, kind: str) -> dict:
    return {"name": r["name"], "kind": kind, "countries": sorted(countries(r.get("country_codes"))),
            "jurisdiction": r.get("jurisdiction_description") or "", "source": r.get("sourceID") or "",
            "valid": r.get("valid_until") or "", "incorporated": r.get("incorporation_date") or "",
            "status": r.get("status") or ""}


def match(people: dict, orgs: dict, where: dict, nodes: dict[str, dict]) -> dict[str, dict]:
    """List entry → {"nodes": [ICIJ ids], "how": "company" | "person"} by the rules above. `nodes`: the ICIJ records whose
    normalised name is one of the list names (all of them, to count how many carry each name)."""
    by_name: dict[str, list] = {}
    for nid, n in nodes.items():
        by_name.setdefault(sanctions.normalise(n["name"]), []).append(nid)
    out: dict[str, dict] = {}
    for name, ids in by_name.items():
        here = [nodes[i] for i in ids]
        for key in orgs.get(name, ()):
            cs = where.get(key, set())
            if cs and all(set(n["countries"]) & cs for n in here):
                out.setdefault(key, {"nodes": [], "how": "company"})["nodes"] += ids
        if len(ids) <= MAX_PEOPLE:
            for key in people.get(name, ()):
                cs = where.get(key, set())
                if cs and all(set(n["countries"]) & cs for n in here):
                    out.setdefault(key, {"nodes": [], "how": "person"})["nodes"] += ids
    for m in out.values():
        m["nodes"] = sorted(set(m["nodes"]))
    return out


def fetch_all(download: bool = True) -> dict:
    DIR.mkdir(parents=True, exist_ok=True)
    if download or not ZIP.exists():
        log.info("ICIJ: downloading %s", URL)
        fetch.download(URL, ZIP, max_bytes=500 * 2**20)
    z = zipfile.ZipFile(ZIP)
    stamp = next((n for n in z.namelist() if n.startswith("GENERATED_ON_")), "")[13:21]
    people, orgs, where = list_names()
    wanted = set(people) | set(orgs)
    cands: dict[str, dict] = {}
    for kind, name in NODE_FILES.items():               # pass 1: every record carrying a list name
        for r in _rows(z, name):
            if sanctions.normalise(r["name"]) in wanted:
                cands[r["node_id"]] = _node(r, kind)
    matches = match(people, orgs, where, cands)
    mine = {i for m in matches.values() for i in m["nodes"]}
    edges = []
    for r in _rows(z, "relationships.csv"):            # one step out from the matched records
        if r["rel_type"] in RELS and (r["node_id_start"] in mine or r["node_id_end"] in mine):
            edges.append({"a": r["node_id_start"], "b": r["node_id_end"], "rel": r["link"] or r["rel_type"].replace("_", " "),
                          "start": r.get("start_date") or "", "end": r.get("end_date") or "", "source": r.get("sourceID") or ""})
    need = {x for e in edges for x in (e["a"], e["b"])} - set(cands)
    nodes = {i: cands[i] for i in mine}
    if need:
        for kind, name in NODE_FILES.items():           # pass 2: the records one step out
            for r in _rows(z, name):
                if r["node_id"] in need:
                    nodes[r["node_id"]] = _node(r, kind)
    for e in edges:
        for x in (e["a"], e["b"]):
            if x in cands:
                nodes.setdefault(x, cands[x])
    meta = {"retrieved": dt.date.today().isoformat(), "generated": stamp, "licence": LICENCE, "source": ABOUT}
    FILE.write_text(json.dumps({"meta": meta, "matches": matches, "nodes": nodes, "edges": edges}, ensure_ascii=False),
                    encoding="utf-8")
    stored.cache_clear()
    return {"matched": len(matches), "by": {h: sum(1 for m in matches.values() if m["how"] == h) for h in ("company", "person")},
            "records": len(nodes), "links": len(edges)}


@lru_cache(maxsize=1)
def stored() -> dict:
    if not FILE.exists():
        return {"meta": {}, "matches": {}, "nodes": {}, "edges": []}
    return json.loads(FILE.read_text(encoding="utf-8"))


def node_kind(n: dict) -> str:
    """An ICIJ record as a kind of the network: entities and intermediaries are companies; an officer is a person unless
    its name is a company's (a legal form among its words)."""
    if n["kind"] != "officer":
        return "org"
    w = set(sanctions.normalise(n["name"]).split())
    return "org" if w & {"limited", "ltd", "inc", "llc", "sa", "ag", "gmbh", "corp", "corporation", "company", "trust", "foundation",
                         "holdings", "holding", "nominees", "bearer", "plc", "bv", "nv", "srl", "fze", "ltda"} else "person"


# ── reviews of the people matched by name ──
from .config import ROOT  # noqa: E402

REVIEWS = ROOT / "sources" / "icij_reviews.yaml"
REVIEW_HEADER = """# Reviews of people on the sanctions lists matched by name and country to a record of ICIJ's Offshore Leaks (/graph/offshore).
# Only confirmed matches become links in the network: a name and a country can be shared by many people.
# Written by the portal; editable by hand. verdict: confirmed | rejected
"""
VERDICTS = {"confirmed": "Confirmed – the same person", "rejected": "Rejected – a namesake or unclear"}


def reviews(path=None) -> dict[str, dict]:
    import yaml
    path = path or REVIEWS
    if not path.exists():
        return {}
    return {r["entry"]: r for r in (yaml.safe_load(path.read_text(encoding="utf-8")) or []) if isinstance(r, dict) and r.get("entry")}


def record(entry: str, verdict: str, note: str = "", path=None) -> dict:
    import yaml
    if verdict not in VERDICTS:
        return {"error": "unknown verdict"}
    m = stored()["matches"].get(entry)
    if not m or m["how"] != "person":
        return {"error": "not a person matched to ICIJ"}
    path = path or REVIEWS
    rows = {**reviews(path)}
    rows[entry] = {"entry": entry, "records": m["nodes"], "name": stored()["nodes"][m["nodes"][0]]["name"], "verdict": verdict,
                   "note": " ".join(note.split())[:1000], "date": dt.date.today().isoformat()}
    path.write_text(REVIEW_HEADER + yaml.safe_dump(list(rows.values()), allow_unicode=True, sort_keys=False, width=120),
                    encoding="utf-8")
    return {"ok": True}


def accepted() -> dict[str, dict]:
    """The matches that become links: every company, and the people whose match is confirmed."""
    rv = reviews()
    return {k: m for k, m in stored()["matches"].items()
            if m["how"] == "company" or (rv.get(k) or {}).get("verdict") == "confirmed"}
