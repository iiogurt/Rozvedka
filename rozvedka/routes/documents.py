"""The Documents list."""
import json
from urllib.parse import urlencode
from fastapi import APIRouter, Query, Request
from markupsafe import escape
from .. import dating, db, doclist, doctypes, paging, topics, trends, watch
from ..web import tpl

router = APIRouter()


@router.get("/documents")
def documents(request: Request, country: str = "", type: str = "", lang: str = "", year: str = "",
          status: str = "", q: str = "", source: int = 0, page: str = "1", per_page: str = "", show_hidden: int = 0,
          coalition: str = "", topic: list[str] = Query(default=[]), sort: str = "",
          year_from: str = "", year_to: str = "", indexed: int = 0, actor: str = "", main: int = 0,
          cluster: str = "", series_id: str = Query("", alias="series"), added_from: str = "", added_to: str = "", undated: int = 0,
          doc_type: str = "", all_types: int = 0, all_files: int = 0, exact: int = 0, cve: str = "", cve_near: str = ""):
    tax = topics.taxonomy()["topics"]
    if doc_type == "all":                                   # the type list's "every type" choice
        doc_type, all_types = "", 1
    doc_type = doc_type if doc_type in doctypes.TYPES else ""
    fargs = dict(country=country, type=type, lang=lang, year=year, status=status, q=q, source=source,
                 show_hidden=show_hidden, coalition=coalition, topic=topic, year_from=year_from, year_to=year_to,
                 indexed=indexed, actor=actor, main=main, cluster=cluster, series_id=series_id,
                 added_from=added_from, added_to=added_to, undated=undated, exact=exact, cve=cve, cve_near=cve_near)
    flt = doclist.build(**fargs, doc_type=doc_type, all_types=all_types, all_files=all_files)
    every_type = doclist.build(**fargs, all_types=1)       # the same filters over every type: counts per type
    where, args, chosen, fts = flt["where"], flt["args"], flt["chosen"], flt["fts"]
    base_where, base_args = flt["base_where"], flt["base_args"]
    editions, series_row, actor_row = flt["editions"], flt["series_row"], flt["actor_row"]
    sql_where = " AND ".join(where)
    sort = sort or ("relevance" if chosen or q.strip() else "year")
    if sort == "relevance" and chosen:
        order = f"""(SELECT SUM(score) FROM doc_topics WHERE doc_id=d.id AND topic IN ({','.join('?' * len(chosen))})) DESC,
                    d.year DESC NULLS LAST"""
        order_args = list(chosen)
    elif sort == "relevance" and fts:
        # relevance of every match computed once (temp.fts_rank, filled below) – a MATCH per row was seconds per page
        order = "(SELECT r FROM temp.fts_rank WHERE doc_id=d.id) ASC NULLS LAST, d.year DESC NULLS LAST"
        order_args = []
    elif sort == "added":
        order, order_args = "d.discovered_at DESC, d.id DESC", []
    else:
        order, order_args = "d.year DESC NULLS LAST, s.country, s.agency, d.lang", []
    size = paging.per_page_of(per_page)
    params = dict(country=country, type=type, lang=lang, year=year, status=status, q=q, source=source or "",
                  coalition=coalition, topic=chosen, sort=sort if sort != "year" or chosen or q else "",
                  show_hidden=show_hidden or "", year_from=year_from, year_to=year_to, indexed=indexed or "",
                  actor=actor, main=main or "", cluster=cluster, series=series_id, added_from=added_from, added_to=added_to,
                  undated=undated or "", doc_type=doc_type, all_types=all_types or "", all_files=all_files or "",
                  exact=exact or "", cve=cve, cve_near=cve_near,
                  per_page=size if size != paging.PER_PAGE_CHOICES[2] else "")
    with db.session() as con:
        topics.init()
        if sort == "relevance" and fts and not chosen:
            con.execute("CREATE TEMP TABLE IF NOT EXISTS fts_rank (doc_id INTEGER PRIMARY KEY, r REAL)")
            con.execute("DELETE FROM temp.fts_rank")
            con.execute("INSERT INTO temp.fts_rank SELECT rowid, bm25(doc_text) FROM doc_text WHERE doc_text MATCH ?", (fts,))
        total = con.execute(f"SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id WHERE {sql_where}",
                            args).fetchone()[0]
        pg = paging.paginate(total, page, size, "/documents", params)
        independent = con.execute(f"""SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                                      WHERE {sql_where} AND NOT {trends.OFFICIAL}""", args).fetchone()[0]
        # other language versions and summaries of the reports listed (one file per report is listed by default)
        every_file = doclist.build(**fargs, doc_type=doc_type, all_types=all_types, all_files=1)
        other_files = con.execute(f"""SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                                      WHERE {' AND '.join(every_file['where'])}""", every_file["args"]).fetchone()[0] - total
        type_counts = dict(con.execute(
            f"""SELECT COALESCE(d.doc_type, ''), COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                WHERE {' AND '.join(every_type['where'])} GROUP BY 1""", every_type["args"]).fetchall())
        docs = [dict(r) for r in con.execute(
            f"""SELECT d.*, s.country, s.agency, s.type, s.name_en, s.logo_path,
                       u.added_at AS hand_added, u.official AS hand_official, ix.ocr AS ocr
                FROM documents d JOIN sources s ON s.id=d.source_id LEFT JOIN uploads u ON u.doc_id=d.id
                LEFT JOIN doc_index ix ON ix.doc_id=d.id
                WHERE {sql_where} ORDER BY {order} LIMIT ? OFFSET ?""",
            (*args, *order_args, size, pg["offset"]))]
        ids = [d["id"] for d in docs]
        variants: dict[int, list] = {}          # the other files of each listed report
        works_ids = [d["work_id"] for d in docs if d.get("work_id")]
        if works_ids:
            for r in con.execute(f"""SELECT id, work_id, lang, title FROM documents WHERE work_id IN ({','.join('?' * len(works_ids))})
                                     ORDER BY lang, id""", works_ids):
                variants.setdefault(r["work_id"], []).append(dict(r))
        for d in docs:
            d["variants"] = [v for v in variants.get(d.get("work_id"), []) if v["id"] != d["id"]]
        by_doc: dict[int, list] = {}
        if ids:
            for r in con.execute(f"""SELECT doc_id, topic, score FROM doc_topics WHERE doc_id IN ({','.join('?' * len(ids))})
                                     ORDER BY score DESC""", ids):
                by_doc.setdefault(r["doc_id"], []).append(r["topic"])
            if fts:
                for r in con.execute(f"""SELECT rowid, snippet(doc_text, 1, char(2), char(3), '…', 14) AS snip FROM doc_text
                                         WHERE doc_text MATCH ? AND rowid IN ({','.join('?' * len(ids))})""", (fts, *ids)):
                    for d in docs:
                        if d["id"] == r["rowid"]:
                            d["snippet"] = highlight(r["snip"])
        for d in docs:
            d["ocr"] = json.loads(d["ocr"]) if d.get("ocr") else None
        for d in docs:   # subject topics first (by score), meta topics such as "agency activity" last
            d["topics"] = sorted(by_doc.get(d["id"], []), key=lambda t: bool(tax.get(t, {}).get("meta")))
        topic_counts = dict(con.execute(
            f"""SELECT t.topic, COUNT(DISTINCT t.doc_id) FROM doc_topics t JOIN documents d ON d.id=t.doc_id
                JOIN sources s ON s.id=d.source_id WHERE {base_where} GROUP BY t.topic""", base_args).fetchall())
        facets = {
            "country": con.execute("SELECT DISTINCT country FROM sources WHERE active=1 ORDER BY country").fetchall(),
            "type": con.execute("SELECT DISTINCT type FROM sources WHERE active=1 ORDER BY type").fetchall(),
            "lang": con.execute("SELECT DISTINCT lang FROM documents WHERE lang!='' ORDER BY lang").fetchall(),
            "year": con.execute("SELECT DISTINCT year FROM documents WHERE year IS NOT NULL ORDER BY year DESC").fetchall(),
        }
        counts = dict(con.execute("SELECT status, COUNT(*) FROM documents GROUP BY status").fetchall())

    def qs(**kw):
        merged = {**params, **kw}
        return urlencode({k: v for k, v in merged.items() if v not in ("", 0, None, [])}, doseq=True)

    return tpl.TemplateResponse(request, "index.html", {"year_conflicts": len(dating.conflicts()),
        "type_counts": type_counts, "DOC_TYPES": doctypes.TYPES, "NOT_REPORTS": doctypes.NOT_REPORTS,
        "other_files": other_files, "independent": independent, "expansions": flt["expansions"],
        "docs": docs, "total": total, "pg": pg,
        "facets": facets, "f": params, "counts": counts, "qs": qs,
        "TOPICS": tax, "CATEGORIES": topics.taxonomy()["categories"], "topic_counts": topic_counts,
        "actor_row": actor_row, "editions": editions, "series_row": series_row,
        "watch_query": watch.to_query({**params, "topic": chosen}) if total else None,
    })


def highlight(snippet: str) -> str:
    """FTS snippet → safe HTML: escape the report text first, then turn our \\x02/\\x03 markers into <mark>."""
    return str(escape(snippet)).replace("\x02", "<mark>").replace("\x03", "</mark>")
