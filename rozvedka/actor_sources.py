"""Fetch the actor gazetteer from public reference data – the network half of the actor index.

    python -m rozvedka fetch-actors

Sources (all public):
  - Wikidata (CC0): items of the classes in sources/actors.yaml, items "designated as terrorist by" (P3461),
    items with a MITRE ATT&CK ID (P9025) and the hand-listed seeds; their labels and aliases in the report
    languages, description, country, dates, designations, image.
  - English Wikipedia (CC BY-SA 4.0): the lead section of each actor's article, with the revision it was taken from.
  - MITRE ATT&CK (Enterprise, STIX 2.1 from github.com/mitre-attack/attack-stix-data): threat groups, aliases,
    descriptions.

Everything is written to data/gazetteer/actors.json together with where and when it was retrieved, so the portal
can show the source of every fact. `index-actors` then works offline from that file.
"""
import datetime as dt
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

from . import connections
from .config import DATA, ROOT

log = logging.getLogger("rozvedka.actors")
CONFIG = ROOT / "sources" / "actors.yaml"
GAZETTEER = DATA / "gazetteer" / "actors.json"
UA = "Rozvedka/0.x (personal research library; https://github.com/iiogurt/Rozvedka)"
LANGS = ["en", "mul", "de", "fr", "es", "it", "nl", "pt", "cs", "sk", "pl", "sl", "hr", "hu", "ro", "bg", "el", "et", "lv",
         "lt", "fi", "sv", "da", "nb", "nn", "ru", "uk", "ja", "zh", "ko"]
ATTACK_URL = "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/enterprise-attack/enterprise-attack.json"
SPARQL = "https://query.wikidata.org/sparql"
WD_API = "https://www.wikidata.org/w/api.php"
WP_API = "https://en.wikipedia.org/w/api.php"
DELAY = 1.0
NOT_ACTORS = {"Q6256": "country", "Q7275": "state", "Q4830453": "business"}


def _get(url: str, params: dict | None = None, accept: str = "application/json", timeout: int = 180,
         delay: float = DELAY):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.load(r)
            time.sleep(delay)
            return data
        except Exception as e:  # noqa: BLE001 - retry rate limits and timeouts, then give up loudly
            if attempt == 3:
                raise
            log.warning("retry %s: %s", url[:90], e)
            time.sleep(10 * (attempt + 1))


def sparql(query: str) -> list[dict]:
    return _get(SPARQL, {"query": query, "format": "json"}, "application/sparql-results+json")["results"]["bindings"]


