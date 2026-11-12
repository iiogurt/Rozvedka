"""Jump to anything: what was typed, looked up among the things the library holds – pages of the portal, countries,
agencies, actors, topics, reports by title and the network's other entities – each answer the thing's own page.

Names only, no full text (the search box does that): it has to answer while typing, on a Raspberry Pi."""
from . import actors, countries, db, nav, topics, trends

LIMIT = 5               # answers per kind
MIN_CHARS = 2
# kind: (heading, the menu glyph it wears)
KINDS = {"page": ("Pages", ""), "country": ("Countries", "countries"), "agency": ("Agencies", "agencies"),
         "actor": ("Actors", "actors"), "topic": ("Topics", "topics"), "report": ("Reports", "reports"),
         "entity": ("Network", "network")}


def _rank(q: str, label: str) -> int:
    """How well a name answers what was typed: the whole name, its start, the start of a word, or somewhere in it."""
    name = topics.normalize(label or "")
    if name == q:
        return 0
    if name.startswith(q):
        return 1
    return 2 if f" {q}" in name else 3


def _best(q: str, rows: list[dict], limit: int) -> list[dict]:
    # a thing found by another of its names comes after one found by the name shown
    return sorted(rows, key=lambda r: (_rank(q, r.get("match") or r["label"]) + (1 if r.get("match", r["label"]) != r["label"] else 0),
                                       -(r.get("weight") or 0), len(r["label"])))[:limit]


def find(q: str, limit: int = LIMIT) -> dict:
    """{"q", "groups": [{"kind", "name", "glyph", "items": [{"label", "sub", "url"}]}]} – only kinds with an answer."""
    typed = (q or "").strip()[:200]
    fq = topics.normalize(typed).strip()
    out = {"q": typed, "groups": []}
    if len(fq) < MIN_CHARS:
        return out
    like = "%" + typed.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"     # typed signs are no wildcards
    found: dict[str, list[dict]] = {}
    found["page"] = [{"label": label, "sub": f"{group} · {blurb}", "url": link}
                     for _key, group, _hub, items in nav.GROUPS for label, link, _more, blurb in items
                     if fq in topics.normalize(label)]
    tax = topics.taxonomy()["topics"]
    found["topic"] = [{"label": t["name"], "sub": t.get("category_name", ""), "url": f"/topics/{k}"}
                      for k, t in tax.items() if fq in topics.normalize(t["name"])]
    names = countries.names()
    with db.session() as con:
        actors.init()
        have = {r[0] for r in con.execute("SELECT DISTINCT country FROM sources WHERE active=1")}
        found["country"] = [{"label": names.get(c, c), "sub": c, "url": f"/countries/{c}", "country": c} for c in have
                            if fq in topics.normalize(names.get(c, c)) or fq == c.lower()]
        found["agency"] = [
            {"label": r["agency"], "match": r["agency"] if fq in topics.normalize(r["agency"]) else (r["name_en"] or r["name_local"]),
             "sub": f"{r['country']} · {r['name_en'] or r['name_local'] or ''}", "url": f"/agency/{r['id']}", "country": r["country"]}
            for r in con.execute("""SELECT id, country, agency, name_en, name_local FROM sources
                                    WHERE active=1 AND (agency LIKE ? ESCAPE '\\' OR name_en LIKE ? ESCAPE '\\' OR name_local LIKE ? ESCAPE '\\')""", (like,) * 3)]
        found["actor"] = [
            {"label": r["label"], "match": r["label"] if fq in topics.normalize(r["label"]) else r["alias"], "weight": r["n"],
             "sub": (f"also “{r['alias']}” · " if r["alias"] and fq not in topics.normalize(r["label"]) else "")
                    + actors.KINDS.get(r["kind"], r["kind"]) + (f" · in {r['n']} reports" if r["n"] else ""),
             "url": f"/actors/{r['key']}"}
            for r in con.execute(
                """WITH m AS (SELECT a.key, MIN(n.name) alias FROM actors a
                              LEFT JOIN actor_names n ON n.actor_key=a.key AND n.status='used' AND n.name LIKE ? ESCAPE '\\'
                              WHERE a.kind != 'country' AND (a.label LIKE ? ESCAPE '\\' OR n.name IS NOT NULL) GROUP BY a.key)
                   SELECT a.key, a.label, a.kind, m.alias, (SELECT COUNT(*) FROM doc_actors da WHERE da.actor_key=a.key) n
                   FROM m JOIN actors a ON a.key=m.key""", (like, like))]
        found["report"] = [
            {"label": r["title"], "weight": r["year"] or 0, "sub": f"{r['agency']} · {r['country']} · {r['year'] or 'undated'}",
             "url": f"/report/{r['id']}", "country": r["country"]}
            for r in con.execute(f"""SELECT d.id, d.title, d.year, s.agency, s.country FROM documents d JOIN sources s ON s.id=d.source_id
                                     WHERE {trends.LISTED} AND d.title LIKE ? ESCAPE '\\' ORDER BY d.year DESC LIMIT 200""", (like,))]
        try:
            rows = con.execute("""SELECT e.id, e.label, e.kind FROM entities e WHERE e.actor IS NULL AND e.label LIKE ? ESCAPE '\\'
                                  ORDER BY length(e.label) LIMIT 60""", (like,)).fetchall()
        except db.sqlite3.OperationalError:                 # the network is not built yet
            rows = []
        from . import ties
        found["entity"] = [{"label": r["label"], "sub": ties.KINDS.get(r["kind"], r["kind"]), "url": f"/entity/{r['id']}"} for r in rows]
    for kind, (name, glyph) in KINDS.items():
        items = _best(fq, found.get(kind, []), limit)
        if items:
            out["groups"].append({"kind": kind, "name": name, "glyph": glyph,
                                  "items": [{k: v for k, v in it.items() if k in ("label", "sub", "url", "country")} for it in items]})
    return out
