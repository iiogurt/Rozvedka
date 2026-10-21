"""Rings around one entity: its direct links on the inner ring, the entities two steps away on the outer ring, one sector
per layer of the network (rozvedka/ties.py), every label visible.

A well-connected actor has hundreds of links (Hezbollah: 305 direct, 3,210 at two steps), so the drawing shows a choice and
says what it left out:
- inner ring – at most INNER neighbours, those stated by most layers first, then actors of the reports, then the most
  specific (fewest links of their own); each sits in the sector of the strongest layer that states its link (official
  lists before reference data before co-mentions, as in rozvedka/paths.py);
- outer ring – at most OUTER entities linked to the shown inner neighbours, those linked to several of them first, hubs
  weighed down (½ per doubling of their links, as on Find a connection); each sits beside the neighbours it is linked to;
- the rest is counted per sector, and every count opens the list of links it counts.
Countries are left out unless asked for: nearly everything is linked to Russia or Ukraine somewhere.
"""
import math
from urllib.parse import quote

from . import paths, ties

INNER = 40
OUTER = 48
LABEL = 26              # characters of a label drawn; the full name is in its tooltip and in the tables
R1, R2 = 220, 400       # ring radii in the drawing (viewBox units)
SIZE = 610              # half the drawing's width: room for the outer labels
MIN_SECTOR = 0.12       # radians a sector with any neighbour gets at least
GAP = 0.035             # radians between sectors
CHOICES = {"connecting": "Links that connect (no rivalries, no bare article mentions)",
           "stated": "Stated links (all but co-mentions)", "official": "Official lists only", "reference": "Reference data only",
           "all": "All, with co-mentions in reports"}


def _uses(choice: str):
    """(tie id, layer) → whether the chosen sources count it. "connecting" also leaves out rivalries and article sentences
    without a relation word (ties.NOT_A_TIE, as on Leads and Brokers)."""
    layers = set(_layers(choice))
    if choice != "connecting":
        return lambda t, l: l in layers
    skip = ties.not_a_tie_ids()
    return lambda t, l: l in layers and t not in skip


def _layers(choice: str) -> list[str]:
    if choice == "all":
        return list(ties.LAYERS)
    if choice in ties.GROUPS:
        return [k for k, v in ties.LAYERS.items() if v["group"] == choice]
    return [k for k in ties.LAYERS if k != "reports"]


def _short(s: str) -> str:
    s = s or ""
    return s if len(s) <= LABEL else s[:LABEL - 1].rstrip() + "…"


def _place(angle: float, r: float) -> dict:
    """A point on a ring and its label: radial text, turned on the left half so that it never reads upside down."""
    x, y = r * math.cos(angle), r * math.sin(angle)
    deg = math.degrees(angle)
    left = math.cos(angle) < 0
    return {"x": round(x, 1), "y": round(y, 1), "rot": round(deg + 180 if left else deg, 1), "anchor": "end" if left else "start",
            "dx": -9 if left else 9}


def _spread(items: list[dict], slots: int) -> None:
    """Put the items on `slots` evenly spaced places of the circle, in the order of the angle each wants and each as near
    to it as possible (least squared distance, by dynamic programming over every starting point of the order)."""
    n = len(items)
    if not n:
        return
    m = max(slots, n)
    places = [-math.pi / 2 + 2 * math.pi * j / m for j in range(m)]
    dist = lambda a, b: ((a - b + math.pi) % (2 * math.pi) - math.pi) ** 2
    items.sort(key=lambda i: i["want"] % (2 * math.pi))
    best = None
    for s0 in range(n):                                   # which item takes the first place the order uses
        order = items[s0:] + items[:s0]
        # cost[i][j]: the first i items placed on places < j
        inf = float("inf")
        cost = [[inf] * (m + 1) for _ in range(n + 1)]
        pick = [[False] * (m + 1) for _ in range(n + 1)]
        for j in range(m + 1):
            cost[0][j] = 0.0
        for i in range(1, n + 1):
            for j in range(i, m + 1):
                skip, take = cost[i][j - 1], cost[i - 1][j - 1] + dist(order[i - 1]["want"], places[j - 1])
                cost[i][j], pick[i][j] = (take, True) if take <= skip else (skip, False)
        if best is None or cost[n][m] < best[0]:
            best = (cost[n][m], order, pick)
    _c, order, pick = best
    i, j = n, m
    while i:
        if pick[i][j]:
            order[i - 1]["angle"] = places[j - 1]
            i -= 1
        j -= 1


