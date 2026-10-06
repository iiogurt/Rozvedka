"""One report on one page: where it comes from, its series and other editions, its topics (with the terms that
matched), the actors it names with a passage each, and what changed against the previous edition of its series."""
import json

from . import actors, collect, dating, db, series, topics

ACTORS_SHOWN = 30


def detail(doc_id: int) -> dict | None:
    tax = topics.taxonomy()["topics"]
    with db.session() as con:
        topics.init()
        actors.init()
        con.executescript(collect.SCHEMA)
        d = con.execute("""SELECT d.*, s.key skey, s.country, s.agency, s.name_en, s.name_local, s.type, s.homepage,
                                  p.url page_url, p.lang page_lang, p.kind page_kind, p.last_crawled
                           FROM documents d JOIN sources s ON s.id=d.source_id LEFT JOIN pages p ON p.id=d.page_id
                           WHERE d.id=?""", (doc_id,)).fetchone()
        if d is None:
            return None
        d = dict(d)
        ix = con.execute("SELECT * FROM doc_index WHERE doc_id=?", (doc_id,)).fetchone()
        ix = dict(ix) if ix else None
        upload = con.execute("SELECT * FROM uploads WHERE doc_id=?", (doc_id,)).fetchone()
        offsets = json.loads(ix["pages"]) if ix and ix.get("pages") else None
        # topics: all of them, by score; the main ones are the first non-meta ones
        trows = [dict(r) for r in con.execute("SELECT * FROM doc_topics WHERE doc_id=? ORDER BY score DESC", (doc_id,))]
        for t in trows:
            t["name"] = tax.get(t["topic"], {}).get("name", t["topic"])
            t["category"] = tax.get(t["topic"], {}).get("category_name", "")
            t["meta"] = bool(tax.get(t["topic"], {}).get("meta"))
            t["terms"] = json.loads(t["terms"]) if t.get("terms") else []
        main = [t for t in trows if not t["meta"]][:topics.MAIN_TOPICS]
        # actors: same rule as the actor pages (not before the actor was founded); the agency naming itself is left
        # out; countries are listed apart
        own = {(x or "").casefold() for x in (d["agency"], d["name_en"], d["name_local"])}
        body = None
        named, countries_named = [], []
        for r in con.execute(f"""SELECT da.actor_key, da.hits, da.spans, da.names, a.label, a.kind FROM doc_actors da
                                JOIN actors a ON a.key=da.actor_key JOIN documents d ON d.id=da.doc_id
                                WHERE da.doc_id=? AND {actors.NOT_BEFORE_FOUNDED} ORDER BY da.hits DESC, a.label""", (doc_id,)):
            if r["label"].casefold() in own:
                continue
            item = {"key": r["actor_key"], "label": r["label"], "kind": r["kind"], "kind_name": actors.kind_name(r["kind"]),
                    "hits": r["hits"], "names": json.loads(r["names"] or "{}")}
            if r["kind"] == "country":
                countries_named.append(item)
                continue
            if len(named) < ACTORS_SHOWN and r["spans"]:
                if body is None:
                    row = con.execute("SELECT body FROM doc_text WHERE rowid=?", (doc_id,)).fetchone()
                    body = (row[0] if row else "") or ""
                s, e = json.loads(r["spans"])[0]
                item.update(actors._snippet(body, s, e), page=topics.page_of(offsets, s))
            named.append(item)
    # series: the edition, its neighbours and other languages, and what changed against the previous edition
    ed = series.doc_index().get(doc_id)
    sdetail, this, prev, nxt, other_langs = None, None, None, None, []
    if ed:
        sdetail = series.detail(ed["id"], ed["lang"])
        if sdetail:
            eds = sdetail["editions"]                       # newest first
            for i, e in enumerate(eds):
                if e["year"] == ed["year"]:
                    this = e
                    nxt = eds[i - 1] if i > 0 else None
                    prev = eds[i + 1] if i + 1 < len(eds) else None
            if this:
                other_langs = [(lg, f) for lg, files in this["files"].items() for f in files if f["id"] != doc_id]
    return {"doc": d, "index": ix, "upload": dict(upload) if upload else None,
            "ocr": actors._ocr_note(ix["ocr"]) if ix and ix.get("ocr") else None,
            "topics": trows, "main": main, "actors": named, "actors_shown": ACTORS_SHOWN, "countries": countries_named,
            "edition": ed, "series": sdetail["series"] if sdetail else None, "this": this, "prev": prev, "next": nxt,
            "other_langs": other_langs, "year_conflict": dating.conflict_of(doc_id), "conflict_kinds": dating.CONFLICT_KINDS}
