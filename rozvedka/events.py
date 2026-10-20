"""Events for the timeline (roadmap H1, docs/TIMELINE.md): what happened when, each with its source.

Three sources, kept apart and each linked:
  - Wikidata: events of the classes listed in sources/events.yaml (`classes`) since 2000 that took place in a state of
    the library or name an actor of the gazetteer as participant or perpetrator. Date: point in time (P585), else
    start (P580) and end (P582); country (P17), coordinates (P625), deaths (P1120), participants (P710), perpetrators
    (P8031), and the relations between events that the item states: has cause / has effect (P828/P1542), immediate
    cause (P1478/P1536), follows / followed by (P155/P156), part of (P361). Weight: the number of Wikipedia language
    editions with an article on it (sitelinks).
  - EuRepoC Global Dataset of Cyber Incidents (Zenodo, CC BY-NC 4.0): every incident, with its receiving states, its
    initiator and the attribution; weight: EuRepoC's weighted intensity.
  - UCDP Georeferenced Event Dataset and the monthly Candidate Events (CC BY 4.0): deaths in organised violence per
    country and month, and the single events with at least BIG_EVENT deaths (best estimate) in a state of the library,
    coded as one clear event dated to within a week (not UCDP's monthly or yearly sums of losses); weight: deaths. Candidate events are preliminary and marked so.
Nothing is inferred. An actor is linked only when its Wikidata item, or one of its names, matches the gazetteer
unambiguously (the reason is kept when not); relations are only those Wikidata states; a state is linked as an
initiator only when EuRepoC codes the initiator as a state. `python -m rozvedka fetch-events` stores it all in the
database (tables events, event_actors, event_countries, event_links, event_months, event_meta)."""
import csv
import datetime as dt
import io
import json
import logging
import re
import urllib.request
import zipfile
from pathlib import Path

import yaml

from . import db
from .config import DATA

log = logging.getLogger("rozvedka.events")

ROOT = Path(__file__).resolve().parent.parent
CLASSES = ROOT / "sources" / "events.yaml"
CACHE = DATA / "events"
UA = "Rozvedka/0.x (personal research library; https://github.com/iiogurt/Rozvedka)"
SINCE = 2000
BIG_EVENT = 50                     # UCDP: single events with at least this many deaths (best estimate) are listed

EUREPOC_RECORD = "https://zenodo.org/records/14965395"
EUREPOC_CSV = "https://zenodo.org/api/records/14965395/files/eurepoc_global_dataset_1_3.csv/content"
UCDP_DOWNLOADS = "https://ucdp.uu.se/downloads/"
UCDP_GED = "https://ucdp.uu.se/downloads/ged/ged261-csv.zip"
UCDP_CONFLICT = "https://ucdp.uu.se/conflict/{id}"
VIOLENCE = {"1": "state-based conflict", "2": "non-state conflict", "3": "one-sided violence"}

# Wikidata relations, written as (cause or earlier, relation, effect or later) whichever item states them
RELATIONS = {"P828": ("has cause", "caused"), "P1542": ("has effect", "caused"),
             "P1478": ("has immediate cause", "immediately caused"), "P1536": ("immediate cause of", "immediately caused"),
             "P155": ("follows", "followed by"), "P156": ("followed by", "followed by"), "P361": ("part of", "part of")}
_BACKWARD = {"P828", "P1478", "P155"}       # the stating item is the effect / the later one

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    key TEXT PRIMARY KEY, source TEXT NOT NULL, kind TEXT, label TEXT, description TEXT,
    start TEXT, end TEXT, year INTEGER, lat REAL, lon REAL, deaths INTEGER,
    weight REAL, url TEXT, preliminary INTEGER DEFAULT 0, data TEXT);
CREATE INDEX IF NOT EXISTS ix_events_start ON events(start);
CREATE TABLE IF NOT EXISTS event_countries (event_key TEXT NOT NULL, iso TEXT NOT NULL, PRIMARY KEY (event_key, iso));
CREATE INDEX IF NOT EXISTS ix_event_countries_iso ON event_countries(iso);
CREATE TABLE IF NOT EXISTS event_actors (            -- who took part: matched to the gazetteer or kept as written
    event_key TEXT NOT NULL, role TEXT NOT NULL, name TEXT NOT NULL, qid TEXT, actor_key TEXT, reason TEXT,
    PRIMARY KEY (event_key, role, name));
CREATE INDEX IF NOT EXISTS ix_event_actors_actor ON event_actors(actor_key);
CREATE TABLE IF NOT EXISTS event_links (             -- relations an item states: cause → effect, earlier → later, part → whole
    src TEXT NOT NULL, rel TEXT NOT NULL, dst TEXT NOT NULL, src_label TEXT, dst_label TEXT, stated_by TEXT,
    property TEXT, evidence TEXT, PRIMARY KEY (src, rel, dst));
CREATE TABLE IF NOT EXISTS event_months (            -- UCDP deaths in organised violence per country and month
    iso TEXT NOT NULL, month TEXT NOT NULL, deaths INTEGER, events INTEGER, state INTEGER, nonstate INTEGER,
    onesided INTEGER, preliminary INTEGER DEFAULT 0, PRIMARY KEY (iso, month));
CREATE TABLE IF NOT EXISTS event_names (            -- an event's names (Wikidata label and aliases) and whether reports are searched for them
    event_key TEXT NOT NULL, name TEXT NOT NULL, lang TEXT, status TEXT, reason TEXT, docs INTEGER DEFAULT 0,
    PRIMARY KEY (event_key, name));