def rings(center: str, choice: str = "connecting", countries: bool = False) -> dict | None:
    g = paths._graph()
    ents, adj = g["ents"], g["adj"]
    if center not in ents:
        return None
    use = _uses(choice)
    rank = {k: i for i, k in enumerate(sorted(ties.LAYERS, key=lambda k: (paths.BASE.get(k, 2), list(ties.LAYERS).index(k))))}
    keep = lambda e: e != center and (countries or ents[e]["kind"] != "country")
    deg = lambda e: len(adj.get(e, {}))

    # ── the inner ring: every neighbour, its layers, the strongest one for its sector ──
    near = {}
    for other, links in adj.get(center, {}).items():
        ls = sorted({l for t, l in links if use(t, l)}, key=rank.get)
        if ls and keep(other):
            near[other] = {"id": other, "layers": ls, "sector": ls[0], "deg": deg(other), "n_ties": len(links)}
    ranked = sorted(near.values(), key=lambda n: (-len(n["layers"]), not ents[n["id"]]["actor"], n["deg"], ents[n["id"]]["label"]))
    shown = ranked[:INNER]
    shown_ids = {n["id"] for n in shown}

    # sectors in the order of the layers, as wide as their share of the shown neighbours (at least MIN_SECTOR)
    sectors = []
    for k in ties.LAYERS:
        allk = [n for n in near.values() if n["sector"] == k]
        if not allk:
            continue
        mine = [n for n in shown if n["sector"] == k]
        sectors.append({"layer": k, "name": ties.LAYERS[k]["name"], "group": ties.LAYERS[k]["group"], "nodes": mine,
                        "n": len(allk), "more": len(allk) - len(mine), "link": f"#sector-{k}", "ties": ties.ties_url(entity=center, layer=k),
                        "all": sorted(allk, key=lambda n: (n["id"] not in shown_ids, ents[n["id"]]["label"].casefold()))})
    total = sum(max(len(s["nodes"]), 1) for s in sectors) or 1
    free = 2 * math.pi - GAP * len(sectors)
    widths = [max(MIN_SECTOR, free * max(len(s["nodes"]), 1) / total) for s in sectors]
    scale = free / sum(widths) if widths else 1
    a = -math.pi / 2                                   # from the top, clockwise
    for s, w in zip(sectors, widths):
        w *= scale
        s["a0"], s["a1"] = a, a + w
        mid = a + w / 2
        s["label"] = _place(mid, R1 - 34)
        s["arc"] = _arc(a, a + w, R1 + 18)
        for i, n in enumerate(sorted(s["nodes"], key=lambda n: ents[n["id"]]["label"].casefold())):
            n["angle"] = a + w * (i + 0.5) / len(s["nodes"])
        a += w + GAP

    # ── the outer ring: entities linked to the shown inner neighbours ──
    far: dict[str, dict] = {}
    for n in shown:
        for other, links in adj.get(n["id"], {}).items():
            if other in near or not keep(other) or not any(use(t, l) for t, l in links):
                continue
            f = far.setdefault(other, {"id": other, "via": [], "deg": deg(other)})
            f["via"].append(n["id"])
    for f in far.values():
        f["score"] = len(f["via"]) / (1 + paths.HUB * math.log2(max(f["deg"], 1)))
    outer = sorted(far.values(), key=lambda f: (-f["score"], ents[f["id"]]["label"]))[:OUTER]
    angle_of = {n["id"]: n["angle"] for n in shown}
    for f in outer:
        sx = sum(math.cos(angle_of[v]) for v in f["via"])
        sy = sum(math.sin(angle_of[v]) for v in f["via"])
        f["want"] = f["angle"] = math.atan2(sy, sx)
    _spread(outer, OUTER)

    def node(n, r, ring):
        e = ents[n["id"]]
        return {**n, **_place(n["angle"], r), "ring": ring, "label": e["label"], "short": _short(e["label"]), "kind": e["kind"],
                "kind_name": ties.KINDS.get(e["kind"], e["kind"]), "actor": e["actor"], "href": ties.entity_url(n["id"], e["actor"])}

    inner_nodes = [node(n, R1, 1) for s in sectors for n in s["nodes"]]
    outer_nodes = [node(f, R2, 2) for f in outer]
    for f in outer_nodes:
        f["via_labels"] = sorted(ents[v]["label"] for v in f["via"])
    pos = {n["id"]: n for n in inner_nodes}
    edges = [{"a": center, "b": n["id"], "x1": 0, "y1": 0, "x2": n["x"], "y2": n["y"], "group": ties.LAYERS[n["sector"]]["group"],
              "many": len(n["layers"]) > 1} for n in inner_nodes]
    for f in outer_nodes:
        for v in f["via"]:
            p = pos[v]
            edges.append({"a": v, "b": f["id"], "x1": p["x"], "y1": p["y"], "x2": f["x"], "y2": f["y"], "group": "outer", "many": False})
    group = {"connecting": "connecting", "stated": "stated", "official": "official", "reference": "reference"}.get(choice, "")
    says: dict[str, set] = {}
    for t in ties.tie_list(entity=center, group=group, limit=100000):
        if t["other"] in near:
            says.setdefault(t["other"], set()).add(t["says"])

    def listed(n, drawn):                 # a row of the tables: every neighbour, drawn or not, with the way to its evidence
        e = ents[n["id"]]
        return {**n, "label": e["label"], "kind": e["kind"], "href": ties.entity_url(n["id"], e["actor"]), "drawn": drawn,
                "chain": f"/graph/path?a={quote(center)}&b={quote(n['id'])}{'&countries=1' if countries else ''}"}
    for n in inner_nodes:
        n["says"] = sorted(says.get(n["id"], ()))
    for sec in sectors:
        sec["all"] = [listed({**n, "says": sorted(says.get(n["id"], ()))}, n["id"] in shown_ids) for n in sec["all"]]
    drawn_far = {f["id"] for f in outer}
    far_all = [listed({**f, "via_labels": sorted(ents[v]["label"] for v in f["via"])}, f["id"] in drawn_far)
               for f in sorted(far.values(), key=lambda f: (-f["score"], ents[f["id"]]["label"]))]
    c = ents[center]
    return {"center": {"id": center, "label": c["label"], "kind": c["kind"], "kind_name": ties.KINDS.get(c["kind"], c["kind"]),
                       "href": ties.entity_url(center, c["actor"]), "actor": c["actor"]},
            "sectors": sectors, "inner": inner_nodes, "outer": outer_nodes, "edges": edges, "far": far_all,
            "counts": {"near": len(near), "shown": len(inner_nodes), "far": len(far), "outer": len(outer_nodes),
                       "countries": countries, "choice": choice},
            "size": SIZE, "r1": R1, "r2": R2, "links": ties.ties_url(entity=center)}


