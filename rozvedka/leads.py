"""Leads and brokers – what the network suggests but no source states. Hypotheses to check, never links.

Leads: two actors of the library that no report names together and no source links, but that share neighbours in the
stated network (every layer except co-mentions in reports – rozvedka/ties.py). Ranked by Adamic–Adar: each shared
neighbour counts 1 ÷ log(its number of links), so sharing a small front company says much more than sharing a hub.
Neighbours with more than HUB links are not counted (a parliament building or a ministry joins hundreds), nor shared malware,
tools and campaigns (alike toolkits are rozvedka/twins.py's subject); links that say two are rivals ("opposed to") are left out
– sharing an enemy is no sign of a connection. Each lead can be
reviewed – confirmed, rejected or unclear, with a note – and the verdict is kept in sources/lead_reviews.yaml.

Brokers: entities whose stated links reach actors of several kinds – state services, cyber groups, terrorist groups, armed
groups, organised crime – the facilitators and proxies between worlds that otherwise do not touch. Ranked by how evenly
they bridge: the number of links to the kind they reach least of their two strongest.
"""
import datetime as dt
import math
from pathlib import Path

import yaml

from . import actors, db, paths, ties
from .config import ROOT

HUB = 200
TOOLKIT = {"malware", "tool", "campaign"}   # shared software is Toolkit twins' business (rozvedka/twins.py), not a lead
MIN_SHARED = 2
DOMAINS = ("state", "cyber", "terror", "armed", "crime")
REVIEWS = ROOT / "sources" / "lead_reviews.yaml"
VERDICTS = {"confirmed": "Confirmed – a real connection", "rejected": "Rejected – coincidence or an error",
            "unclear": "Unclear – needs more"}
HEADER = """# Reviewed leads of the network (Network → Leads): two actors that share neighbours in the stated network but are
# never named together. verdict: confirmed | rejected | unclear; note: why, with a source where there is one.
# Written by the portal; edit by hand if needed.
"""

_cache: dict = {"v": None}


def _stated() -> dict:
    """The network without co-mentions: {node: {other: [layers]}}, kept until the database changes."""
    g = paths._graph()
    if _cache["v"] == g["v"]:
        return _cache
    with db.session() as con:
        rivals = {r[0] for r in con.execute("SELECT id FROM ties WHERE rel IN ('opposed to')")}
    adj: dict[str, dict[str, list]] = {}
    for u, nb in g["adj"].items():
        for v, links in nb.items():
            layers = sorted({layer for tid, layer in links if layer != "reports" and tid not in rivals})
            if layers:
                adj.setdefault(u, {})[v] = layers
    with db.session() as con:
        together = {(a, b) for a, b in con.execute("SELECT DISTINCT a, b FROM actor_pairs")}
    _cache.update(v=g["v"], adj=adj, ents=g["ents"], together=together)
    return _cache


def _is_actor(ents: dict, x: str) -> bool:
    e = ents.get(x) or {}
    return bool(e.get("actor")) and e.get("kind") != "country"


@db.cached
def ranking(kind: str = "", q: str = "") -> list[dict]:
    """All leads, strongest first: pairs of actors never named together and not linked, with shared stated neighbours."""
    c = _stated()
    adj, ents, together = c["adj"], c["ents"], c["together"]
    score: dict[tuple, float] = {}
    shared: dict[tuple, int] = {}
    for w, nb in adj.items():
        deg = len(nb)
        if deg < 2 or deg > HUB or ents[w]["kind"] in TOOLKIT:
            continue
        acts = sorted(x for x in nb if _is_actor(ents, x))
        for i, a in enumerate(acts):
            for b in acts[i + 1:]:
                score[(a, b)] = score.get((a, b), 0.0) + 1 / math.log(deg)
                shared[(a, b)] = shared.get((a, b), 0) + 1
    verdicts = reviews()
    q = q.strip().casefold()
    out = []
    for (a, b), s in score.items():
        if shared[(a, b)] < MIN_SHARED or b in adj.get(a, {}) or (a, b) in together or (b, a) in together:
            continue
        ea, eb = ents[a], ents[b]
        if kind and kind not in (ea["kind"], eb["kind"]):
            continue
        if q and q not in ea["label"].casefold() and q not in eb["label"].casefold():
            continue
        out.append({"a": a, "b": b, "a_label": ea["label"], "b_label": eb["label"], "a_kind": ea["kind"], "b_kind": eb["kind"],
                    "score": round(s, 2), "shared": shared[(a, b)], "link": f"/graph/leads/{a}/{b}",
                    "a_href": f"/actors/{a}", "b_href": f"/actors/{b}", "review": verdicts.get((a, b))})
    out.sort(key=lambda r: (-r["score"], r["a_label"]))
    return out


def of_actor(key: str, limit: int = 6) -> list[dict]:
    return [r for r in ranking() if key in (r["a"], r["b"])][:limit]


