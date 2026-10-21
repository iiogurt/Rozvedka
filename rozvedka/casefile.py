"""The case file: one shared board of pinned entities and how they are connected – no per-user state.

Pins (an actor, a sanctions entry, a company, a person …, each with an optional note) are kept in data/case_file.yaml:
written by the portal, editable by hand, never committed, and carried only by personal backups (rozvedka/dataset.py) –
a case file says what its owner is looking into. For every pair of pins the board shows the most specific chain of
stated links between them (rozvedka/paths.py), the entities that sit on the chains of several pairs (connectors), and
exports it all as Markdown with a citation for every step.
"""
import datetime as dt
import itertools
from urllib.parse import quote

import yaml

from . import config, db, paths, ties

MAX_PINS = 12            # 66 pairs at most: the chains stay quick enough on a Raspberry Pi
HEADER = """# Case file – entities pinned on the portal's Case file page (/case), with notes. Written by the portal; editable by hand.
# Kept for personal use: never committed, carried only by personal backups.
"""
_chains: dict = {"v": None, "pairs": {}}


def path():
    return config.DATA / "case_file.yaml"


def load(p=None) -> list[dict]:
    p = p or path()
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return [x for x in (raw.get("pins") or []) if isinstance(x, dict) and x.get("id")]


def save(pins: list[dict], p=None) -> None:
    p = p or path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(HEADER + yaml.safe_dump({"pins": pins}, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")


def pin(text: str, note: str = "") -> dict:
    """Pin what was typed or chosen (an entity id, "Name [id]" or a name that only one entity carries)."""
    ent, cands = paths.resolve(text)
    if not ent:
        return {"error": f"several entities are called “{text}” – choose one" if cands else f"nothing in the network is called “{text}”",
                "cands": cands}
    pins = load()
    if any(x["id"] == ent["id"] for x in pins):
        return {"exists": ent["label"]}
    if len(pins) >= MAX_PINS:
        return {"error": f"the case file holds at most {MAX_PINS} entities – remove one first"}
    pins.append({"id": ent["id"], "label": ent["label"], "added": dt.date.today().isoformat(), "note": " ".join(note.split())})
    save(pins)
    return {"added": ent["label"]}


def unpin(id_: str) -> None:
    save([x for x in load() if x["id"] != id_])


def set_note(id_: str, note: str) -> None:
    pins = load()
    for x in pins:
        if x["id"] == id_:
            x["note"] = note.strip()
    save(pins)


def clear() -> None:
    save([])


def merge(theirs: list[dict]) -> int:
    """Pins of an imported personal backup: those not here are added (up to MAX_PINS); a note fills an empty one."""
    ours = load()
    have = {x["id"]: x for x in ours}
    added = 0
    for x in theirs or []:
        if not isinstance(x, dict) or not x.get("id"):
            continue
        if x["id"] in have:
            if x.get("note") and not have[x["id"]].get("note"):
                have[x["id"]]["note"] = x["note"]
        elif len(ours) < MAX_PINS:
            ours.append(x)
            have[x["id"]] = x
            added += 1
    save(ours)
    return added


def _chain(a: str, b: str) -> dict | None:
    """The most specific chain between two pins, kept until the network changes."""
    v = db.version()
    if _chains["v"] != v:
        _chains.update(v=v, pairs={})
    key = tuple(sorted((a, b)))
    if key not in _chains["pairs"]:
        found = paths.chains(key[0], key[1], n=1, connecting=True)
        _chains["pairs"][key] = found[0] if found else None
    return _chains["pairs"][key]


def board() -> dict:
    """Pins with what the network knows about them, the chain of every pair, the pair grid and the connectors."""
    g = paths._graph()
    pins = []
    for x in load():
        known = x["id"] in g["ents"]
        e = paths._choice(x["id"]) if known else {"id": x["id"], "label": x.get("label") or x["id"], "kind": "", "links": 0,
                                                   "kind_name": "no longer in the network", "href": ""}
        pins.append({**e, "note": x.get("note") or "", "added": x.get("added"), "known": known})
    known = [p for p in pins if p["known"]]
    pairs, through = [], {}
    for a, b in itertools.combinations(known, 2):
        c = _chain(a["id"], b["id"])
        steps = len(c["nodes"]) - 1 if c else None
        pairs.append({"a": a, "b": b, "chain": c, "steps": steps, "link": f"/graph/path?a={quote(a['id'])}&b={quote(b['id'])}&connecting=1"})
        for n in (c["nodes"][1:-1] if c else []):
            through.setdefault(n["id"], {"node": n, "pairs": []})["pairs"].append(f"{a['label']} – {b['label']}")
    grid = {(p["a"]["id"], p["b"]["id"]): p for p in pairs}
    grid.update({(p["b"]["id"], p["a"]["id"]): p for p in pairs})
    pinned = {p["id"] for p in pins}
    connectors = sorted((t for k, t in through.items() if len(t["pairs"]) >= 2 and k not in pinned),
                        key=lambda t: (-len(t["pairs"]), t["node"]["label"]))
    pairs.sort(key=lambda p: (p["steps"] is None, p["steps"] or 0, p["chain"]["cost"] if p["chain"] else 0))
    return {"pins": pins, "pairs": pairs, "grid": grid, "connectors": connectors, "max": MAX_PINS,
            "linked": sum(1 for p in pairs if p["chain"]), "file": "data/case_file.yaml"}


def cite(link: dict) -> tuple[str, str]:
    """A step's evidence as (citation text, address) – the source, its reference or revision and the retrieval date."""
    e, layer = link.get("evidence") or {}, link["layer"]
    src = e.get("source") or {}
    if layer in ("us", "uk", "un", "eu"):
        return f"{e.get('list', layer.upper())} sanctions list, entry {e.get('ref', '')}".strip(", "), e.get("url", "")
    if layer == "wanted":
        who = "FBI" if e.get("list") == "FBI" else "Europe's Most Wanted"
        return f"{who} wanted notice “{e.get('notice', '')}”, retrieved {e.get('retrieved', '')}", e.get("url", "")
    if layer == "wikipedia":
        return (f"Wikipedia, “{src.get('article', '')}”, infobox field “{src.get('field', '')}”, revision {src.get('revision', '')}, "
                f"retrieved {src.get('retrieved', '')}"), e.get("url", "")
    if layer == "wikitext":
        sec = f", section “{e['section']}”" if e.get("section") else ""
        return (f"Wikipedia, “{e.get('article', '')}”{sec}, revision {e.get('revision', '')}, retrieved {e.get('retrieved', '')}",
                e.get("url", ""))
    if layer == "wikidata":
        return f"Wikidata, statement {src.get('property', '')}, retrieved {src.get('retrieved', '')}", e.get("url", "")
    if layer == "attack":
        return f"MITRE ATT&CK, retrieved {e.get('retrieved', '')}", e.get("url", "")
    if layer == "reports":
        return f"{e.get('docs', '')} reports of the library name both in one passage (a co-mention, not a stated link)", e.get("link", "")
    if layer == "icij":
        return (f"ICIJ Offshore Leaks Database ({e.get('source', '')}) – leaked records published by journalists, not official; "
                f"retrieved {e.get('retrieved', '')}"), e.get("url", "")
    if layer == "gleif":
        return (f"GLEIF Level 2 relationship record {e.get('type', '')} ({e.get('status', '')}"
                f"{', since ' + e['start'] if e.get('start') else ''}), LEI {e.get('lei', '')}, retrieved {e.get('retrieved', '')}"), e.get("url", "")
    if layer == "publishers":
        return f"publisher profile: {e.get('label', '')}", e.get("url", "")
    return ties.LAYERS[layer]["name"], e.get("url", "") or e.get("link", "")


def markdown(base: str) -> str:
    """The case file as Markdown: the pins with their notes, each pair's chain with the evidence of every step, the
    connectors – every statement with its source."""
    b = board()
    url = lambda u: (base + u) if u.startswith("/") else u
    out = [f"# Case file", "", f"Exported {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} from Rozvedka ({base}). "
           "A chain is a set of stated links, not a finding: read the evidence.", "", "## Pinned", ""]
    for p in b["pins"]:
        out.append(f"- **{p['label']}** – {p['kind_name']}, {p['links']} links ({url(p['href']) if p['href'] else p['id']})"
                   + (f"  \n  Note: {p['note']}" if p["note"] else ""))
    out += ["", "## How they are connected", ""]
    for pr in b["pairs"]:
        c = pr["chain"]
        out.append(f"### {pr['a']['label']} – {pr['b']['label']}")
        out.append("")
        if not c:
            out += ["No chain of stated links within the network's reach.", ""]
            continue
        out.append(f"{pr['steps']} step{'s' if pr['steps'] != 1 else ''}: " + " → ".join(n["label"] for n in c["nodes"])
                   + f" ([all chains]({url(pr['link'])}))")
        out.append("")
        for i, s in enumerate(c["steps"]):
            x, y = c["nodes"][i]["label"], c["nodes"][i + 1]["label"]
            for l in s["links"]:
                text, u = cite(l)
                quote = (l.get("evidence") or {}).get("quote")
                out.append(f"{i + 1}. {l['a_label']} *{l['rel']}* {l['b_label']} – {text}" + (f" <{url(u)}>" if u else "")
                           + (f"  \n   > {quote}" if quote else ""))
        if c["co_mention_only"]:
            out.append("")
            out.append("Steps resting only on co-mentions in reports: " + ", ".join(str(i + 1) for i in c["co_mention_only"]) + ".")
        out.append("")
    if b["connectors"]:
        out += ["## Connectors", "", "Entities on the chains of several pairs:", ""]
        for t in b["connectors"]:
            out.append(f"- **{t['node']['label']}** ({url(t['node']['href'])}) – {'; '.join(t['pairs'])}")
        out.append("")
    return "\n".join(out)