def _arc(a0: float, a1: float, r: float) -> str:
    """SVG path of a circle arc from angle a0 to a1 (clockwise)."""
    x0, y0, x1, y1 = r * math.cos(a0), r * math.sin(a0), r * math.cos(a1), r * math.sin(a1)
    big = 1 if a1 - a0 > math.pi else 0
    return f"M{x0:.1f},{y0:.1f} A{r},{r} 0 {big} 1 {x1:.1f},{y1:.1f}"


# ── the matrix of one entity's neighbourhood, ordered by communities ──
MATRIX = 60             # neighbours in the matrix: those with most links among themselves
CELL = 14               # a cell's size in the drawing
ROW_LABEL = 230         # room for the row names
COL_LABEL = 170         # room for the column names, turned


def louvain(nodes: list[str], weights: dict[tuple[str, str], float]) -> list[list[str]]:
    """Communities by modularity (Blondel et al. 2008): move each node to the neighbouring community that raises modularity
    most, merge the communities into nodes, repeat until nothing moves. Deterministic: nodes are visited in sorted order."""
    adj: dict[str, dict[str, float]] = {n: {} for n in nodes}
    for (a, b), w in weights.items():
        if a != b:
            adj[a][b] = adj[a].get(b, 0) + w
            adj[b][a] = adj[b].get(a, 0) + w
    members = {n: [n] for n in nodes}
    while True:
        m2 = sum(sum(v.values()) for v in adj.values())        # twice the total weight
        if not m2:
            break
        k = {n: sum(adj[n].values()) for n in adj}
        com = {n: n for n in adj}
        tot = dict(k)
        moved_any = False
        for _ in range(20):
            moved = False
            for n in sorted(adj):
                c0 = com[n]
                tot[c0] -= k[n]
                links: dict[str, float] = {}
                for o, w in adj[n].items():
                    if o != n:                                 # a merged community's own links are not a move
                        links[com[o]] = links.get(com[o], 0) + w
                best, gain = c0, links.get(c0, 0) - tot[c0] * k[n] / m2
                for c, w in sorted(links.items()):
                    g = w - tot[c] * k[n] / m2
                    if g > gain + 1e-12:
                        best, gain = c, g
                com[n] = best
                tot[best] += k[n]
                if best != c0:
                    moved = moved_any = True
            if not moved:
                break
        if not moved_any:
            break
        new_adj: dict[str, dict[str, float]] = {}
        new_members: dict[str, list[str]] = {}
        for n, c in com.items():
            new_members.setdefault(c, []).extend(members[n])
            row = new_adj.setdefault(c, {})
            for o, w in adj[n].items():                      # links inside stay as the new node's own (self) weight
                row[com[o]] = row.get(com[o], 0) + w
        adj, members = new_adj, new_members
    return sorted((sorted(v) for v in members.values()), key=lambda v: (-len(v), v))


