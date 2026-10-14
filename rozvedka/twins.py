"""Toolkit twins – threat groups that work alike, by what MITRE ATT&CK says they use.

Each group of MITRE ATT&CK (rozvedka/techniques.py) has a toolkit: the techniques it uses and its software (malware and
tools). Two groups are compared by the share of their combined toolkit they have in common, every item weighted by how
rare it is (log of groups ÷ groups using it): sharing a custom implant says much, sharing "PowerShell" or "phishing
attachment" – used by a hundred groups – almost nothing. 1.0 = identical toolkits, 0 = nothing in common.

A similar toolkit is not a connection: groups copy each other, buy the same tools and are described by the same vendors.
It is a lead to read about (rozvedka/ties.py holds what sources state). CVE numbers that reports name near both groups
are shown beside it, not counted in it (a nearness in text, not a use).
"""
import json
import math

from . import db, techniques, ties

MIN_SHARED = 5          # a pair is listed when it shares at least this many techniques and programs

_cache: dict = {"v": None}


def _profiles() -> dict:
    """{group node id: {label, actor, techniques: set, software: set}} and the item weights; kept until data changes."""
    v = (db.version(), techniques.FILE.stat().st_mtime if techniques.FILE.exists() else 0)
    if _cache["v"] == v:
        return _cache
    cat = techniques._catalog()
    with db.session() as con:
        by_attack = {}
        for key, label, data in con.execute("SELECT key, label, data FROM actors WHERE json_extract(data, '$.attack.id') IS NOT NULL"):
            by_attack[json.loads(data)["attack"]["id"]] = (key, label)
    groups = cat.get("groups", {})

    def node(gid):
        return by_attack.get(gid, (gid, groups.get(gid, gid)))

    prof: dict[str, dict] = {}

    def get(gid):
        key, label = node(gid)
        return prof.setdefault(key, {"id": key, "attack": gid, "label": label, "actor": key if key != gid else None,
                                     "techniques": set(), "software": set()})

    for t, info in cat.get("techniques", {}).items():
        if info.get("retired"):
            continue
        for gid, _ in info.get("groups", []):
            get(gid)["techniques"].add(t)
    soft = cat.get("software", {})
    for src, rel, dst, _ in cat.get("relations", []):
        if rel == "uses" and src.startswith("G") and dst in soft:
            get(src)["software"].add(dst)
    n = len(prof) or 1
    df: dict[str, int] = {}
    for p in prof.values():
        for x in p["techniques"] | p["software"]:
            df[x] = df.get(x, 0) + 1
    weight = {x: math.log(n / c) for x, c in df.items()}
    _cache.update(v=v, prof=prof, weight=weight, df=df, n=n, soft=soft, cat=cat)
    return _cache


def _score(a: dict, b: dict, w: dict) -> tuple[float, set, set]:
    ia, ib = a["techniques"] | a["software"], b["techniques"] | b["software"]
    shared, union = ia & ib, ia | ib
    den = sum(w[x] for x in union)
    return (sum(w[x] for x in shared) / den if den else 0.0), shared & (a["techniques"]), shared & a["software"]


@db.cached
def ranking(limit: int | None = None, q: str = "") -> list[dict]:
    """The most alike pairs of groups (at least MIN_SHARED items in common), most alike first."""
    c = _profiles()
    prof, w = c["prof"], c["weight"]
    keys = sorted(prof)
    q = q.strip().casefold()
    out = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            pa, pb = prof[a], prof[b]
            if q and q not in pa["label"].casefold() and q not in pb["label"].casefold():
                continue
            s, st, ss = _score(pa, pb, w)
            if len(st) + len(ss) >= MIN_SHARED:
                out.append(_row(pa, pb, s, st, ss))
    out.sort(key=lambda r: -r["score"])
    return out[:limit] if limit else out


def _row(pa, pb, s, st, ss) -> dict:
    return {"a": pa["id"], "b": pb["id"], "a_label": pa["label"], "b_label": pb["label"], "a_actor": pa["actor"],
            "b_actor": pb["actor"], "score": round(s, 3), "techniques": len(st), "software": len(ss),
            "a_href": ties.entity_url(pa["id"], pa["actor"]), "b_href": ties.entity_url(pb["id"], pb["actor"]),
            "link": f"/graph/twins/{pa['id']}/{pb['id']}"}


def of_group(key: str, limit: int = 8) -> list[dict]:
    """The groups most alike one group – for its actor page."""
    c = _profiles()
    prof, w = c["prof"], c["weight"]
    if key not in prof:
        return []
    out = []
    for other, p in prof.items():
        if other == key:
            continue
        s, st, ss = _score(prof[key], p, w)
        if len(st) + len(ss) >= MIN_SHARED:
            out.append(_row(prof[key], p, s, st, ss))
    out.sort(key=lambda r: -r["score"])
    return out[:limit]


def pair(a: str, b: str) -> dict | None:
    """Two groups side by side: what they share (rarest first), what only one of them uses, CVEs named near both."""
    c = _profiles()
    prof, w, df, soft, cat = c["prof"], c["weight"], c["df"], c["soft"], c["cat"]
    if a not in prof or b not in prof or a == b:
        return None
    pa, pb = prof[a], prof[b]
    s, st, ss = _score(pa, pb, w)

    def tech(t):
        k = techniques.known(t) or {}
        return {"id": t, "name": (f"{k['parent']}: {k['name']}" if k.get("parent") else k.get("name", t)),
                "tactics": k.get("tactics", []), "groups": df[t], "weight": round(w[t], 2)}

    def sw(x):
        return {"id": x, "name": soft[x]["name"], "type": soft[x]["type"], "groups": df[x], "weight": round(w[x], 2),
                "href": f"/entity/{x}"}

    cves = []
    if pa["actor"] and pb["actor"]:
        with db.session() as con:
            cves = [r[0] for r in con.execute(
                """SELECT x.cve FROM actor_cves x JOIN actor_cves y ON y.cve=x.cve AND y.actor_key=?
                   WHERE x.actor_key=? GROUP BY x.cve ORDER BY x.cve""", (pb["actor"], pa["actor"]))]
    return {**_row(pa, pb, s, st, ss),
            "shared_techniques": sorted((tech(t) for t in st), key=lambda r: -r["weight"]),
            "shared_software": sorted((sw(x) for x in ss), key=lambda r: -r["weight"]),
            "only_a": {"techniques": len(pa["techniques"] - pb["techniques"]), "software": len(pa["software"] - pb["software"])},
            "only_b": {"techniques": len(pb["techniques"] - pa["techniques"]), "software": len(pb["software"] - pa["software"])},
            "cves": cves, "groups": c["n"], "meta": techniques.meta()}


def figures() -> list[tuple[str, int, str]]:
    """(label, number, link) of the Toolkit twins page, for tools/check_links.py: shared counts against the pair page."""
    out = []
    for r in ranking(10):
        out.append((f"twins {r['a_label']} / {r['b_label']}", r["techniques"] + r["software"], r["link"]))
    return out
