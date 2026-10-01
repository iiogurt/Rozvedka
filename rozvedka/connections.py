"""Connections between actors and the people and organisations around them – from Wikipedia and Wikidata.

Two public sources, each link keeping where it came from:
  - the infobox of the actor's English Wikipedia article (founder, leaders, key people, parent organisation,
    subsidiaries, allies …): article, infobox field and revision;
  - Wikidata statements (member of, member of political party, employer, affiliation, parent organisation, owned
    by, founded by, chairperson, director …), in both directions: statement and its cited references.

Used by `fetch-actors` (rozvedka/actor_sources.py). The connected people are added to the actor index so that a
report naming them can show who they are connected to.
"""
import json
import logging
import re
import time
import urllib.parse
from pathlib import Path

log = logging.getLogger("rozvedka.actors")

# Wikidata properties: (label from the subject, label from the object). Subject → object as on Wikidata.
RELATIONS = {
    "P463": ("member of", "members"),
    "P102": ("member of the party", "party members"),
    "P108": ("employed by", "employees"),
    "P1416": ("affiliated with", "affiliated"),
    "P241": ("serves in", "personnel"),
    "P749": ("parent organisation", "subsidiaries and units"),
    "P361": ("part of", "parts"),
    "P127": ("owned by", "owns"),
    "P112": ("founded by", "founded"),
    "P488": ("chaired by", "chair of"),
    "P1037": ("directed by", "director of"),
    "P169": ("chief executive", "chief executive of"),
    "P3320": ("board members", "board member of"),
}
# looked up in both directions; ranked by notability (number of Wikipedia language versions) and cut per actor
IN_PROPS = ["P463", "P102", "P108", "P1416", "P241", "P749", "P361", "P127", "P112", "P488", "P1037", "P169", "P3320"]
OUT_PROPS = IN_PROPS
PER_RELATION = 25            # most notable connections kept per actor and relation (the total is recorded too)
MIN_SITELINKS = 2            # Wikidata items in fewer Wikipedias are mostly bulk records (e.g. casualty lists)

# Wikipedia infobox fields (digits removed: leader1_name → leader_name) → (relation from the actor, from the other)
INFOBOX = {
    **{f: ("led by", "leader of") for f in (
        "leader", "leaders", "leader_name", "military_leader", "founding_leader", "chief_name", "chairman",
        "chairperson", "chair", "president", "president_name", "ceo", "director", "director_name", "head",
        "head_name", "commander", "commanders", "notable_commanders", "secretary_general", "general_secretary",
        "deputy_leader", "deputy_leader_name", "spokesperson", "leader_title")},
    **{f: ("founded by", "founder of") for f in ("founder", "founders", "founded_by")},
    **{f: ("key people", "key person in") for f in ("key_people", "notable_members", "key_members", "members")},
    **{f: ("parent organisation", "subsidiaries and units") for f in (
        "parent", "parent_organization", "parent_organisation", "parent_agency", "part_of", "parent_organizations")},
    **{f: ("subsidiaries and units", "parent organisation") for f in (
        "subsidiaries", "subsidiary", "child_agency", "divisions", "units", "youth_wing", "think_tank", "wing",
        "armed_wing", "political_wing", "student_wing", "women_wing", "branches")},
    **{f: ("allied with", "allied with") for f in ("allies", "affiliations", "affiliation", "partners")},
    **{f: ("opposed to", "opposed to") for f in ("opponents", "enemies", "rivals")},
    **{f: ("owned by", "owns") for f in ("owner", "owners")},
    **{f: ("predecessor", "successor") for f in ("predecessor", "preceding")},
    **{f: ("successor", "predecessor") for f in ("successor", "superseding")},
}
# people's infoboxes have their own fields ("predecessor" there is the previous holder of an office)
PERSON_INFOBOX = {
    **{f: ("member of the party", "party members") for f in ("party", "otherparty")},
    **{f: ("serves in", "personnel") for f in ("branch", "unit")},
    **{f: ("employed by", "employees") for f in ("employer",)},
    **{f: ("member of", "members") for f in ("organization", "organisation", "organizations", "organisations")},
}
_MARKUP = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")