def matrix(center: str, choice: str = "connecting", countries: bool = False) -> dict | None:
    g = paths._graph()
    ents, adj = g["ents"], g["adj"]
    if center not in ents:
        return None
    use = _uses(choice)
    rank = {k: i for i, k in enumerate(sorted(ties.LAYERS, key=lambda k: (paths.BASE.get(k, 2), list(ties.LAYERS).index(k))))}
    near = {o for o, links in adj.get(center, {}).items()
            if o != center and (countries or ents[o]["kind"] != "country") and any(use(t, l) for t, l in links)}
    # links among the neighbours, by pair: the layers that state them
    pairs: dict[tuple[str, str], list[str]] = {}
    for a in near:
        for b, links in adj.get(a, {}).items():
            if b in near and a < b:
                ls = sorted({l for t, l in links if use(t, l)}, key=rank.get)
                if ls:
                    pairs[(a, b)] = ls
    inside = {n: 0 for n in near}
    for a, b in pairs:
        inside[a] += 1
        inside[b] += 1
    chosen = sorted(near, key=lambda n: (-inside[n], -len(adj[n]), ents[n]["label"]))[:MATRIX]
    chosen_set = set(chosen)
    linked = [n for n in chosen if any((min(n, o), max(n, o)) in pairs for o in chosen_set if o != n)]
    lone = sorted((n for n in chosen if n not in set(linked)), key=lambda n: ents[n]["label"].casefold())
    sub = {p: ls for p, ls in pairs.items() if p[0] in chosen_set and p[1] in chosen_set}
    comms = louvain(linked, {p: float(len(ls)) for p, ls in sub.items()})
    deg_in = {n: 0 for n in chosen}
    for a, b in sub:
        deg_in[a] += 1
        deg_in[b] += 1
    order, groups = [], []
    for i, cm in enumerate(comms):
        cm = sorted(cm, key=lambda n: (-deg_in[n], ents[n]["label"].casefold()))
        internal = sum(1 for a, b in sub if a in cm and b in cm)
        groups.append({"i": i + 1, "start": len(order), "size": len(cm), "name": ents[cm[0]]["label"], "internal": internal,
                       "members": [{"id": n, "label": ents[n]["label"], "kind": ents[n]["kind"],
                                    "href": ties.entity_url(n, ents[n]["actor"]), "deg": deg_in[n]} for n in cm]})
        order += cm
    group_of = {m["id"]: gr["i"] for gr in groups for m in gr["members"]}
    rows = [{"id": n, "label": ents[n]["label"], "short": _short(ents[n]["label"]), "kind": ents[n]["kind"],
             "href": ties.entity_url(n, ents[n]["actor"]), "group": group_of[n], "deg": deg_in[n], "y": i * CELL}
            for i, n in enumerate(order)]
    idx = {n: i for i, n in enumerate(order)}
    cells, links = [], []
    for (a, b), ls in sorted(sub.items(), key=lambda x: (idx[x[0][0]], idx[x[0][1]])):
        grp = ties.LAYERS[ls[0]]["group"]
        chain = f"/graph/path?a={quote(a)}&b={quote(b)}"
        for r, c in ((a, b), (b, a)):
            cells.append({"x": idx[c] * CELL, "y": idx[r] * CELL, "group": grp, "many": len(ls) > 1, "chain": chain,
                          "title": f"{ents[r]['label']} – {ents[c]['label']}: {', '.join(ls)}",
                          "inside": group_of[a] == group_of[b]})
        links.append({"a": ents[a]["label"], "b": ents[b]["label"], "a_href": ties.entity_url(a, ents[a]["actor"]),
                      "b_href": ties.entity_url(b, ents[b]["actor"]), "layers": ls, "chain": chain, "group": grp})
    links.sort(key=lambda l: (l["a"].casefold(), l["b"].casefold()))
    c = ents[center]
    n = len(order)
    return {"center": {"id": center, "label": c["label"], "kind": c["kind"], "href": ties.entity_url(center, c["actor"])},
            "rows": rows, "cells": cells, "groups": groups, "links": links,
            "lone": [{"id": x, "label": ents[x]["label"], "kind": ents[x]["kind"], "href": ties.entity_url(x, ents[x]["actor"])}
                     for x in lone],
            "counts": {"near": len(near), "pairs": len(pairs), "chosen": len(chosen), "shown": n, "shown_pairs": len(sub),
                       "countries": countries, "choice": choice},
            "cell": CELL, "side": n * CELL, "row_label": ROW_LABEL, "col_label": COL_LABEL}
