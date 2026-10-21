"""How are two entities connected? – the shortest chains of stated links between them in the network (rozvedka/ties.py).

A step costs the more, the weaker its layer (a co-mention in reports costs more than a sanctions-list link) and the more
links the entity it passes through has: a chain through Islamic State or the "Donetsk People's Republic" (hundreds of
links) says little, a chain through a small front company says much. So the cheapest chain is the most specific one,
not merely the shortest. Countries are left out unless asked for. After the best chain, the next ones may not reuse its
intermediate entities – alternative routes, not variations of one. Every step shows the links behind it with their
evidence; nothing here is a link of its own.
"""
import heapq
import math
import re

from . import actors, db, ties

BASE = {"us": 1.0, "uk": 1.0, "un": 1.0, "eu": 1.0, "ids": 1.0, "wanted": 1.0, "wikidata": 1.25, "wikipedia": 1.25, "attack": 1.25, "misp": 1.25, "publishers": 1.25, "gleif": 1.25, "events": 1.5, "wikitext": 1.5, "reports": 1.75}
HUB = 0.5               # per doubling of an intermediate entity's links
KIND_COST = {"tool": 1.5}   # system tools (net, PowerShell, Mimikatz) are used by everyone: sharing one says little
MAX_STEPS = 6
CHAINS = 5

_cache: dict = {"v": None}


def _graph() -> dict:
    """Adjacency of the whole network, kept until the database changes: {node: {other: [(tie id, layer)]}}."""
    v = db.version()
    if _cache["v"] != v:
        adj: dict[str, dict[str, list]] = {}
        with db.session() as con:
            ties.init()
            for tid, a, b, layer in con.execute("SELECT id, a, b, layer FROM ties"):
                adj.setdefault(a, {}).setdefault(b, []).append((tid, layer))
                adj.setdefault(b, {}).setdefault(a, []).append((tid, layer))
            ents = {r["id"]: dict(r) for r in con.execute("SELECT id, kind, label, actor FROM entities")}
        comp, sizes = {}, []                # connected parts: which part each entity is in, and their sizes
        for s in adj:
            if s in comp:
                continue
            comp[s], stack, n = len(sizes), [s], 0
            while stack:
                u = stack.pop()
                n += 1
                for w in adj[u]:
                    if w not in comp:
                        comp[w] = len(sizes)
                        stack.append(w)
            sizes.append(n)
        _cache.update(v=v, adj=adj, ents=ents, comp=comp, sizes=sizes)
    return _cache


def part(x: str) -> dict:
    """The connected part of the network an entity is in: its size and whether it is the largest one."""
    g = _graph()
    c = g["comp"].get(x)
    if c is None:
        return {"size": 1, "largest": False, "same": None}
    return {"size": g["sizes"][c], "largest": g["sizes"][c] == max(g["sizes"]), "id": c}


def penalty(degree: int) -> float:
    return HUB * math.log2(1 + degree)


def _shortest(g: dict, src: str, dst: str, layers: set, countries: bool, banned: set, banned_edges: set, skip=frozenset()):
    adj, ents = g["adj"], g["ents"]
    best = {src: 0.0}
    prev: dict[str, str] = {}
    heap = [(0.0, 0, src)]
    while heap:
        cost, steps, u = heapq.heappop(heap)
        if u == dst:
            path = [u]
            while path[-1] != src:
                path.append(prev[path[-1]])
            return cost, path[::-1]
        if cost > best.get(u, math.inf) or steps >= MAX_STEPS:
            continue
        extra = penalty(len(adj.get(u, ()))) + KIND_COST.get(ents.get(u, {}).get("kind"), 0.0) if u != src else 0.0
        for v, links in adj.get(u, {}).items():
            if v in banned or (u, v) in banned_edges:
                continue
            if v != dst and not countries and ents.get(v, {}).get("kind") == "country":
                continue
            base = min((BASE[layer] for tid, layer in links if layer in layers and tid not in skip), default=None)
            if base is None:
                continue
            c = cost + base + extra
            if c < best.get(v, math.inf):
                best[v], prev[v] = c, u
                heapq.heappush(heap, (c, steps + 1, v))
    return None