def _qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def _chunks(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def candidates(cfg: dict) -> tuple[dict[str, list[dict]], dict[str, str]]:
    """QID → reasons for inclusion (each with the Wikidata query it came from), and MITRE ATT&CK id → QID."""
    found: dict[str, list[dict]] = {}
    # dissolved (P576) or ended (P582) before 2000: historical, left out
    alive = ("FILTER NOT EXISTS { ?i wdt:P576 ?end . FILTER(YEAR(?end) < 2000) } "
             "FILTER NOT EXISTS { ?i wdt:P582 ?end2 . FILTER(YEAR(?end2) < 2000) }")
    # states and companies can be "designated as terrorist" too (by another state); they are not actors here.
    # Only states are excluded from the class queries: Wikidata files drug cartels and PMCs under "business".
    not_state_or_company = " ".join(f"FILTER NOT EXISTS {{ ?i wdt:P31/wdt:P279* wd:{c} . }}" for c in NOT_ACTORS)
    not_state = " ".join(f"FILTER NOT EXISTS {{ ?i wdt:P31/wdt:P279* wd:{c} . }}" for c in NOT_ACTORS if c != "Q4830453")
    enwiki = "?a schema:about ?i ; schema:isPartOf <https://en.wikipedia.org/> ."
    for cls, kind in cfg["classes"].items():
        q = f"SELECT DISTINCT ?i WHERE {{ ?i wdt:P31/wdt:P279* wd:{cls} . {enwiki} {alive} {not_state} }}"
        rows = sparql(q)
        log.info("class %s (%s): %d items", cls, kind, len(rows))
        for r in rows:
            found.setdefault(_qid(r["i"]["value"]), []).append(
                {"via": "class", "class": cls, "kind": kind,
                 "text": f"Wikidata: instance of (P31) {cls} or a subclass", "query": q})
    q = f"SELECT DISTINCT ?i WHERE {{ ?i wdt:P3461 ?by . {not_state_or_company} }}"
    for r in sparql(q):
        found.setdefault(_qid(r["i"]["value"]), []).append(
            {"via": "designation", "kind": "terror", "text": "Wikidata: designated as terrorist by (P3461)", "query": q})
    q = "SELECT ?i ?id WHERE { ?i wdt:P9025 ?id . }"
    attack_qids = {}
    for r in sparql(q):   # values are ATT&CK paths: "groups/G0007", "software/S0012", "techniques/T1583" …
        m = re.fullmatch(r"(?:groups/)?(G\d{4})", r["id"]["value"])
        if m:
            attack_qids[m.group(1)] = _qid(r["i"]["value"])
    return found, attack_qids


def _plain(name: str) -> str:
    return re.sub(r"\W+", "", name).casefold()


def link_attack_by_name(groups: list[dict], ents: dict, found: dict, attack_qids: dict) -> dict[str, tuple[str, str]]:
    """MITRE group → Wikidata cyber actor sharing one of its names, when exactly one such actor exists."""
    cyber = [q for q, reasons in found.items() if any(r["kind"] == "cyber" for r in reasons) and q in ents]
    by_name: dict[str, set] = {}
    for q in cyber:
        e = ents[q]
        names = [v["value"] for v in e.get("labels", {}).values()]
        names += [a["value"] for al in e.get("aliases", {}).values() for a in al]
        for n in names:
            by_name.setdefault(_plain(n), set()).add(q)
    linked = {}
    for g in groups:
        if g["id"] in attack_qids:
            continue
        for n in [g["name"], *g["aliases"]]:
            qs = by_name.get(_plain(n), set())
            if len(qs) == 1 and len(_plain(n)) >= 4:
                linked[g["id"]] = (next(iter(qs)), n)
                break
    return linked


def resolve_titles(titles: list[str], what: str = "seed") -> dict[str, str]:
    """English Wikipedia title → Wikidata QID (following redirects; several spellings may lead to one article)."""
    out = {}
    for chunk in _chunks(titles, 50):
        d = _get(WP_API, {"action": "query", "prop": "pageprops", "ppprop": "wikibase_item", "redirects": 1,
                          "titles": "|".join(chunk), "format": "json", "formatversion": 2})["query"]
        back: dict[str, set] = {}
        for n in d.get("normalized", []) + d.get("redirects", []):
            back.setdefault(n["to"], set()).update(back.get(n["from"], set()) | {n["from"]})
        for p in d["pages"]:
            if "pageprops" in p:
                for original in back.get(p["title"], set()) | {p["title"]}:
                    if original in chunk:
                        out[original] = p["pageprops"]["wikibase_item"]
    missing = set(titles) - set(out)
    if what == "seed":
        for t in sorted(missing):
            log.warning("seed %r: no Wikipedia article / Wikidata item – skipped", t)
    elif missing:
        log.info("%d %s without a Wikipedia article / Wikidata item (red links) – left out", len(missing), what)
    return out


def entities(qids: list[str], props: str, languages: list[str]) -> dict[str, dict]:
    out = {}
    for chunk in _chunks(sorted(qids), 50):
        d = _get(WD_API, {"action": "wbgetentities", "ids": "|".join(chunk), "props": props,
                          "languages": "|".join(languages), "sitefilter": "enwiki", "format": "json"})
        out.update({k: v for k, v in d.get("entities", {}).items() if "missing" not in v})
        log.info("wikidata entities %d/%d", len(out), len(qids))
    return out


def _claims(ent: dict, prop: str) -> list[dict]:
    return [c for c in ent.get("claims", {}).get(prop, []) if c["mainsnak"].get("datavalue")]


def _time(v: dict) -> str:
    y, m, d = v["time"][1:11].split("-")
    return {11: f"{y}-{m}-{d}", 10: f"{y}-{m}"}.get(v["precision"], y.lstrip("0") or y)


def wikipedia_leads(titles: list[str]) -> dict[str, dict]:
    """Lead section (plain text) and revision of each English Wikipedia article."""
    out = {}
    for chunk in _chunks(titles, 20):
        d = _get(WP_API, {"action": "query", "prop": "extracts|revisions", "exintro": 1, "explaintext": 1,
                          "exlimit": 20, "rvprop": "ids|timestamp", "titles": "|".join(chunk), "redirects": 1,
                          "format": "json", "formatversion": 2})["query"]
        back = {}
        for n in d.get("normalized", []) + d.get("redirects", []):
            back[n["to"]] = back.get(n["from"], n["from"])
        for p in d["pages"]:
            if p.get("missing"):
                continue
            rev = (p.get("revisions") or [{}])[0]
            text = re.sub(r"\n{2,}", "\n", (p.get("extract") or "").strip())
            out[back.get(p["title"], p["title"])] = {
                "title": p["title"], "extract": text[:1500] + ("…" if len(text) > 1500 else ""),
                "revision": rev.get("revid"), "revision_time": rev.get("timestamp"),
                "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(p["title"].replace(" ", "_")),
                "revision_url": f"https://en.wikipedia.org/w/index.php?oldid={rev.get('revid')}"}
        log.info("wikipedia leads %d/%d", len(out), len(titles))
    return out


def attack_groups() -> tuple[list[dict], dict]:
    bundle = _get(ATTACK_URL, timeout=600)
    groups, version = [], None
    for o in bundle["objects"]:
        if o["type"] == "x-mitre-collection":
            version = o.get("x_mitre_version")
        if o["type"] != "intrusion-set" or o.get("revoked") or o.get("x_mitre_deprecated"):
            continue
        ref = next(r for r in o["external_references"] if r.get("source_name") == "mitre-attack")
        desc = re.sub(r"\(Citation:[^)]*\)", "", o.get("description", ""))
        desc = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", desc)       # markdown links → text
        groups.append({"id": ref["external_id"], "url": ref["url"], "name": o["name"],
                       "aliases": [a for a in o.get("aliases", []) if a != o["name"]],
                       "description": " ".join(desc.split())[:1500], "modified": o.get("modified")})
    return groups, {"url": ATTACK_URL, "version": version}


def country_actors(cfg: dict, today: str) -> list[dict]:
    """Countries as actors: sovereign states (Q3624078) with an ISO code, plus the extra items in actors.yaml.

    Names are the Wikidata labels and aliases and the demonyms (P1549: "Russian", "Russe") in the report languages,
    so that "which countries' reports talk about which countries" can be counted like any other actor.
    """
    q = """SELECT DISTINCT ?i ?iso WHERE { ?i wdt:P31 wd:Q3624078 ; wdt:P297 ?iso .
           FILTER NOT EXISTS { ?i wdt:P576 ?end } }"""
    iso = {_qid(r["i"]["value"]): r["iso"]["value"] for r in sparql(q)}
    extra = (cfg.get("countries") or {}).get("extra") or {}
    iso.update(extra)
    ents = entities(list(iso), "labels|aliases|descriptions|claims|sitelinks/urls|info", LANGS)
    out = []
    for qid, e in ents.items():
        names = [{"name": v["value"], "lang": lg, "origin": "Wikidata label"} for lg, v in e.get("labels", {}).items()]
        names += [{"name": a["value"], "lang": lg, "origin": "Wikidata alias"}
                  for lg, al in e.get("aliases", {}).items() for a in al]
        for c in _claims(e, "P1549"):
            v = c["mainsnak"]["datavalue"]["value"]
            if v["language"] in LANGS:
                names.append({"name": v["text"], "lang": v["language"], "origin": "Wikidata demonym (P1549)"})
        names += [{"name": n, "lang": "", "origin": "added by hand in sources/actors.yaml"}
                  for n in ((cfg.get("countries") or {}).get("aliases") or {}).get(qid, [])]
        title = e.get("sitelinks", {}).get("enwiki", {}).get("title")
        out.append({
            "key": qid, "qid": qid, "kind": "country", "iso": iso[qid],
            "label": next((e["labels"][lg]["value"] for lg in ("en", "mul") if lg in e.get("labels", {})), qid),
            "description": e.get("descriptions", {}).get("en", {}).get("value", ""),
            "instance_of": [], "countries": [], "inception": None, "dissolved": None, "designations": [],
            "image": None, "names": names,
            "reasons": [{"via": "country", "kind": "country", "text": "Wikidata: instance of (P31) sovereign state (Q3624078) with an ISO code (P297)"
                         if qid not in extra else "Added by hand in sources/actors.yaml (countries: extra)"}],
            "wikidata": {"url": f"https://www.wikidata.org/wiki/{qid}", "revision": e.get("lastrevid"),
                         "revision_url": f"https://www.wikidata.org/w/index.php?title={qid}&oldid={e.get('lastrevid')}",
                         "retrieved": today},
            "wikipedia": title and {"title": title, "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
                                    "extract": "", "revision": None, "revision_url": None, "revision_time": None,
                                    "retrieved": today, "licence": "CC BY-SA 4.0"},
            "attack": None})
    return out


class _Cache:
    """A JSON file under data/gazetteer/ that keeps the results of a slow fetch stage between runs."""

    def __init__(self, name: str, refresh: bool = False):
        self.path = GAZETTEER.parent / name
        self.data = {} if refresh or not self.path.exists() else json.loads(self.path.read_text(encoding="utf-8"))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")


def _sparql_batches(make_query, items: list[str], size: int) -> list[dict]:
    """Run a VALUES query in batches; a batch that times out is retried item by item."""
    rows = []
    for chunk in _chunks(items, size):
        try:
            rows += sparql(make_query(chunk))
        except Exception as e:  # noqa: BLE001
            log.warning("batch of %d failed (%s); retrying one by one", len(chunk), e)
            for one in chunk:
                try:
                    rows += sparql(make_query([one]))
                except Exception as e2:  # noqa: BLE001
                    log.warning("  %s: %s", one, e2)
    return rows


def _kinds_of(qids: list[str], refresh: bool = False) -> tuple[set[str], set[str]]:
    """Which of these items are people (P31 human) and which are organisations (a class that is a subclass of
    organization, Q43229). Direct classes are read first; only the distinct classes climb the class tree."""
    kinds = _Cache("kinds.json", refresh)
    classes = _Cache("org_classes.json", refresh)
    todo = [q for q in qids if q not in kinds.data]
    p31: dict[str, set] = {}
    for r in _sparql_batches(lambda c: "SELECT ?i ?c WHERE { VALUES ?i { %s } ?i wdt:P31 ?c . }"
                             % " ".join(f"wd:{q}" for q in c), todo, 200):
        p31.setdefault(_qid(r["i"]["value"]), set()).add(_qid(r["c"]["value"]))
    new_classes = sorted({c for cs in p31.values() for c in cs} - set(classes.data) - {"Q5"})
    is_org = set()
    for r in _sparql_batches(lambda c: "SELECT DISTINCT ?c WHERE { VALUES ?c { %s } ?c wdt:P279* wd:Q43229 . }"
                             % " ".join(f"wd:{q}" for q in c), new_classes, 40):
        is_org.add(_qid(r["c"]["value"]))
    classes.data.update({c: c in is_org for c in new_classes})
    classes.save()
    for q in todo:
        cs = p31.get(q, set())
        kinds.data[q] = "human" if "Q5" in cs else "org" if any(classes.data.get(c) or c == "Q43229" for c in cs) else "other"
    kinds.save()
    humans = {q for q in qids if kinds.data.get(q) == "human"}
    orgs = {q for q in qids if kinds.data.get(q) == "org"}
    return humans, orgs


def connect(actors: list[dict], ents: dict, today: str, refresh: bool = False) -> tuple[list[dict], dict, list[dict]]:
    """Links between actors and the people/organisations around them (see rozvedka/connections.py).

    Returns (links, entities, people): every link with its source; label, description and Wikipedia article of
    each connected item; and the connected people, to be added to the actor index (full names only)."""
    by_key = {a["key"]: a for a in actors}
    qids = [a["qid"] for a in actors if a["qid"]]
    people_titles = {a["wikipedia"]["title"] for a in actors if a["kind"] == "person" and a.get("wikipedia")}
    titles = sorted({a["wikipedia"]["title"] for a in actors if a.get("wikipedia")})
    boxes = connections.fetch_infoboxes(lambda u, p: _get(u, p, delay=0.25), titles, WP_API, people_titles, delay=0,
                                        cache=GAZETTEER.parent / "infoboxes.json", refresh=refresh)
    link_titles = sorted({l["title"] for b in boxes.values() for l in b["links"]})
    title_qid = resolve_titles(link_titles, "infobox links") if link_titles else {}
    actor_by_title = {a["wikipedia"]["title"]: a["key"] for a in actors if a.get("wikipedia")}

    raw = []   # (actor side, other side, …) before filtering by kind of the other item
    for title, box in boxes.items():
        a = actor_by_title.get(title)
        for l in box["links"]:
            b = title_qid.get(l["title"])
            if not a or not b or b == a:
                continue
            raw.append({"a": a, "b": b, "a_says": l["relation"], "b_says": l["inverse"], "start": None, "end": None,
                        "role": None, "note": l["note"],
                        "source": {"type": "wikipedia", "article": title, "field": l["field"],
                                   "revision": box["revision"], "url": connections.wiki_url(title),
                                   "revision_url": f"https://en.wikipedia.org/w/index.php?oldid={box['revision']}",
                                   "retrieved": today}})
    cached = _Cache("incoming.json", refresh)
    missing = [q for q in qids if q not in cached.data]
    got, failed = connections.incoming(sparql, missing)
    for row in got:
        cached.data.setdefault(row["object"], []).append(row)
    for q in missing:
        if q not in failed:
            cached.data.setdefault(q, [])
        else:
            cached.data.pop(q, None)          # not cached: tried again on the next run
    cached.save()
    inc = [r for q in qids for r in cached.data.get(q, [])]
    # most notable per actor and relation; record how many there are in all
    groups: dict[tuple, list] = {}
    for r in inc:
        groups.setdefault((r["object"], r["prop"]), []).append(r)
    totals = {}
    for (obj, prop), lst in groups.items():
        lst.sort(key=lambda r: -r["sitelinks"])
        seen, kept = set(), []
        for r in lst:
            if r["subject"] not in seen:
                seen.add(r["subject"]); kept.append(r)
        totals[f"{obj}|{prop}"] = len(kept)
        groups[(obj, prop)] = kept[:connections.PER_RELATION]
    wd_rows = [r for lst in groups.values() for r in lst] + connections.outgoing(
        {q: e for q, e in ents.items() if q in by_key}, lambda v: _time(v) if v else None)
    for r in wd_rows:
        a_says, b_says = connections.RELATIONS[r["prop"]]
        raw.append({"a": r["subject"], "b": r["object"], "a_says": a_says, "b_says": b_says, "start": r["start"],
                    "end": r["end"], "role": r["role"], "note": "",
                    "source": {"type": "wikidata", "property": r["prop"], "statement": r["statement"],
                               "url": connections.statement_url(r["subject"], r["prop"]), "ref": r["ref"],
                               "stated_in": r["stated_in"], "retrieved": today}})
    others = sorted({x for r in raw for x in (r["a"], r["b"]) if x not in by_key})
    humans, orgs = _kinds_of(others, refresh)
    keep = humans | orgs | set(by_key)
    links = [r for r in raw if r["a"] in keep and r["b"] in keep and by_key.get(r["a"], {}).get("kind") != "country"
             and by_key.get(r["b"], {}).get("kind") != "country"]
    extra = sorted({x for r in links for x in (r["a"], r["b"]) if x not in by_key}
                   | {r["role"] for r in links if r["role"]} | {r["source"].get("stated_in") for r in links if r["source"].get("stated_in")})
    info = entities(extra, "labels|aliases|descriptions|sitelinks/urls|info", LANGS)
    label = lambda e, q: next((e["labels"][lg]["value"] for lg in ("en", "mul") if lg in e.get("labels", {})),  # noqa: E731
                              next(iter(e.get("labels", {}).values()), {}).get("value", q))
    ent_out = {}
    for q, e in info.items():
        t = e.get("sitelinks", {}).get("enwiki", {}).get("title")
        ent_out[q] = {"label": label(e, q), "description": e.get("descriptions", {}).get("en", {}).get("value", ""),
                      "wikipedia": connections.wiki_url(t) if t else None, "human": q in humans, "org": q in orgs}
    for r in links:
        if r["role"]:
            r["role"] = ent_out.get(r["role"], {}).get("label", r["role"])
        if r["source"].get("stated_in"):
            r["source"]["stated_in_label"] = ent_out.get(r["source"]["stated_in"], {}).get("label")
    # connected people become actors (found by their full names only)
    reasons: dict[str, list] = {}
    for r in links:
        for me, other, says in ((r["a"], r["b"], r["b_says"]), (r["b"], r["a"], r["a_says"])):
            if me in humans and me not in by_key and other in by_key:
                reasons.setdefault(me, []).append(
                    {"via": "connection", "kind": "person",
                     "text": f"Connected to {by_key[other]['label']}: {says} "
                             f"({'Wikipedia infobox' if r['source']['type'] == 'wikipedia' else 'Wikidata'})"})
    people = []
    for q, rs in reasons.items():
        e = info.get(q)
        if not e:
            continue
        names = [{"name": v["value"], "lang": lg, "origin": "Wikidata label"} for lg, v in e.get("labels", {}).items()]
        names += [{"name": a["value"], "lang": lg, "origin": "Wikidata alias"} for lg, al in e.get("aliases", {}).items() for a in al]
        t = e.get("sitelinks", {}).get("enwiki", {}).get("title")
        people.append({
            "key": q, "qid": q, "kind": "person", "connected": True, "label": ent_out[q]["label"],
            "description": ent_out[q]["description"], "instance_of": [], "countries": [], "inception": None,
            "dissolved": None, "designations": [], "image": None, "names": names, "reasons": rs[:5],
            "wikidata": {"url": f"https://www.wikidata.org/wiki/{q}", "revision": e.get("lastrevid"),
                         "revision_url": f"https://www.wikidata.org/w/index.php?title={q}&oldid={e.get('lastrevid')}",
                         "retrieved": today},
            "wikipedia": t and {"title": t, "url": connections.wiki_url(t), "extract": "", "revision": None,
                                "revision_url": None, "revision_time": None, "retrieved": today,
                                "licence": "CC BY-SA 4.0"},
            "attack": None})
    log.info("connections: %d links, %d connected people added", len(links), len(people))
    return links, {**ent_out, "_totals": totals}, people


def fetch(config: Path = CONFIG, out: Path = GAZETTEER, refresh: bool = False) -> dict:
    cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
    today = dt.date.today().isoformat()
    found, attack_qids = candidates(cfg)
    seeds = {s["wikipedia"]: s for s in cfg.get("seeds", [])}
    seed_qids = resolve_titles(list(seeds))
    for title, qid in seed_qids.items():
        found.setdefault(qid, []).append({"via": "seed", "kind": seeds[title].get("kind", "other"),
                                          "text": "Added by hand in sources/actors.yaml", "wikipedia": title})
    groups, attack_meta = attack_groups()
    log.info("MITRE ATT&CK %s: %d groups", attack_meta["version"], len(groups))
    for g in groups:
        if g["id"] in attack_qids:
            found.setdefault(attack_qids[g["id"]], []).append(
                {"via": "attack", "kind": "cyber", "text": f"MITRE ATT&CK group {g['id']} (Wikidata P9025)"})

    ents = entities(list(found), "labels|aliases|descriptions|claims|sitelinks/urls|info", LANGS)
    for gid, (qid, name) in link_attack_by_name(groups, ents, found, attack_qids).items():
        attack_qids[gid] = qid
        found[qid].append({"via": "attack", "kind": "cyber",
                           "text": f"MITRE ATT&CK group {gid}, linked by the shared name “{name}”"})
    # labels of the items the claims point to (classes, countries, designating authorities) + ISO codes of countries
    refs = set()
    for e in ents.values():
        for prop in ("P31", "P17", "P3461"):
            refs |= {c["mainsnak"]["datavalue"]["value"]["id"] for c in _claims(e, prop)}
    ref_ents = entities(list(refs), "labels|claims", ["en"])

    def ref_label(q):
        return ref_ents.get(q, {}).get("labels", {}).get("en", {}).get("value", q)

    def iso(q):
        c = _claims(ref_ents.get(q, {}), "P297")
        return c[0]["mainsnak"]["datavalue"]["value"] if c else None

    titles = {q: e["sitelinks"]["enwiki"]["title"] for q, e in ents.items() if "enwiki" in e.get("sitelinks", {})}
    leads = wikipedia_leads(sorted(set(titles.values())))
    by_attack = {g["id"]: g for g in groups}
    qid_of_attack = {a: q for a, q in attack_qids.items() if q in ents}

    actors = []
    for qid, e in ents.items():
        names = []
        for lang, lab in e.get("labels", {}).items():
            names.append({"name": lab["value"], "lang": lang, "origin": "Wikidata label"})
        for lang, al in e.get("aliases", {}).items():
            names += [{"name": a["value"], "lang": lang, "origin": "Wikidata alias"} for a in al]
        attack_id = next((a for a, q in qid_of_attack.items() if q == qid), None)
        if attack_id and attack_id in by_attack:
            g = by_attack[attack_id]
            names += [{"name": n, "lang": "", "origin": f"MITRE ATT&CK {attack_id}"} for n in [g["name"], *g["aliases"]]]
        seed = next((s for t, s in seeds.items() if seed_qids.get(t) == qid), None)
        if seed:
            names += [{"name": n, "lang": "", "origin": "added by hand in sources/actors.yaml"}
                      for n in seed.get("aliases", [])]
        reasons = found[qid]
        kind = next((r["kind"] for r in reasons if r["via"] == "seed"), None) or \
            next((r["kind"] for r in reasons if r["via"] == "attack"), None) or \
            ("person" if any(c["mainsnak"]["datavalue"]["value"]["id"] == "Q5" for c in _claims(e, "P31")) else None) or \
            next((r["kind"] for r in reasons if r["via"] == "class"), None) or reasons[0]["kind"]
        designations = []
        for c in _claims(e, "P3461"):
            by = c["mainsnak"]["datavalue"]["value"]["id"]
            q = c.get("qualifiers", {})
            start = next((_time(x["datavalue"]["value"]) for x in q.get("P580", []) if x.get("datavalue")), None)
            end = next((_time(x["datavalue"]["value"]) for x in q.get("P582", []) if x.get("datavalue")), None)
            designations.append({"by": by, "by_label": ref_label(by), "start": start, "end": end})
        first = lambda p: next((_time(c["mainsnak"]["datavalue"]["value"]) for c in _claims(e, p)), None)  # noqa: E731
        image = next((c["mainsnak"]["datavalue"]["value"] for c in _claims(e, "P154") + _claims(e, "P18")), None)
        lead = leads.get(titles.get(qid, ""))
        actors.append({
            "key": qid, "qid": qid, "kind": kind,
            "label": next((e["labels"][lg]["value"] for lg in ("en", "mul") if lg in e.get("labels", {})), None)
                     or next(iter(e.get("labels", {}).values()), {}).get("value", qid),
            "description": e.get("descriptions", {}).get("en", {}).get("value", ""),
            "instance_of": [{"id": i, "label": ref_label(i)} for i in
                            (c["mainsnak"]["datavalue"]["value"]["id"] for c in _claims(e, "P31"))],
            "countries": [{"id": i, "label": ref_label(i), "iso": iso(i)} for i in
                          (c["mainsnak"]["datavalue"]["value"]["id"] for c in _claims(e, "P17"))],
            "inception": first("P571"), "dissolved": first("P576"), "designations": designations,
            "image": f"https://commons.wikimedia.org/wiki/File:{urllib.parse.quote(image.replace(' ', '_'))}" if image else None,
            "names": names, "reasons": [{k: v for k, v in r.items() if k != "query"} for r in reasons],
            "wikidata": {"url": f"https://www.wikidata.org/wiki/{qid}", "revision": e.get("lastrevid"),
                         "revision_url": f"https://www.wikidata.org/w/index.php?title={qid}&oldid={e.get('lastrevid')}",
                         "retrieved": today},
            "wikipedia": lead and {**lead, "retrieved": today, "licence": "CC BY-SA 4.0"},
            "attack": attack_id and by_attack.get(attack_id) and {**by_attack[attack_id], "retrieved": today},
        })
    # MITRE groups without a Wikidata item are actors of their own
    for g in groups:
        if g["id"] in qid_of_attack:
            continue
        actors.append({
            "key": g["id"], "qid": None, "kind": "cyber", "label": g["name"], "description": "Threat group (MITRE ATT&CK)",
            "instance_of": [], "countries": [], "inception": None, "dissolved": None, "designations": [], "image": None,
            "names": [{"name": n, "lang": "", "origin": f"MITRE ATT&CK {g['id']}"} for n in [g["name"], *g["aliases"]]],
            "reasons": [{"via": "attack", "kind": "cyber", "text": f"MITRE ATT&CK group {g['id']}"}],
            "wikidata": None, "wikipedia": None, "attack": {**g, "retrieved": today}})
    links, link_entities, people = connect(actors, ents, today, refresh)
    have = {a["key"] for a in actors}
    actors += [p for p in people if p["key"] not in have]
    have = {a["key"] for a in actors}
    for c in country_actors(cfg, today):
        if c["key"] in have:      # a state that is also listed as an actor (e.g. a seed): keep one entry, as country
            actors = [a for a in actors if a["key"] != c["key"]]
        actors.append(c)
    data = {"retrieved": today, "config_hash": _hash(config),
            "sources": {"wikidata": {"sparql": SPARQL, "api": WD_API, "licence": "CC0"},
                        "wikipedia": {"api": WP_API, "licence": "CC BY-SA 4.0"},
                        "attack": {**attack_meta, "licence": "MITRE ATT&CK terms of use (attribution)"}},
            "actors": sorted(actors, key=lambda a: a["label"].lower()),
            "links": links, "entities": link_entities}
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    tmp.replace(out)
    kinds = {}
    for a in actors:
        kinds[a["kind"]] = kinds.get(a["kind"], 0) + 1
    return {"actors": len(actors), "kinds": kinds, "file": str(out)}


def _hash(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
