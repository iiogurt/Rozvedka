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
CHOICES = {"stated": "Stated links (all but co-mentions)", "official": "Official lists only", "reference": "Reference data only",
           "all": "All, with co-mentions in reports"}


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


def rings(center: str, choice: str = "stated", countries: bool = False) -> dict | None:
    g = paths._graph()
    ents, adj = g["ents"], g["adj"]
    if center not in ents:
        return None
    layers = _layers(choice)
    rank = {k: i for i, k in enumerate(sorted(ties.LAYERS, key=lambda k: (paths.BASE.get(k, 2), list(ties.LAYERS).index(k))))}
    keep = lambda e: e != center and (countries or ents[e]["kind"] != "country")
    deg = lambda e: len(adj.get(e, {}))

    # ── the inner ring: every neighbour, its layers, the strongest one for its sector ──
    near = {}
    for other, links in adj.get(center, {}).items():
        ls = sorted({l for _t, l in links if l in layers}, key=rank.get)
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
            if other in near or not keep(other) or not any(l in layers for _t, l in links):
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
    group = {"stated": "stated", "official": "official", "reference": "reference"}.get(choice, "")
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
