"""Security vendors' names for the same threat group – the MISP threat-actor galaxy (CC0), a community catalogue.

APT28 is "Fancy Bear" to CrowdStrike, "Forest Blizzard" (formerly STRONTIUM) to Microsoft, "Sofacy" to Kaspersky, "Pawn Storm"
to Trend Micro, "UAC-0001" to CERT-UA. Reports use any of these. `fetch-misp` downloads the galaxy into
data/gazetteer/misp_actors.json; each of its groups is tied to an actor of the gazetteer when its synonyms carry the actor's
MITRE ATT&CK number (G0007), or else when its name is exactly one actor's name. The synonyms of a tied group then become
names of that actor for the report matching (with all the usual rules: a name shared with another actor, too short or a
generic word is not used – see the Actor names page), and MISP's statements that two groups are similar or overlap become
links of the network (layer "misp", with MISP's stated likelihood). Nothing here calls out except `fetch`.
"""
import datetime as dt
import json
import re
from functools import lru_cache

from . import actor_sources, sanctions
from .config import DATA

FILE = DATA / "gazetteer" / "misp_actors.json"
URL = "https://raw.githubusercontent.com/MISP/misp-galaxy/main/clusters/threat-actor.json"
PAGE = "https://github.com/MISP/misp-galaxy"
LICENSE = "CC0 1.0"
ATTACK_ID = re.compile(r"^G\d{4}$")
RELATED = {"similar": ("similar to", "similar to"), "overlaps": ("overlaps with", "overlaps with"),
           "linked-to": ("linked to", "linked to"), "associated-with": ("associated with", "associated with"),
           "related-to": ("related to", "related to"), "part-of": ("part of", "has as part")}
ORIGIN = "MISP threat-actor galaxy (CC0)"


def fetch() -> dict:
    d = actor_sources._get(URL, timeout=300)
    clusters = []
    for v in d.get("values", []):
        m = v.get("meta") or {}
        clusters.append({"uuid": v["uuid"], "value": v["value"], "synonyms": [s for s in m.get("synonyms", []) if s],
                         "country": m.get("country"), "sponsor": m.get("cfr-suspected-state-sponsor"),
                         "refs": (m.get("refs") or [])[:6], "description": (v.get("description") or "")[:400],
                         "related": [{"uuid": r["dest-uuid"], "type": r.get("type"),
                                      "likelihood": next((t.split("=", 1)[1].strip('"') for t in r.get("tags", [])
                                                          if t.startswith("estimative-language:likelihood")), "")}
                                     for r in v.get("related", []) if r.get("type") in RELATED]})
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({"meta": {"version": d.get("version"), "retrieved": dt.date.today().isoformat(), "url": URL,
                                         "page": PAGE, "license": LICENSE}, "clusters": clusters}, ensure_ascii=False),
                    encoding="utf-8")
    _stored.cache_clear()
    return {"groups": len(clusters), "synonyms": sum(len(c["synonyms"]) for c in clusters),
            "relations": sum(len(c["related"]) for c in clusters), "version": d.get("version")}


@lru_cache(maxsize=1)
def _stored(mtime: float) -> dict:
    return json.loads(FILE.read_text(encoding="utf-8"))


def stored() -> dict:
    return _stored(FILE.stat().st_mtime) if FILE.exists() else {"meta": None, "clusters": []}


def tie_to_actors(gaz_actors: list[dict]) -> dict[str, tuple[str, str]]:
    """MISP group uuid → (actor key, how): by the ATT&CK number among its synonyms, else by a name only one actor has."""
    by_attack = {(a.get("attack") or {}).get("id"): a["key"] for a in gaz_actors if (a.get("attack") or {}).get("id")}
    names: dict[str, set] = {}
    for a in gaz_actors:
        if a["kind"] in ("person", "country"):
            continue
        for n in a["names"]:
            names.setdefault(sanctions.normalise(n["name"]), set()).add(a["key"])
    out = {}
    for c in stored()["clusters"]:
        ids = [s for s in c["synonyms"] if ATTACK_ID.match(s)]
        if ids and ids[0] in by_attack:
            out[c["uuid"]] = (by_attack[ids[0]], f"ATT&CK {ids[0]} among its synonyms")
            continue
        keys = names.get(sanctions.normalise(c["value"]), set())
        if len(keys) == 1:
            out[c["uuid"]] = (next(iter(keys)), f"its name “{c['value']}”")
    return out


def distinctive(name: str) -> bool:
    """A vendor's one-word name is used only when it cannot be an ordinary word: with a digit (APT12, TA422, UNC2452) or an
    all-capital code name of five letters or more (STRONTIUM). "Pioneer", "Axiom" or "Buckeye" are left out."""
    words = name.split()
    if len(words) > 1:
        return True
    w = words[0]
    return bool(re.search(r"\d", w) and re.search(r"[A-Za-z]", w)) or (w.isupper() and len(w) >= 5)


def extra_names(gaz_actors: list[dict]) -> dict[str, list[dict]]:
    """actor key → names from the MISP groups tied to it (a synonym two groups share is left out)."""
    tied = tie_to_actors(gaz_actors)
    clusters = {c["uuid"]: c for c in stored()["clusters"]}
    owners: dict[str, set] = {}
    for c in clusters.values():
        for s in [c["value"], *c["synonyms"]]:
            owners.setdefault(sanctions.normalise(s), set()).add(c["uuid"])
    out: dict[str, list] = {}
    for uuid, (key, _) in tied.items():
        c = clusters[uuid]
        for s in [c["value"], *c["synonyms"]]:
            if ATTACK_ID.match(s) or len(s) < 4 or len(owners[sanctions.normalise(s)]) > 1 or not distinctive(s):
                continue
            out.setdefault(key, []).append({"name": s, "lang": "", "origin": f"{ORIGIN}: {c['value']}"})
    return out


def with_names(gaz: dict) -> dict:
    """The gazetteer with the vendors' names added to the actors they belong to."""
    if not stored()["clusters"]:
        return gaz
    extra = extra_names(gaz["actors"])
    owner: dict[str, set] = {}            # a vendor's name for one group that is another actor's own name ("APT38" for
    for a in gaz["actors"]:               # Lazarus) would take that name away from it: left out
        for n in a["names"]:
            owner.setdefault(sanctions.normalise(n["name"]), set()).add(a["key"])
    for a in gaz["actors"]:
        have = {sanctions.normalise(n["name"]) for n in a["names"]}
        extra[a["key"]] = [n for n in extra.get(a["key"], []) if not owner.get(sanctions.normalise(n["name"]), set()) - {a["key"]}]
        for n in extra.get(a["key"], []):
            if sanctions.normalise(n["name"]) not in have:
                a["names"].append(n)
                have.add(sanctions.normalise(n["name"]))
    return gaz
