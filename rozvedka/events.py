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
    property TEXT, PRIMARY KEY (src, rel, dst));
CREATE TABLE IF NOT EXISTS event_months (            -- UCDP deaths in organised violence per country and month
    iso TEXT NOT NULL, month TEXT NOT NULL, deaths INTEGER, events INTEGER, state INTEGER, nonstate INTEGER,
    onesided INTEGER, preliminary INTEGER DEFAULT 0, PRIMARY KEY (iso, month));
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
    ents = src.entities(list(found), "labels|descriptions|claims", LABEL_LANGS)
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
        for a in e["actors"]:
            key = a.get("actor_key") or (country_key.get(a["country"]) if a.get("country") else None)
            con.execute("INSERT OR IGNORE INTO event_actors VALUES(?,?,?,?,?,?)",
                        (e["key"], a["role"], a["name"], a.get("qid"), key, a.get("reason")))
        for l in e["links"]:
            con.execute("INSERT OR IGNORE INTO event_links VALUES(?,?,?,?,?,?,?)",
                        (l["src"], l["rel"], l["dst"], l["src_label"], l["dst_label"], l["stated_by"], l["property"]))
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
    return out


# ── reading ──
def meta() -> dict[str, dict]:
    init()
    with db.session() as con:
        return {r["source"]: dict(r) for r in con.execute("SELECT * FROM event_meta")}


def query(source: str = "", kind: str = "", country: str = "", year: int | None = None, q: str = "",
          actor: str = "") -> tuple[str, list]:
    where, args = ["1=1"], []
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
    for r in rows:
        r["countries"], r["actors"], r["links"] = ctry.get(r["key"], []), acts.get(r["key"], []), links.get(r["key"], [])
        r["data"] = json.loads(r["data"] or "{}")
    return total, rows


def facets() -> dict:
    init()
    with db.session() as con:
        return {"sources": [tuple(r) for r in con.execute("SELECT source, COUNT(*) FROM events GROUP BY source ORDER BY source")],
                "kinds": [tuple(r) for r in con.execute("SELECT kind, COUNT(*) FROM events GROUP BY kind ORDER BY COUNT(*) DESC")],
                "years": [r[0] for r in con.execute("SELECT DISTINCT year FROM events ORDER BY year DESC")],
                "links": con.execute("SELECT COUNT(*) FROM event_links").fetchone()[0],
                "months": con.execute("SELECT COUNT(*) FROM event_months").fetchone()[0]}