def detail(a: str, b: str) -> dict | None:
    """One lead: the shared neighbours, each with the links on both sides and their evidence."""
    a, b = sorted((a, b))
    c = _stated()
    adj, ents = c["adj"], c["ents"]
    if not (_is_actor(ents, a) and _is_actor(ents, b)) or a == b:
        return None
    common = sorted(set(adj.get(a, {})) & set(adj.get(b, {})), key=lambda w: len(adj[w]))

    def counted(w):
        return 2 <= len(adj[w]) <= HUB and ents[w]["kind"] not in TOOLKIT
    rows = []
    with db.session() as con:
        for w in common:
            deg = len(adj[w])
            sides = {}
            for x in (a, b):
                sides[x] = [ties._row(r, x) for r in con.execute(
                    f"""{ties.SELECT} {ties.FROM} WHERE ((t.a=? AND t.b=?) OR (t.a=? AND t.b=?)) AND t.layer != 'reports'
                        AND t.rel != 'opposed to'""",
                    (x, w, w, x))]
            e = ents[w]
            rows.append({"id": w, "label": e["label"], "kind": e["kind"], "kind_name": ties.KINDS.get(e["kind"], e["kind"]),
                         "href": ties.entity_url(w, e["actor"]), "links": deg, "counted": counted(w),
                         "weight": round(1 / math.log(deg), 2) if counted(w) else 0, "a": sides[a], "b": sides[b]})
    direct = b in adj.get(a, {})
    together = (a, b) in c["together"] or (b, a) in c["together"]
    return {"a": a, "b": b, "ea": {**ents[a], "id": a, "href": f"/actors/{a}"}, "eb": {**ents[b], "id": b, "href": f"/actors/{b}"},
            "common": rows, "counted": sum(1 for r in rows if r["counted"]), "score": round(sum(r["weight"] for r in rows), 2),
            "direct": direct, "together": together, "review": reviews().get((a, b)), "verdicts": VERDICTS, "hub": HUB}


# ── reviews ──
def _load(path: Path | None = None) -> list[dict]:
    path = path or REVIEWS
    if not path.exists():
        return []
    return [r for r in (yaml.safe_load(path.read_text(encoding="utf-8")) or []) if isinstance(r, dict)]


def reviews(path: Path | None = None) -> dict[tuple, dict]:
    return {tuple(sorted((r["a"], r["b"]))): r for r in _load(path)}


def record(a: str, b: str, verdict: str, note: str = "", path: Path | None = None) -> dict:
    if verdict not in VERDICTS:
        return {"error": "unknown verdict"}
    if detail(a, b) is None:
        return {"error": "not a lead between two actors"}
    a, b = sorted((a, b))
    path = path or REVIEWS
    rows = [r for r in _load(path) if tuple(sorted((r["a"], r["b"]))) != (a, b)]
    with db.session() as con:
        labels = dict(con.execute("SELECT key, label FROM actors WHERE key IN (?,?)", (a, b)).fetchall())
    rows.append({"a": a, "b": b, "labels": f"{labels.get(a, a)} – {labels.get(b, b)}", "verdict": verdict,
                 "note": " ".join(note.split())[:1000], "date": dt.date.today().isoformat()})
    path.write_text(HEADER + yaml.safe_dump(rows, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    return {"ok": True}


# ── brokers ──
@db.cached
def brokers(kind: str = "") -> list[dict]:
    """Entities whose stated links reach actors of two kinds or more (state, cyber, terror, armed, crime)."""
    c = _stated()
    adj, ents = c["adj"], c["ents"]
    out = []
    for x, nb in adj.items():
        e = ents[x]
        if e["kind"] == "country":
            continue
        counts = {d: 0 for d in DOMAINS}
        for v in nb:
            k = ents[v]["kind"]
            if k in counts and ents[v]["actor"]:
                counts[k] += 1
        reached = sorted((d for d in DOMAINS if counts[d]), key=lambda d: -counts[d])
        if len(reached) < 2 or (kind and kind not in reached):
            continue
        out.append({"id": x, "label": e["label"], "kind": e["kind"], "kind_name": ties.KINDS.get(e["kind"], e["kind"]),
                    "href": ties.entity_url(x, e["actor"]), "score": counts[reached[1]], "reached": len(reached),
                    "domains": [{"kind": d, "name": actors.KINDS[d], "n": counts[d],
                                 "link": ties.ties_url(entity=x, other_kind=d, group="stated")} for d in reached]})
    out.sort(key=lambda r: (-r["score"], -r["reached"], r["label"]))
    return out


def figures() -> list[tuple[str, int, str]]:
    """(label, number, link) for tools/check_links.py: leads' shared counts and brokers' counts against their lists."""
    out = [(f"lead {r['a_label']} / {r['b_label']}", r["shared"], r["link"]) for r in ranking()[:10]]
    for r in brokers()[:10]:
        out += [(f"broker {r['label']} → {d['kind']}", -d["n"], d["link"]) for d in r["domains"]]
    return out