# ── Wikipedia infoboxes ──
def infobox(wikitext: str) -> dict[str, str]:
    """First {{Infobox …}} of an article → {param: raw value}; '|' inside links and nested templates ignored."""
    i = wikitext.find("{{Infobox")
    if i < 0:
        i = wikitext.find("{{infobox")
    if i < 0:
        return {}
    depth, j, parts, start = 0, i, [], i + 2
    while j < len(wikitext):
        two = wikitext[j:j + 2]
        if two in ("{{", "[["):
            depth += 1; j += 2; continue
        if two in ("}}", "]]"):
            depth -= 1; j += 2
            if depth == 0:
                parts.append(wikitext[start:j - 2]); break
            continue
        if wikitext[j] == "|" and depth == 1:
            parts.append(wikitext[start:j]); start = j + 1
        j += 1
    out = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            out[re.sub(r"\d+", "", k.strip().lower().replace(" ", "_"))] = out.get(
                re.sub(r"\d+", "", k.strip().lower().replace(" ", "_")), "") + " " + v.strip()
    return out


_REF = re.compile(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", re.S | re.I)
_LINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
_NOTE = re.compile(r"\(([^()]{1,40})\)")


def infobox_links(wikitext: str, person: bool = False) -> list[dict]:
    """Links in the relation fields of the infobox: [{field, relation, inverse, title, text, note}]."""
    out, seen = [], set()
    fields = PERSON_INFOBOX if person else INFOBOX
    for field, value in infobox(wikitext).items():
        rel = fields.get(field)
        if not rel:
            continue
        value = _REF.sub("", value)
        for m in _LINK.finditer(value):
            title = m.group(1).strip()
            if ":" in title:          # File:, Category:, wikt: …
                continue
            if (field, title) in seen:
                continue
            seen.add((field, title))
            after = _MARKUP.sub(r"\1", value[m.end():m.end() + 80]).strip()
            note = _NOTE.match(after)
            out.append({"field": field, "relation": rel[0], "inverse": rel[1], "title": title,
                        "text": (m.group(2) or title).strip(), "note": note.group(1).strip() if note else ""})
    return out


def fetch_infoboxes(get, titles: list[str], api: str, people: set[str] = frozenset(), delay: float = 0.3,
                    cache: Path | None = None, refresh: bool = False) -> dict[str, dict]:
    """English Wikipedia title → {"links": [...], "revision": id} (lead section only).

    With `cache`, results are saved as they come and reused by the next run (unless `refresh`), so an
    interrupted fetch continues where it stopped."""
    out = {}
    if cache and cache.exists() and not refresh:
        out = {t: v for t, v in json.loads(cache.read_text(encoding="utf-8")).items() if t in set(titles)}
        log.info("infoboxes: %d from the cache, %d to fetch", len(out), len(set(titles) - set(out)))
    todo = [t for t in titles if t not in out]
    for n, title in enumerate(todo, 1):
        try:
            d = get(api, {"action": "parse", "page": title, "prop": "wikitext|revid", "section": 0, "redirects": 1,
                          "format": "json", "formatversion": 2})["parse"]
        except Exception as e:  # noqa: BLE001 - one missing article must not stop the fetch
            log.warning("infobox %r: %s", title, e)
            continue
        out[title] = {"links": infobox_links(d.get("wikitext", ""), title in people), "revision": d.get("revid"),
                      "resolved_title": d.get("title", title)}
        if n % 100 == 0:
            log.info("infoboxes %d/%d", n, len(todo))
            if cache:
                cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        time.sleep(delay)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def wiki_url(title: str) -> str:
    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))


# ── Wikidata ──
def _val(b, k):
    return b[k]["value"] if k in b else None


def _qid(uri):
    return uri.rsplit("/", 1)[-1]