def chains(a: str, b: str, layers=None, countries: bool = False, n: int = CHAINS, connecting: bool = False) -> list[dict]:
    """Up to n chains from a to b, the most specific first; each the entities on it and the links of every step.
    `connecting`: only links that are a sign of a connection – no rivalries, no article sentences without a relation word."""
    g = _graph()
    if a not in g["ents"] or b not in g["ents"] or a == b:
        return []
    layers = {l for l in (layers or ties.LAYERS) if l in ties.LAYERS}
    found, banned, banned_edges = [], set(), set()
    skip = ties.not_a_tie_ids() if connecting else frozenset()
    while len(found) < n:
        r = _shortest(g, a, b, layers, countries, banned, banned_edges, skip)
        if not r:
            break
        cost, path = r
        found.append((cost, path))
        inner = path[1:-1]
        if inner:
            banned |= set(inner)
        else:                                       # a direct link: the next chain must go another way
            banned_edges |= {(a, b), (b, a)}
    ids = {tid for _, path in found for u, v in zip(path, path[1:]) for tid, layer in g["adj"][u][v] if layer in layers and tid not in skip}
    rows = {}
    if ids:
        with db.session() as con:
            marks = ",".join("?" * len(ids))
            rows = {r["id"]: ties._row(r) for r in con.execute(f"{ties.SELECT} {ties.FROM} WHERE t.id IN ({marks})", list(ids))}
    out = []
    for cost, path in found:
        nodes = []
        for x in path:
            e = g["ents"][x]
            nodes.append({"id": x, "label": e["label"], "kind": e["kind"], "href": ties.entity_url(x, e["actor"]),
                          "links": len(g["adj"].get(x, ())), "kind_name": ties.KINDS.get(e["kind"], e["kind"])})
        steps = []
        for u, v in zip(path, path[1:]):
            links = []
            for tid, layer in sorted(g["adj"][u][v], key=lambda x: BASE[x[1]]):
                if layer not in layers or tid in skip:
                    continue
                r = rows[tid]
                links.append({**r, "says": r["rel"] if r["a"] == u else r["back"], "forward": r["a"] == u})
            steps.append({"links": links, "layers": sorted({l["layer"] for l in links}, key=list(ties.LAYERS).index)})
        out.append({"nodes": nodes, "steps": steps, "cost": round(cost, 2), "n": len(steps),
                    "co_mention_only": [i for i, s in enumerate(steps) if s["layers"] == ["reports"]],
                    "hubs": [x for x in nodes[1:-1] if x["links"] >= 50]})
    return out


# ── choosing the two ends ──
REF = re.compile(r"\[([^\[\]]+)\]\s*$")


def suggest(q: str, limit: int = 12) -> list[dict]:
    """Entities for a name typed: actors by any of their names (rozvedka/actors.py suggest), others by their label."""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    g = _graph()
    out, seen = [], set()
    for r in actors.suggest(q):
        if r.get("near"):
            continue                        # "named often with the best match" – not a match for the name typed
        if r["key"] in g["ents"] and r["key"] not in seen:
            seen.add(r["key"])
            out.append(r["key"])
    with db.session() as con:
        for r in con.execute("""SELECT id FROM entities WHERE label LIKE ? ORDER BY length(label) LIMIT 200""", (f"%{q}%",)):
            if r["id"] not in seen:
                seen.add(r["id"])
                out.append(r["id"])
    named = [x for x in out if g["ents"][x]["actor"]]                  # actors in the order of the actor search
    others = sorted((x for x in out if not g["ents"][x]["actor"]), key=lambda x: -len(g["adj"].get(x, ())))
    return [_choice(x) for x in (named + others)[:limit]]


def _choice(x: str) -> dict:
    g = _graph()
    e = g["ents"][x]
    return {"id": x, "label": e["label"], "kind": e["kind"], "kind_name": ties.KINDS.get(e["kind"], e["kind"]),
            "links": len(g["adj"].get(x, ())), "value": f"{e['label']} [{x}]", "href": ties.entity_url(x, e["actor"])}


def resolve(text: str) -> tuple[dict | None, list[dict]]:
    """What the user typed → (the entity, or None and the candidates to choose from)."""
    text = (text or "").strip()
    if not text:
        return None, []
    g = _graph()
    m = REF.search(text)
    for x in ([m.group(1)] if m else []) + [text]:
        if x in g["ents"]:
            return _choice(x), []
    cands = suggest(text)
    exact = [c for c in cands if c["label"].casefold() == text.casefold()]
    if len(cands) == 1 or (len(exact) == 1 and g["ents"][exact[0]["id"]]["actor"]):
        return (exact or cands)[0], []
    return None, cands              # several entries carry the name (the lists are not merged yet): the user chooses
