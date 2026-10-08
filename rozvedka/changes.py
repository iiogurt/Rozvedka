"""What a new edition of a report series says that the previous one did not: topics that appear, disappear, rise or
fall, and actors that are new, dropped or named more often – each with the passage of the newer edition (or, for
dropped ones, of the older) and a link to the page. One file per year, as on the series page (series.detail)."""
import json

from . import actors, db, series, topics

PASSAGES = 40       # new / dropped actors shown with a passage each; the rest is counted, never hidden silently
MIN_RISE = 2        # an actor counts as "named more / less" from this many mentions of difference


def _topics(con, doc_id: int, tax: dict) -> dict[str, dict]:
    return {r["topic"]: {"score": r["score"], "hits": r["hits"], "terms": json.loads(r["terms"] or "[]")}
            for r in con.execute("SELECT * FROM doc_topics WHERE doc_id=?", (doc_id,))
            if not tax.get(r["topic"], {}).get("meta")}


def _actors(con, doc_id: int, own: set[str]) -> dict[str, dict]:
    """Actors of one report as on the report page: no countries, not the agency itself, not before founding."""
    out = {}
    for r in con.execute(f"""SELECT da.actor_key, da.hits, da.spans, a.label, a.kind FROM doc_actors da
                             JOIN actors a ON a.key=da.actor_key JOIN documents d ON d.id=da.doc_id
                             WHERE da.doc_id=? AND a.kind != 'country' AND {actors.NOT_BEFORE_FOUNDED}
                             ORDER BY da.hits DESC, a.label""", (doc_id,)):
        if r["label"].casefold() not in own:
            out[r["actor_key"]] = dict(r)
    return out


def _passage(con, doc_id: int, spans: str | None) -> dict:
    if not spans:
        return {}
    body = (con.execute("SELECT body FROM doc_text WHERE rowid=?", (doc_id,)).fetchone() or [""])[0] or ""
    ix = con.execute("SELECT pages FROM doc_index WHERE doc_id=?", (doc_id,)).fetchone()
    s, e = json.loads(spans)[0]
    return {**actors._snippet(body, s, e),
            "page": topics.page_of(json.loads(ix[0]) if ix and ix[0] else None, s)}


def diff(series_id: str, old: int, new: int, lang: str = "") -> dict | None:
    """Compare the editions of two years of a series; None if the series or an edition's text is unknown."""
    d = series.detail(series_id, lang)
    if d is None:
        return None
    eds = {e["year"]: e for e in d["editions"]}
    years = sorted(eds)
    out = {"series": d["series"], "id": series_id, "lang": d["lang"], "years": years, "old": old, "new": new,
           "docs": None}
    if old not in eds or new not in eds or old == new:
        return out
    a_doc, b_doc = eds[old]["profile_doc"], eds[new]["profile_doc"]
    if not a_doc or not b_doc:
        out["missing"] = [y for y, x in ((old, a_doc), (new, b_doc)) if not x]
        return out
    tax = topics.taxonomy()["topics"]
    with db.session() as con:
        src = con.execute("SELECT agency, name_en, name_local FROM sources WHERE key=?", (d["series"]["source"],)).fetchone()
        own = {(x or "").casefold() for x in (src["agency"], src["name_en"], src["name_local"])} if src else set()
        ta, tb = _topics(con, a_doc["id"], tax), _topics(con, b_doc["id"], tax)
        rank = lambda t: {k: i for i, k in enumerate(sorted(t, key=lambda k: -t[k]["score"]))}  # noqa: E731
        ra, rb = rank(ta), rank(tb)
        main = lambda r: {k for k, i in r.items() if i < topics.MAIN_TOPICS}  # noqa: E731
        rows = []
        for k in set(ta) | set(tb):
            s0, s1 = (ta.get(k) or {}).get("score", 0), (tb.get(k) or {}).get("score", 0)
            state = "new" if k not in ta else "gone" if k not in tb else "up" if k in main(rb) and k not in main(ra) \
                else "down" if k in main(ra) and k not in main(rb) else "same"
            rows.append({"topic": k, "name": tax[k]["name"], "old": s0, "new": s1, "state": state,
                         "main_old": k in main(ra), "main_new": k in main(rb),
                         "terms": (tb.get(k) or ta.get(k))["terms"][:8]})
        rows.sort(key=lambda r: (-abs(r["new"] - r["old"]), r["name"]))
        aa, ab = _actors(con, a_doc["id"], own), _actors(con, b_doc["id"], own)
        added = [{**v, "doc": b_doc["id"], **_passage(con, b_doc["id"], v["spans"])}
                 for k, v in ab.items() if k not in aa][:PASSAGES]
        dropped = [{**v, "doc": a_doc["id"], **_passage(con, a_doc["id"], v["spans"])}
                   for k, v in aa.items() if k not in ab][:PASSAGES]
        changed = sorted(({"key": k, "label": ab[k]["label"], "kind": ab[k]["kind"], "old": aa[k]["hits"], "new": ab[k]["hits"]}
                          for k in aa.keys() & ab.keys() if abs(ab[k]["hits"] - aa[k]["hits"]) >= MIN_RISE),
                         key=lambda r: -abs(r["new"] - r["old"]))
        out.update(docs=(a_doc, b_doc), topics=rows, added=added, dropped=dropped, changed=changed,
                   n_added=sum(k not in aa for k in ab), n_dropped=sum(k not in ab for k in aa),
                   shown=PASSAGES, min_rise=MIN_RISE,
                   for_kind={x: actors.kind_name(x) for x in {v["kind"] for v in list(aa.values()) + list(ab.values())}})
    return out