def incoming(sparql, qids: list[str], batch: int = 40) -> tuple[list[dict], set[str]]:
    """Statements of other items pointing at these actors (members, employees, subsidiaries …), and the actors
    whose query failed (to be tried again next time)."""
    props = " ".join(f"wd:{p}" for p in IN_PROPS)
    rows, failed = [], set()
    for i in range(0, len(qids), batch):
        values = " ".join(f"wd:{q}" for q in qids[i:i + batch])
        q = f"""SELECT ?actor ?prop ?x ?st ?sl ?start ?end ?role ?ref ?statedin WHERE {{
          VALUES ?actor {{ {values} }} VALUES ?prop {{ {props} }}
          ?prop wikibase:claim ?p ; wikibase:statementProperty ?ps .
          ?x ?p ?st . ?st ?ps ?actor . ?x wikibase:sitelinks ?sl . FILTER(?sl >= {MIN_SITELINKS})
          OPTIONAL {{ ?st pq:P580 ?start }} OPTIONAL {{ ?st pq:P582 ?end }} OPTIONAL {{ ?st pq:P2868 ?role }}
          OPTIONAL {{ ?st prov:wasDerivedFrom ?r . OPTIONAL {{ ?r pr:P854 ?ref }} OPTIONAL {{ ?r pr:P248 ?statedin }} }}
        }}"""
        try:
            got = sparql(q)
        except Exception as e:  # noqa: BLE001 - a timed-out batch is retried one by one
            log.warning("incoming batch %d failed (%s); retrying per actor", i, e)
            got = []
            for one in qids[i:i + batch]:
                try:
                    got += sparql(q.replace(values, f"wd:{one}"))
                except Exception as e2:  # noqa: BLE001
                    log.warning("incoming %s: %s", one, e2)
                    failed.add(one)
        rows += got
        log.info("wikidata incoming links %d/%d actors", min(i + batch, len(qids)), len(qids))
    return [{"subject": _qid(_val(r, "x")), "object": _qid(_val(r, "actor")), "prop": _qid(_val(r, "prop")),
             "statement": _val(r, "st").rsplit("/", 1)[-1], "sitelinks": int(_val(r, "sl") or 0),
             "start": _date(_val(r, "start")), "end": _date(_val(r, "end")),
             "role": _qid(_val(r, "role")) if _val(r, "role") else None, "ref": _val(r, "ref"),
             "stated_in": _qid(_val(r, "statedin")) if _val(r, "statedin") else None} for r in rows], failed


def _date(v: str | None) -> str | None:
    """Wikidata time from SPARQL → 'YYYY-MM-DD'; "unknown value" comes back as an internal URI and is dropped."""
    return v[:10] if v and re.match(r"-?\d{4}", v) else None


def outgoing(ents: dict, claim_time) -> list[dict]:
    """Statements of the actors themselves pointing at other items (their parties, employers, founders …)."""
    out = []
    for qid, e in ents.items():
        for prop in OUT_PROPS:
            for c in e.get("claims", {}).get(prop, []):
                v = c["mainsnak"].get("datavalue", {}).get("value")
                if not isinstance(v, dict) or "id" not in v:
                    continue
                q = c.get("qualifiers", {})
                first = lambda p: next((x["datavalue"]["value"] for x in q.get(p, []) if x.get("datavalue")), None)  # noqa: E731
                refs = c.get("references", [])
                ref = next((s["datavalue"]["value"] for r in refs for s in r["snaks"].get("P854", []) if s.get("datavalue")), None)
                stated = next((s["datavalue"]["value"]["id"] for r in refs for s in r["snaks"].get("P248", []) if s.get("datavalue")), None)
                role = first("P2868")
                out.append({"subject": qid, "object": v["id"], "prop": prop, "statement": c.get("id"),
                            "start": claim_time(first("P580")), "end": claim_time(first("P582")),
                            "role": role["id"] if isinstance(role, dict) else None, "ref": ref, "stated_in": stated,
                            "sitelinks": None})
    return out


def statement_url(subject: str, prop: str) -> str:
    return f"https://www.wikidata.org/wiki/{subject}#{prop}"
