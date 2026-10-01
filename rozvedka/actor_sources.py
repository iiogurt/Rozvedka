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


def _get(url: str, params: dict | None = None, accept: str = "application/json", timeout: int = 180):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.load(r)
            time.sleep(DELAY)
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
    # states and companies can be "designated as terrorist" too (by another state); they are not actors here
    not_state_or_company = " ".join(f"FILTER NOT EXISTS {{ ?i wdt:P31/wdt:P279* wd:{c} . }}" for c in NOT_ACTORS)
    enwiki = "?a schema:about ?i ; schema:isPartOf <https://en.wikipedia.org/> ."
    for cls, kind in cfg["classes"].items():
        q = f"SELECT DISTINCT ?i WHERE {{ ?i wdt:P31/wdt:P279* wd:{cls} . {enwiki} {alive} {not_state_or_company} }}"
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


def resolve_titles(titles: list[str]) -> dict[str, str]:
    """English Wikipedia title → Wikidata QID (following redirects)."""
    out = {}
    for chunk in _chunks(titles, 50):
        d = _get(WP_API, {"action": "query", "prop": "pageprops", "ppprop": "wikibase_item", "redirects": 1,
                          "titles": "|".join(chunk), "format": "json", "formatversion": 2})["query"]
        back = {}
        for n in d.get("normalized", []) + d.get("redirects", []):
            back[n["to"]] = back.get(n["from"], n["from"])
        for p in d["pages"]:
            if "pageprops" in p:
                out[back.get(p["title"], p["title"])] = p["pageprops"]["wikibase_item"]
    missing = set(titles) - set(out)
    for t in sorted(missing):
        log.warning("seed %r: no Wikipedia article / Wikidata item – skipped", t)
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


def fetch(config: Path = CONFIG, out: Path = GAZETTEER) -> dict:
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
    data = {"retrieved": today, "config_hash": _hash(config),
            "sources": {"wikidata": {"sparql": SPARQL, "api": WD_API, "licence": "CC0"},
                        "wikipedia": {"api": WP_API, "licence": "CC BY-SA 4.0"},
                        "attack": {**attack_meta, "licence": "MITRE ATT&CK terms of use (attribution)"}},
            "actors": sorted(actors, key=lambda a: a["label"].lower())}
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