CREATE TABLE IF NOT EXISTS event_docs (             -- reports that name the event (one of its used names, in the event's year or later)
    event_key TEXT NOT NULL, doc_id INTEGER NOT NULL, names TEXT, PRIMARY KEY (event_key, doc_id));
CREATE INDEX IF NOT EXISTS ix_event_docs_doc ON event_docs(doc_id);
CREATE TABLE IF NOT EXISTS event_meta (
    source TEXT PRIMARY KEY, name TEXT, retrieved TEXT, url TEXT, data_url TEXT, license TEXT, citation TEXT,
    rows INTEGER, note TEXT);
"""
META = {
    "wikidata": {"name": "Wikidata", "url": "https://www.wikidata.org/", "license": "CC0",
                 "citation": "Wikidata items of the classes in sources/events.yaml"},
    "eurepoc": {"name": "EuRepoC Global Dataset of Cyber Incidents 1.3", "url": EUREPOC_RECORD, "data_url": EUREPOC_CSV,
                "license": "CC BY-NC 4.0",
                "citation": "European Repository of Cyber Incidents (EuRepoC), Global Dataset of Cyber Incidents, version 1.3 (2025)"},
    "ucdp": {"name": "UCDP Georeferenced Event Dataset 26.1 and Candidate Events", "url": UCDP_DOWNLOADS, "data_url": UCDP_GED,
             "license": "CC BY 4.0",
             "citation": "Sundberg & Melander (2013), Introducing the UCDP Georeferenced Event Dataset; Davies et al., "
                         "Organized violence 1989–2025"},
}


def init() -> None:
    with db.session() as con:
        con.executescript(SCHEMA)
        if "evidence" not in {r["name"] for r in con.execute("PRAGMA table_info(event_links)")}:
            con.execute("ALTER TABLE event_links ADD COLUMN evidence TEXT")
    sync_hand()


# ── hand-written relations (sources/events.yaml `relations`), for chains the sources do not state ──
HAND_RELS = {"caused", "immediately caused", "followed by", "part of", "response to"}
_hand = {"mtime": None}


def hand_relations(path: Path | None = None) -> list[dict]:
    """[{from, rel, to, evidence, note?}] – each with the evidence URL that states it; the others are ignored."""
    rows = (yaml.safe_load((path or CLASSES).read_text(encoding="utf-8")) or {}).get("relations") or []
    return [r for r in rows if r.get("rel") in HAND_RELS and r.get("from") and r.get("to")
            and str(r.get("evidence", "")).startswith("http")]


def sync_hand(path: Path | None = None) -> int:
    """Write the hand-written relations into event_links (stated_by 'hand') when the file has changed."""
    path = path or CLASSES
    mtime = (str(path), path.stat().st_mtime) if path.exists() else None
    if mtime == _hand["mtime"]:
        return 0
    rels = hand_relations(path) if mtime else []
    with db.session() as con:
        con.execute("DELETE FROM event_links WHERE stated_by='hand'")
        labels = {r["key"]: r["label"] for r in con.execute(
            f"SELECT key, label FROM events WHERE key IN ({','.join('?' * len({x for r in rels for x in (r['from'], r['to'])}))})",
            [x for x in {x for r in rels for x in (r['from'], r['to'])}])} if rels else {}
        for r in rels:
            con.execute("INSERT OR REPLACE INTO event_links VALUES(?,?,?,?,?,?,?,?)",
                        (r["from"], r["rel"], r["to"], labels.get(r["from"], r["from"]), labels.get(r["to"], r["to"]),
                         "hand", "written by hand" + (f": {r['note']}" if r.get("note") else ""), r["evidence"]))
    _hand["mtime"] = mtime
    return len(rels)


def classes(path: Path | None = None) -> list[dict]:
    return (yaml.safe_load((path or CLASSES).read_text(encoding="utf-8")) or {}).get("classes") or []


def _download(url: str, name: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / name
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=600) as r, open(out, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    return out


# ── matching names to the gazetteer ──
GENERIC = {"not attributed", "unknown", "anonymous", "not available", "unknown actor", "unknown hackers"}


def _aliases(written: str) -> list[str]:
    """EuRepoC writes a group as 'Fancy Bear/APT28/…/Forest Blizzard fka STRONTIUM (GRU, Unit 26165) < Umbrella':
    every alias, without the sponsor in brackets and the umbrella group after '<'."""
    s = re.sub(r"\([^)]*\)", " ", written.split("<")[0])
    out = []
    for part in s.split("/"):
        for name in re.split(r"\s+fka\s+", part):
            name = " ".join(name.split())
            if name:
                out.append(name)
    return out


def resolve_name(written: str, names: dict[str, list[tuple]]) -> tuple[str | None, str | None]:
    """(actor key, note) when the aliases point to one gazetteer actor – or when one actor holds a clear majority of
    them (at least 2, and twice as many as any other: one stray alias of another group does not hide 'Sandworm');
    (None, reason) otherwise."""
    from collections import Counter
    from .sanctions import normalise
    if normalise(written) in GENERIC:
        return None, "not a name"
    votes = Counter(k for a in dict.fromkeys(_aliases(written)) for k in {k for k, *_ in names.get(normalise(a), [])})
    if len(votes) == 1:
        return next(iter(votes)), None
    if not votes:
        return None, "no name in the gazetteer"
    (top, n), (_, second) = votes.most_common(2)
    if n >= 2 and n >= 2 * second:
        return top, f"{n} of {sum(votes.values())} matching names point to it"
    return None, f"{len(votes)} actors share these names"


def _country_names(con) -> dict[str, str]:
    """normalised English country name → ISO code, from the gazetteer's countries."""
    from .sanctions import normalise
    return {normalise(r["label"]): r["iso"] for r in con.execute("SELECT label, iso FROM actors WHERE kind='country' AND iso IS NOT NULL")}


UCDP_COUNTRIES = {"united states of america": "US", "turkey": "TR", "russia": "RU", "bosnia herzegovina": "BA",
                  "dr congo": "CD", "ivory coast": "CI", "kingdom of eswatini": "SZ", "myanmar": "MM",
                  "cambodia": "KH", "serbia": "RS", "yemen": "YE", "north macedonia": "MK", "czech republic": "CZ"}


def ucdp_iso(name: str, by_name: dict[str, str]) -> str | None:
    """UCDP's country name ('Russia (Soviet Union)', 'United States of America') → ISO code."""
    from .sanctions import normalise
    n = normalise(re.sub(r"\([^)]*\)", " ", name))
    return UCDP_COUNTRIES.get(n) or by_name.get(n)


# ── Wikidata ──
def _claim_ids(ent: dict, prop: str) -> list[str]:
    return [c["mainsnak"]["datavalue"]["value"]["id"] for c in ent.get("claims", {}).get(prop, [])
            if c["mainsnak"].get("datavalue", {}).get("type") == "wikibase-entityid"]


def _first(ent: dict, prop: str):
    cs = [c for c in ent.get("claims", {}).get(prop, []) if c["mainsnak"].get("datavalue") and c.get("rank") != "deprecated"]
    cs.sort(key=lambda c: c.get("rank") != "preferred")
    return cs[0]["mainsnak"]["datavalue"]["value"] if cs else None


def _date(v: dict | None) -> str | None:
    """A Wikidata time as YYYY[-MM[-DD]]; None for decades and centuries ('+2020' = the 2020s, '+2100' = the 21st
    century), which are no date to draw."""
    if not v or v.get("precision", 0) < 9:
        return None
    from .actor_sources import _time
    return _time(v)


LABEL_LANGS = ["en", "mul", "uk", "ru", "de", "fr", "es", "pl", "it", "pt", "nl", "ja", "ar", "he", "tr"]
# the languages of the library's reports: an event's label and aliases in these are searched for in the reports
NAME_LANGS = ["en", "mul", "es", "de", "fr", "hr", "et", "cs", "sq", "ja", "ro", "nl", "nb", "pl", "bg", "lv", "sl", "tr",
              "sv", "sk", "it", "ru", "uk", "pt", "fi", "da", "is", "hu", "el", "mk"]


def _label(ent: dict, field: str = "labels") -> str | None:
    """The English label, else the first one in LABEL_LANGS (an item about a strike on Kyiv may have only Ukrainian)."""
    vals = ent.get(field, {})
    return next((vals[l]["value"] for l in LABEL_LANGS if l in vals), None)


def parse_item(qid: str, ent: dict, kind: str, sitelinks: int) -> dict:
    """One Wikidata item → an event row with its countries, actors and stated relations (QIDs, labels added later)."""
    point, start, end = _date(_first(ent, "P585")), _date(_first(ent, "P580")), _date(_first(ent, "P582"))
    coord = _first(ent, "P625")
    deaths = _first(ent, "P1120")
    links = []
    for prop, (_, rel) in RELATIONS.items():
        for other in _claim_ids(ent, prop):
            a, b = (other, qid) if prop in _BACKWARD else (qid, other)
            links.append({"src": a, "rel": rel, "dst": b, "stated_by": qid, "property": prop})
    return {"key": qid, "source": "wikidata", "kind": kind,
            "label": _label(ent) or qid, "description": _label(ent, "descriptions"),
            "names": sorted({(v["value"], lang) for lang, v in ent.get("labels", {}).items() if lang in NAME_LANGS} |
                            {(a["value"], lang) for lang, vs in ent.get("aliases", {}).items() if lang in NAME_LANGS for a in vs}),
            "start": point or start, "end": point or end,
            "lat": coord["latitude"] if coord else None, "lon": coord["longitude"] if coord else None,
            "deaths": int(float(deaths["amount"])) if deaths else None, "weight": sitelinks,
            "url": f"https://www.wikidata.org/wiki/{qid}",
            "countries": _claim_ids(ent, "P17"),
            "actors": [("participant", q) for q in _claim_ids(ent, "P710")] + [("perpetrator", q) for q in _claim_ids(ent, "P8031")],
            "links": links}


def fetch_wikidata(con, scope: set[str]) -> dict:
    from . import actor_sources as src
    country_iso = {r["qid"]: r["iso"] for r in con.execute("SELECT qid, iso FROM actors WHERE kind='country' AND qid IS NOT NULL")}
    known = {r["qid"]: r["key"] for r in con.execute("SELECT key, qid FROM actors WHERE qid IS NOT NULL")}
    found: dict[str, tuple[str, int]] = {}
    for c in classes():
        q = f"""SELECT DISTINCT ?e ?links WHERE {{ ?e wdt:P31/wdt:P279* wd:{c['qid']} . ?e wdt:P585|wdt:P580 ?d .
                FILTER(YEAR(?d) >= {SINCE}) ?e wikibase:sitelinks ?links }}"""
        rows = src.sparql(q)
        for r in rows:
            found.setdefault(src._qid(r["e"]["value"]), (c["label"], int(r["links"]["value"])))
        log.info("wikidata %s: %d items", c["label"], len(rows))
    ents = src.entities(list(found), "labels|descriptions|claims|aliases", sorted(set(LABEL_LANGS) | set(NAME_LANGS)))
    events = []
    for qid, ent in ents.items():
        e = parse_item(qid, ent, *found[qid])
        isos = [country_iso[q] for q in e["countries"] if q in country_iso]
        if not (set(isos) & scope or any(q in known for _, q in e["actors"])):
            continue
        if not e["start"] or int(e["start"][:4]) < SINCE:
            continue
        e["countries"] = isos
        events.append(e)
    kept = {e["key"] for e in events}
    # labels of the participants and of the other ends of relations
    need = {q for e in events for _, q in e["actors"] if q not in known} | \
           {x for e in events for l in e["links"] for x in (l["src"], l["dst"]) if x not in kept}
    labels = {k: _label(v) or k for k, v in src.entities(list(need), "labels", LABEL_LANGS).items()} if need else {}
    gaz = {r["key"]: r["label"] for r in con.execute("SELECT key, label FROM actors")}
    by_key = {e["key"]: e["label"] for e in events}
    for e in events:
        e["actors"] = [{"role": role, "name": gaz.get(known.get(q), labels.get(q, q)), "qid": q, "actor_key": known.get(q),
                        "reason": None if q in known else "not in the gazetteer"} for role, q in e["actors"]]
        for l in e["links"]:
            l["src_label"] = by_key.get(l["src"]) or labels.get(l["src"], l["src"])
            l["dst_label"] = by_key.get(l["dst"]) or labels.get(l["dst"], l["dst"])
    return {"events": events}


# ── EuRepoC ──
def _eu_date(s: str) -> str | None:
    m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", (s or "").strip())
    return f"{m[3]}-{m[2]}-{m[1]}" if m else None


def parse_eurepoc(rows, names: dict[str, list[tuple]], country_key: dict[str, str]) -> list[dict]:
    """EuRepoC rows → events: receivers as countries, initiators matched to the gazetteer, a state linked as the
    initiator only when EuRepoC codes the initiator as a state."""
    out = []
    for r in rows:
        start = _eu_date(r["start_date"])
        if not start or int(start[:4]) < SINCE:
            continue
        split = lambda v: [x.strip() for x in (v or "").split(";") if x.strip() and x.strip() != "Not available"]
        actors, seen = [], set()
        for name in split(r["initiator_name"]):
            if name in seen:
                continue
            seen.add(name)
            key, reason = resolve_name(name, names)
            actors.append({"role": "initiator", "name": name, "qid": None, "actor_key": key, "reason": reason})
        cats = split(r["initiator_category"])
        for i, a2 in enumerate(split(r["initiator_alpha_2"])):
            if i < len(cats) and cats[i] == "State" and a2 in country_key and a2 not in seen:
                seen.add(a2)
                actors.append({"role": "initiator state", "name": a2, "qid": None, "actor_key": country_key[a2], "reason": None})
        for c in sorted({x for x in split(r["attributing_country"])}):
            if c in seen:
                continue
            seen.add(c)
            actors.append({"role": "attributed by", "name": c, "qid": None, "actor_key": None, "reason": "a state's name, as written"})
        try:
            weight = float(r.get("weighted_intensity") or "")
        except ValueError:
            weight = None
        src_urls = split(r.get("source_url"))
        out.append({"key": f"eurepoc:{r['incident_id']}", "source": "eurepoc", "kind": "cyber incident",
                    "label": " ".join((r["name"] or "").split()) or f"incident {r['incident_id']}",
                    "description": " ".join((r["description"] or "").split())[:600],
                    "start": start, "end": _eu_date(r["end_date"]) or start, "lat": None, "lon": None, "deaths": None,
                    "weight": weight, "url": src_urls[0] if src_urls else EUREPOC_RECORD,
                    "countries": sorted({c for c in split(r["receiver_country_alpha_2_code"]) if re.fullmatch(r"[A-Z]{2}", c)}),
                    "actors": actors, "links": [],
                    "data": {"incident_type": r.get("incident_type"), "attribution_date": r.get("attribution_date"),
                             "settled_initiator": r.get("settled_initiator"), "sources": src_urls[:5],
                             "incident_id": r["incident_id"]}})
    return out


# ── UCDP ──
def parse_ucdp(rows, by_name: dict[str, str], scope: set[str], names: dict[str, list[tuple]], preliminary: bool = False,
               months: dict | None = None) -> list[dict]:
    """UCDP rows → monthly deaths per country (into `months`) and the events with at least BIG_EVENT deaths in a
    state of the library."""
    months = {} if months is None else months
    out = []
    col = {"1": "state", "2": "nonstate", "3": "onesided"}
    for r in rows:
        iso = ucdp_iso(r["country"], by_name)
        if not iso:
            continue
        start = (r["date_start"] or "")[:10]
        if not start or int(start[:4]) < SINCE:
            continue
        best = int(float(r["best"] or 0))
        m = months.setdefault((iso, start[:7]), {"deaths": 0, "events": 0, "state": 0, "nonstate": 0, "onesided": 0,
                                                 "preliminary": int(preliminary)})
        m["deaths"] += best
        m["events"] += 1
        m[col.get(r["type_of_violence"], "state")] += best
        # a single event: at least BIG_EVENT deaths in a state of the library, coded as one clear event (UCDP's
        # event_clarity 1) dated to within a week (date_prec 1–3) – not UCDP's monthly or yearly sums of losses
        if best < BIG_EVENT or iso not in scope or r.get("event_clarity") != "1" or r.get("date_prec") not in ("1", "2", "3"):
            continue
        actors = []
        for role, side in (("side A", r["side_a"]), ("side B", r["side_b"])):
            g = re.fullmatch(r"Government of (.+)", side or "")
            if g and (c := ucdp_iso(g[1], by_name)):
                actors.append({"role": role, "name": side, "qid": None, "actor_key": None, "reason": None, "country": c})
            elif side:
                key, reason = resolve_name(side, names)
                actors.append({"role": role, "name": side, "qid": None, "actor_key": key, "reason": reason})
        place = r.get("where_coordinates") or r.get("adm_1") or r["country"]
        out.append({"key": f"ucdp:{r['id']}", "source": "ucdp", "kind": VIOLENCE.get(r["type_of_violence"], "organised violence"),
                    "label": " ".join(f"{r['conflict_name']}: {place}".split()), "description": (r.get("source_headline") or "")[:300] or None,
                    "start": start, "end": (r["date_end"] or "")[:10] or start,
                    "lat": float(r["latitude"]) if r.get("latitude") else None,
                    "lon": float(r["longitude"]) if r.get("longitude") else None,
                    "deaths": best, "weight": best, "url": UCDP_CONFLICT.format(id=r["conflict_new_id"]),
                    "preliminary": int(preliminary), "countries": [iso], "actors": actors, "links": [],
                    "data": {"dyad": r.get("dyad_name"), "low": r.get("low"), "high": r.get("high"), "ucdp_id": r["id"]}})
    return out


def _candidate_url() -> str | None:
    """The newest monthly Candidate Events CSV listed on the UCDP download page."""
    req = urllib.request.Request(UCDP_DOWNLOADS, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        page = r.read().decode("utf-8", "replace")
    found = re.findall(r'href="(https://ucdp\.uu\.se/downloads/candidateged/GEDEvent_v(\d+)_(\d+)_(\d+)\.csv)"', page)
    return max(found, key=lambda f: tuple(int(x) for x in f[1:]))[0] if found else None


# ── storing ──
def _store(con, events: list[dict], source: str) -> None:
    keys = [e["key"] for e in events]
    con.execute("DELETE FROM event_countries WHERE event_key IN (SELECT key FROM events WHERE source=?)", (source,))
    con.execute("DELETE FROM event_names WHERE event_key IN (SELECT key FROM events WHERE source=?)", (source,))
    con.execute("DELETE FROM event_docs WHERE event_key IN (SELECT key FROM events WHERE source=?)", (source,))
    con.execute("DELETE FROM event_actors WHERE event_key IN (SELECT key FROM events WHERE source=?)", (source,))
    con.execute("DELETE FROM event_links WHERE stated_by IN (SELECT key FROM events WHERE source=?)", (source,))
    con.execute("DELETE FROM events WHERE source=?", (source,))
    country_key = {r["iso"]: r["key"] for r in con.execute("SELECT key, iso FROM actors WHERE kind='country' AND iso IS NOT NULL")}
    for e in events:
        con.execute("""INSERT OR REPLACE INTO events(key, source, kind, label, description, start, end, year, lat, lon, deaths,
                       weight, url, preliminary, data) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (e["key"], source, e["kind"], e["label"], e.get("description"), e["start"], e.get("end"),
                     int(e["start"][:4]), e.get("lat"), e.get("lon"), e.get("deaths"), e.get("weight"), e["url"],
                     e.get("preliminary", 0), json.dumps(e.get("data") or {}, ensure_ascii=False)))
        con.executemany("INSERT OR IGNORE INTO event_countries VALUES(?,?)", [(e["key"], c) for c in e["countries"]])
        con.executemany("INSERT OR IGNORE INTO event_names(event_key, name, lang) VALUES(?,?,?)",
                        [(e["key"], n, lang) for n, lang in e.get("names") or []])
        for a in e["actors"]:
            key = a.get("actor_key") or (country_key.get(a["country"]) if a.get("country") else None)
            con.execute("INSERT OR IGNORE INTO event_actors VALUES(?,?,?,?,?,?)",
                        (e["key"], a["role"], a["name"], a.get("qid"), key, a.get("reason")))
        for l in e["links"]:
            con.execute("INSERT OR IGNORE INTO event_links VALUES(?,?,?,?,?,?,?,?)",
                        (l["src"], l["rel"], l["dst"], l["src_label"], l["dst_label"], l["stated_by"], l["property"],
                         f"https://www.wikidata.org/wiki/{l['stated_by']}#{l['property']}"))
    log.info("events %s: %d", source, len(keys))


def _meta(con, source: str, rows: int, note: str = "", **extra) -> None:
    m = {**META[source], **extra}
    con.execute("INSERT OR REPLACE INTO event_meta VALUES(?,?,?,?,?,?,?,?,?)",
                (source, m["name"], dt.date.today().isoformat(), m["url"], m.get("data_url"), m["license"], m["citation"],
                 rows, note))


def fetch(sources: tuple[str, ...] = ("wikidata", "eurepoc", "ucdp")) -> dict:
    """Download the events of every source and store them; returns counts per source."""
    from . import countries
    from .sanctions import _actor_names
    init()
    scope = {c for c in countries.names() if c not in ("EU", "NATO", "OTHER")}
    out = {}
    with db.session() as con:
        names = _actor_names(con)
        by_name = _country_names(con)
        country_key = {r["iso"]: r["key"] for r in con.execute("SELECT key, iso FROM actors WHERE kind='country' AND iso IS NOT NULL")}
        if "wikidata" in sources:
            evs = fetch_wikidata(con, scope)["events"]
            _store(con, evs, "wikidata")
            _meta(con, "wikidata", len(evs), f"{len(classes())} classes, since {SINCE}")
            out["wikidata"] = len(evs)
        if "eurepoc" in sources:
            path = _download(EUREPOC_CSV, "eurepoc_global.csv")
            csv.field_size_limit(10 ** 8)
            with open(path, encoding="utf-8") as f:
                evs = parse_eurepoc(csv.DictReader(f), names, country_key)
            path.unlink()                    # downloaded afresh every time; the database holds what is used
            _store(con, evs, "eurepoc")
            _meta(con, "eurepoc", len(evs))
            out["eurepoc"] = len(evs)
        if "ucdp" in sources:
            months: dict = {}
            path = _download(UCDP_GED, "ged.zip")
            with zipfile.ZipFile(path) as z:
                name = next(n for n in z.namelist() if n.endswith(".csv"))
                with z.open(name) as f:
                    evs = parse_ucdp(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8")), by_name, scope, names,
                                     months=months)
            path.unlink()
            last = max((m for _, m in months), default="")
            cand_url, n_cand = _candidate_url(), 0
            if cand_url:
                cand = _download(cand_url, "candidate.csv")
                with open(cand, encoding="utf-8") as f:
                    rows = [r for r in csv.DictReader(f) if (r.get("date_start") or "")[:7] > last]
                n_cand = len(rows)
                cand.unlink()
                evs += parse_ucdp(rows, by_name, scope, names, preliminary=True, months=months)
            _store(con, evs, "ucdp")
            con.execute("DELETE FROM event_months")
            con.executemany("INSERT INTO event_months VALUES(?,?,?,?,?,?,?,?)",
                            [(iso, m, v["deaths"], v["events"], v["state"], v["nonstate"], v["onesided"], v["preliminary"])
                             for (iso, m), v in months.items()])
            _meta(con, "ucdp", len(evs), f"single events with at least {BIG_EVENT} deaths in a state of the library; "
                  f"deaths per country and month for all states; candidate events after {last}: {n_cand}",
                  data_url=UCDP_GED + (" · " + cand_url if cand_url else ""))
            out["ucdp"] = len(evs)
            out["ucdp_months"] = len(months)
    out["named_in_reports"] = index_reports()
    return out


# ── reading ──
def meta() -> dict[str, dict]:
    init()
    with db.session() as con:
        return {r["source"]: dict(r) for r in con.execute("SELECT * FROM event_meta")}


def query(source: str = "", kind: str = "", country: str = "", year: int | None = None, q: str = "",
          actor: str = "", key: str = "") -> tuple[str, list]:
    where, args = ["1=1"], []
    if key:
        where.append("e.key=?"); args.append(key)
    if source:
        where.append("e.source=?"); args.append(source)
    if kind:
        where.append("e.kind=?"); args.append(kind)
    if country:
        where.append("e.key IN (SELECT event_key FROM event_countries WHERE iso=?)"); args.append(country)
    if year:
        where.append("e.year=?"); args.append(year)
    if q:
        where.append("e.label LIKE ?"); args.append(f"%{q}%")
    if actor:
        where.append("e.key IN (SELECT event_key FROM event_actors WHERE actor_key=?)"); args.append(actor)
    return " AND ".join(where), args


def listing(offset: int, limit: int, **filters) -> tuple[int, list[dict]]:
    init()
    where, args = query(**filters)
    with db.session() as con:
        total = con.execute(f"SELECT COUNT(*) FROM events e WHERE {where}", args).fetchone()[0]
        rows = [dict(r) for r in con.execute(f"SELECT * FROM events e WHERE {where} ORDER BY e.start DESC, e.key LIMIT ? OFFSET ?",
                                             (*args, limit, offset))]
        keys = [r["key"] for r in rows]
        marks = ",".join("?" * len(keys))
        ctry, acts, links = {}, {}, {}
        if keys:
            for r in con.execute(f"SELECT event_key, iso FROM event_countries WHERE event_key IN ({marks}) ORDER BY iso", keys):
                ctry.setdefault(r["event_key"], []).append(r["iso"])
            for r in con.execute(f"""SELECT ea.*, a.label actor_label FROM event_actors ea LEFT JOIN actors a ON a.key=ea.actor_key
                                     WHERE ea.event_key IN ({marks})""", keys):
                acts.setdefault(r["event_key"], []).append(dict(r))
            for r in con.execute(f"SELECT * FROM event_links WHERE src IN ({marks}) OR dst IN ({marks})", keys + keys):
                for k in {r["src"], r["dst"]} & set(keys):
                    links.setdefault(k, []).append(dict(r))
        reports = report_counts(con, keys)
        names = {}
        if keys:
            for r in con.execute(f"SELECT * FROM event_names WHERE event_key IN ({marks}) ORDER BY status DESC, docs DESC, name", keys):
                names.setdefault(r["event_key"], []).append(dict(r))
    for r in rows:
        r["countries"], r["actors"], r["links"] = ctry.get(r["key"], []), acts.get(r["key"], []), links.get(r["key"], [])
        r["data"] = json.loads(r["data"] or "{}")
        r["reports"], r["names"] = reports.get(r["key"], 0), names.get(r["key"], [])
    return total, rows


def report_counts(con, keys: list[str]) -> dict[str, int]:
    """{event key: reports naming it} – counted as the Documents list /documents?event=… counts (its default filters)."""
    from . import doclist
    if not keys:
        return {}
    f = doclist.build()
    marks = ",".join("?" * len(keys))
    return dict(con.execute(f"""SELECT ed.event_key, COUNT(*) FROM event_docs ed JOIN documents d ON d.id=ed.doc_id
                                JOIN sources s ON s.id=d.source_id
                                WHERE ed.event_key IN ({marks}) AND {' AND '.join(f['where'])} GROUP BY ed.event_key""",
                            [*keys, *f["args"]]).fetchall())


def facets() -> dict:
    init()
    with db.session() as con:
        return {"sources": [tuple(r) for r in con.execute("SELECT source, COUNT(*) FROM events GROUP BY source ORDER BY source")],
                "kinds": [tuple(r) for r in con.execute("SELECT kind, COUNT(*) FROM events GROUP BY kind ORDER BY COUNT(*) DESC")],
                "years": [r[0] for r in con.execute("SELECT DISTINCT year FROM events ORDER BY year DESC")],
                "links": con.execute("SELECT COUNT(*) FROM event_links").fetchone()[0],
                "months": con.execute("SELECT COUNT(*) FROM event_months").fetchone()[0]}


# ── the timeline (/timeline): lanes of countries and actors on one time axis ──
RECORD_KINDS = {"listed", "designated", "attributed", "threat level", "founded", "dissolved"}   # not first/last named:
                                                                                               # the report strip shows those
_ranks: dict = {"version": None, "ranks": {}}


def ranks() -> dict[str, float]:
    """{event key: 0–1}, its place by weight within its own source (1 = the heaviest): the sources weigh differently
    (Wikipedia editions, intensity, deaths), so an event is compared only with events of the same source."""
    v = db.version()
    if _ranks["version"] != v:
        init()
        out = {}
        with db.session() as con:
            for (src,) in con.execute("SELECT DISTINCT source FROM events"):
                rows = con.execute("SELECT key FROM events WHERE source=? ORDER BY COALESCE(weight, 0), key", (src,)).fetchall()
                n = max(1, len(rows) - 1)
                out.update({r["key"]: round(i / n, 4) for i, r in enumerate(rows)})
        _ranks.update(version=v, ranks=out)
    return _ranks["ranks"]


def parse_lanes(specs: list[str]) -> list[tuple[str, str]]:
    """['country:UA', 'actor:Q100605916'] → [('country', 'UA'), ('actor', 'Q100605916')]; unknown kinds dropped."""
    out = []
    for s in specs:
        kind, _, value = (s or "").partition(":")
        if kind in ("country", "actor") and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", value) and (kind, value) not in out:
            out.append((kind, value.upper() if kind == "country" else value))
    return out


def timeline(lanes: list[tuple[str, str]]) -> dict:
    """Everything the timeline draws for these lanes: the lanes, their events, the library's dated records (sanctions
    listings, attributions, threat levels …), reports per year naming the lane's subject (each year opens its list),
    and UCDP deaths per month for a state – each with its source."""
    from . import actor_events, doclist
    init()
    rk = ranks()
    out = {"lanes": [], "items": [], "strips": {}, "meta": meta()}
    with db.session() as con:
        for kind, value in lanes:
            if kind == "country":
                row = con.execute("SELECT key, label FROM actors WHERE kind='country' AND iso=?", (value,)).fetchone()
                actor_key, label, iso = (row["key"], row["label"], value) if row else (None, value, value)
                evs = con.execute("""SELECT DISTINCT e.* FROM events e WHERE e.key IN (SELECT event_key FROM event_countries WHERE iso=?)
                                     OR e.key IN (SELECT event_key FROM event_actors WHERE actor_key=?)""", (iso, actor_key or "")).fetchall()
            else:
                row = con.execute("SELECT key, label, iso FROM actors WHERE key=?", (value,)).fetchone()
                if not row:
                    continue
                actor_key, label, iso = row["key"], row["label"], row["iso"]
                evs = con.execute("SELECT DISTINCT e.* FROM events e JOIN event_actors ea ON ea.event_key=e.key WHERE ea.actor_key=?",
                                  (actor_key,)).fetchall()
            lane = f"{kind}:{value}"
            out["lanes"].append({"id": lane, "kind": kind, "value": value, "label": label, "actor": actor_key, "iso": iso,
                                 "href": f"/actors/{actor_key}" if actor_key else None, "events": len(evs)})
            for e in evs:
                out["items"].append({"id": f"{lane}|{e['key']}", "lane": lane, "key": e["key"], "label": e["label"], "kind": e["kind"],
                                     "source": e["source"], "start": e["start"], "end": e["end"], "deaths": e["deaths"],
                                     "rank": rk.get(e["key"], 0), "preliminary": e["preliminary"], "url": e["url"]})
            strip = {"reports": {}, "deaths": {}}
            if actor_key:
                for r in actor_events.of_actor(actor_key):
                    if r["kind"] in RECORD_KINDS and re.match(r"\d{4}", str(r["date"])):
                        out["items"].append({"id": f"{lane}|rec|{r['kind']}|{r['date']}|{r['title'][:40]}", "lane": lane,
                                             "key": None, "label": r["title"], "kind": r["kind"], "source": "library",
                                             "start": str(r["date"]), "end": None, "rank": 1, "url": r.get("source_url"),
                                             "detail": r.get("detail"), "by": r.get("source")})
                # what the local library's books say happened, dated to a day or a month (a year alone would be a
                # bar over the whole year): "according to <book>, p. n" – a book's statement, not an event of the sources
                try:
                    from . import books as _books, meanings
                    meanings.init()
                    for st in con.execute("""SELECT s.doc_id, s.start, s.page, s.date, s.precision, s.sentence, b.title, b.year
                                             FROM book_statements s JOIN books b ON b.doc_id=s.doc_id
                                             WHERE s.precision IN ('day', 'month') AND s.actors LIKE ?""", (f'%"{actor_key}"%',)):
                        page = _books.page_name(st["doc_id"], st["page"])
                        book = f"{st['title']} ({st['year']})" if st["year"] else st["title"]
                        out["items"].append({"id": f"{lane}|book|{st['doc_id']}|{st['start']}", "lane": lane, "key": None,
                                             "label": st["sentence"][:90], "kind": f"book, {page}", "source": "book",
                                             "start": st["date"], "end": None, "rank": 0.3 if st["precision"] == "day" else 0.2,
                                             "url": f"/doc/{st['doc_id']}#page={st['page']}", "detail": st["sentence"],
                                             "by": f"{book}, {page}"})
                except Exception as e:  # noqa: BLE001 - no book tables yet
                    log.debug("no book statements: %s", e)
                f = doclist.build(actor=actor_key, indexed=1)
                for y, n in con.execute(f"""SELECT d.year, COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                                            WHERE {' AND '.join(f['where'])} AND d.year IS NOT NULL GROUP BY d.year""", f["args"]):
                    strip["reports"][str(y)] = {"n": n, "url": f"/documents?actor={actor_key}&indexed=1&year={y}"}
            if iso:
                for r in con.execute("SELECT month, deaths, preliminary FROM event_months WHERE iso=? AND deaths > 0 ORDER BY month", (iso,)):
                    strip["deaths"][r["month"]] = {"n": r["deaths"], "preliminary": r["preliminary"]}
            out["strips"][lane] = strip
        # the stated relations between stored events that touch these lanes – the chains the timeline draws
        keys = sorted({i["key"] for i in out["items"] if i["key"]})
        links, seen = [], set()
        for chunk in (keys[i:i + 500] for i in range(0, len(keys), 500)):
            marks = ",".join("?" * len(chunk))
            for r in con.execute(f"""SELECT l.* FROM event_links l JOIN events a ON a.key=l.src JOIN events b ON b.key=l.dst
                                     WHERE l.src IN ({marks}) OR l.dst IN ({marks})""", chunk + chunk):
                if (r["src"], r["rel"], r["dst"]) not in seen:
                    seen.add((r["src"], r["rel"], r["dst"]))
                    links.append(dict(r))
        out["links"] = links
    return out


def detail(key: str) -> dict | None:
    """One event with its countries, actors and every relation it takes part in (both directions)."""
    init()
    total, rows = listing(0, 1, key=key)
    return rows[0] if rows else None



# ── which reports name an event ──
CASELESS = re.compile(r"[\u0590-\u06ff\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")   # Hebrew, Arabic, Japanese, Chinese, Korean


MONTHS = {m.casefold() for m in (
    "january february march april may june july august september october november december "
    "januar februar märz april mai juni juli august september oktober november dezember "
    "janvier février mars avril mai juin juillet août septembre octobre novembre décembre "
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre "
    "januari februari maart april mei juni juli augustus september oktober november december "
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre "
    "styczeń luty marzec kwiecień maj czerwiec lipiec sierpień wrzesień październik listopad grudzień").split()}


OPERATION = {w.casefold() for w in "operation operazione operación opération operação operatie operacja operasjon operaatio "
             "operace operácia operacija operaţiunea operațiunea operationen операция операція операция".split()}


def name_rule(name: str, actor_names: set[str], ignored: dict[str, str] | None = None) -> str | None:
    """Why a name is not searched for, or None when it is. General rules first: at least two words; a word of three
    letters or more (not a code such as '11-M'); not only a date ('October 7'); not a one-word code name ('Operation
    Domino' – reused by many forces); something specific after the first
    word – a capitalised word, an acronym (COVID) or a year – so a phrase like 'Lucha contra el terrorismo' (the fight
    against terrorism), capitalised only at its start, is not taken for a name; not an actor's name (the actor index
    finds those); a script the full-text index splits into words. Then the names excluded by hand, with their reason."""
    from .sanctions import normalise
    words = re.findall(r"\w+", name)
    if CASELESS.search(name):
        return "script not split into words by the full-text index"
    if len(words) < 2:
        return "one word – too ambiguous"
    if all(w.isdigit() or len(w) <= 2 for w in words):
        return "a code or abbreviation – too ambiguous"
    if all(w.isdigit() or w.casefold() in MONTHS for w in words):
        return "a date, not a name"
    if len(words) == 2 and words[0].casefold() in OPERATION:
        return "a one-word code name – police and armed forces reuse them"
    year = any(re.fullmatch(r"(1[89]|20)\d\d", w) for w in words)
    acronym = any(len(w) >= 3 and w.isupper() for w in words)
    if not (year or acronym or any(w[0].isupper() for w in words[1:])):
        return "no proper name or year in it"
    if normalise(name) in actor_names:
        return "an actor's name"
    if ignored and normalise(name) in ignored:
        return f"excluded by hand: {ignored[normalise(name)]}"
    return None


def ignored_names(path: Path | None = None) -> dict[str, str]:
    """Names excluded by hand (sources/events.yaml `ignore_names`): normalised name → reason."""
    from .sanctions import normalise
    rows = (yaml.safe_load((path or CLASSES).read_text(encoding="utf-8")) or {}).get("ignore_names") or []
    return {normalise(r["name"]): r.get("reason", "") for r in rows if r.get("name")}


def _fts_phrase(name: str) -> str:
    return '"' + " ".join(re.findall(r"\w+", name)) + '"'


NEAR = 80        # characters on either side of a name in which an earlier year means the passage speaks of something earlier


def _occurrence_regex(name: str) -> re.Pattern:
    from . import topics
    words = re.findall(r"\w+", topics.normalize(name))
    return re.compile(r"(?<!\w)" + r"\W+".join(map(re.escape, words)) + r"(?!\w)")


def clean_occurrences(body: str, rx: re.Pattern, year: int) -> tuple[int, int]:
    """(occurrences, those without an earlier year beside them – within NEAR characters and the sentence) of a name in a
    normalised text. A generic
    name of the 2022 invasion also describes 2014 ("Russia's invasion of Ukraine in 2014", "since 2014"): an occurrence
    next to a year before the event's start year speaks of something earlier."""
    n = clean = 0
    for m in rx.finditer(body):
        n += 1
        # within NEAR characters, and within the sentence: a year in the sentence before speaks of something else
        # (a line break is no sentence end: PDF text breaks lines mid-sentence; an empty line is)
        left = re.split(r"[.!?;]\s|\n\s*\n", body[max(0, m.start() - NEAR):m.start()])[-1]
        right = re.split(r"[.!?;]\s|\n\s*\n", body[m.end():m.end() + NEAR])[0]
        window = left + right
        if not any(int(y) < year for y in re.findall(r"(?<!\d)((?:19|20)\d\d)(?!\d)", window)):
            clean += 1
    return n, clean


def index_reports() -> dict:
    """Find the reports that name each Wikidata event, by its used names (rules: name_rule; a name shared by two
    events is not used), in the event's start year or later – a report cannot name an event that had not happened –
    and with at least one occurrence that has no earlier year beside it (clean_occurrences).
    Writes event_names.status/reason/docs and event_docs."""
    from . import topics
    from .sanctions import normalise
    init()
    with db.session() as con:
        actor_names = {normalise(r[0]) for r in con.execute("SELECT name FROM actor_names WHERE status='used'")}
        ignored = ignored_names()
        rows = con.execute("""SELECT n.event_key, n.name, e.year FROM event_names n JOIN events e ON e.key=n.event_key
                              WHERE e.source='wikidata'""").fetchall()
        owners: dict[str, set] = {}
        for r in rows:
            owners.setdefault(normalise(r["name"]), set()).add(r["event_key"])
        con.execute("DELETE FROM event_docs")
        candidates: dict[int, list] = {}                 # doc → [(event, name, year)] found by the full-text index
        status = {}
        stats = {"names": len(rows), "used": 0, "events": 0, "matches": 0, "only_beside_an_earlier_year": 0}
        for r in rows:
            reason = name_rule(r["name"], actor_names, ignored)
            if not reason and len(owners[normalise(r["name"])]) > 1:
                reason = f"also the name of {len(owners[normalise(r['name'])]) - 1} other event(s)"
            status[(r["event_key"], r["name"])] = reason
            if reason:
                continue
            stats["used"] += 1
            for (d,) in con.execute("""SELECT t.rowid FROM doc_text t JOIN documents d ON d.id=t.rowid
                                       WHERE doc_text MATCH ? AND (d.year IS NULL OR d.year >= ?)""",
                                    (_fts_phrase(r["name"]), r["year"])):
                candidates.setdefault(d, []).append((r["event_key"], r["name"], r["year"]))
        found: dict[tuple, set] = {}
        docs_of: dict[tuple, int] = {}
        for d, cands in candidates.items():
            row = con.execute("SELECT title, body FROM doc_text WHERE rowid=?", (d,)).fetchone()
            body = topics.normalize(f"{row['title'] or ''}\n{row['body'] or ''}")
            for key, name, year in cands:
                n, clean = clean_occurrences(body, _occurrence_regex(name), year)
                if clean:
                    found.setdefault((key, d), set()).add(name)
                    docs_of[(key, name)] = docs_of.get((key, name), 0) + 1
                elif n:
                    stats["only_beside_an_earlier_year"] += 1
        for (key, name), reason in status.items():
            con.execute("UPDATE event_names SET status=?, reason=?, docs=? WHERE event_key=? AND name=?",
                        ("ignored" if reason else "used", reason, docs_of.get((key, name), 0), key, name))
        con.executemany("INSERT INTO event_docs VALUES(?,?,?)", [(k, d, json.dumps(sorted(n), ensure_ascii=False)) for (k, d), n in found.items()])
        stats["matches"] = len(found)
        stats["events"] = len({k for k, _ in found})
    log.info("events named in reports: %s", stats)
    return stats


def sample(n: int = 50, seed: int = 1) -> list[dict]:
    """Random matches with the passage around the name – for measuring the precision by reading them."""
    import random
    init()
    with db.session() as con:
        pairs = con.execute("SELECT event_key, doc_id, names FROM event_docs").fetchall()
        out = []
        for r in random.Random(seed).sample(pairs, min(n, len(pairs))):
            name = json.loads(r["names"])[0]
            snip = con.execute("SELECT snippet(doc_text, 1, '[', ']', '…', 24) FROM doc_text WHERE rowid=? AND doc_text MATCH ?",
                               (r["doc_id"], _fts_phrase(name))).fetchone()
            ev = con.execute("SELECT label, start FROM events WHERE key=?", (r["event_key"],)).fetchone()
            out.append({"event": r["event_key"], "label": ev["label"], "start": ev["start"], "doc_id": r["doc_id"], "name": name,
                        "passage": snip[0] if snip else None})
        return out


def of_actor(key: str, limit: int = 8) -> dict:
    """The events an actor is linked to (participant, perpetrator, initiator, side – or, for a state, held in it): how
    many, by source, and the heaviest few – for the actor page."""
    init()
    rk = ranks()
    with db.session() as con:
        iso = (con.execute("SELECT iso FROM actors WHERE key=? AND kind='country'", (key,)).fetchone() or [None])[0]
        rows = con.execute("""SELECT DISTINCT e.key, e.label, e.start, e.source, e.kind FROM events e
                              WHERE e.key IN (SELECT event_key FROM event_actors WHERE actor_key=?)
                                 OR e.key IN (SELECT event_key FROM event_countries WHERE iso=?)""", (key, iso or "")).fetchall()
        rows = [dict(r) for r in rows]
        by_source: dict[str, int] = {}
        for r in rows:
            by_source[r["source"]] = by_source.get(r["source"], 0) + 1
        top = sorted(rows, key=lambda r: -rk.get(r["key"], 0))[:limit]
        reports = report_counts(con, [r["key"] for r in top])
    for r in top:
        r["reports"] = reports.get(r["key"], 0)
    return {"total": len(rows), "by_source": by_source, "top": sorted(top, key=lambda r: r["start"], reverse=True),
            "lane": f"country:{iso}" if iso else f"actor:{key}", "iso": iso}
