"""The Documents list's filters as SQL – one place, so every count elsewhere (watchlist, checks) is exactly what the
list shows for the same parameters."""
import re

from . import actors, countries, db, doctypes, series, topics, trends


def build(country: str = "", type: str = "", lang: str = "", year="", status: str = "", q: str = "", source: int = 0,
          show_hidden: int = 0, coalition: str = "", topic=(), year_from="", year_to="", indexed: int = 0,
          actor: str = "", main: int = 0, cluster: str = "", series_id: str = "", added_from: str = "",
          added_to: str = "", undated: int = 0, doc_type: str = "", all_types: int = 0) -> dict:
    """SQL condition (over documents d JOIN sources s) and its arguments for the Documents list's parameters."""
    tax = topics.taxonomy()["topics"]
    topic = [topic] if isinstance(topic, str) else list(topic or [])
    year, year_from, year_to = str(year or ""), str(year_from or ""), str(year_to or "")
    chosen = [t for t in topic if t in tax]
    where, args = ["s.active=1"], []
    if coalition in countries.coalitions():
        codes = sorted(countries.scope(coalition))
        where.append(f"s.country IN ({','.join('?' * len(codes))})"); args += codes
    if not show_hidden:
        where.append("d.hidden=0 AND d.status NOT IN ('missing','duplicate','skipped')")
    if doc_type in doctypes.TYPES:          # one document type, also one that is not counted as a report
        where.append("d.doc_type=?"); args.append(doc_type)
    elif not all_types:                     # by default, as every count: statements, laws, finance tables and forms left out
        where.append(doctypes.COUNTED)
    for col, val in (("s.country", country), ("s.type", type), ("d.lang", lang), ("d.status", status)):
        if val:
            where.append(f"{col}=?"); args.append(val)
    if year:
        where.append("d.year=?"); args.append(int(year))
    if year_from.strip().isdigit():
        where.append("d.year>=?"); args.append(int(year_from))
    if year_to.strip().isdigit():
        where.append("d.year<=?"); args.append(int(year_to))
    if undated:
        where.append("d.year IS NULL")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", added_from):   # added to the library on or after this day
        where.append("date(d.discovered_at)>=?"); args.append(added_from)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", added_to):     # … and on or before this day
        where.append("date(d.discovered_at)<=?"); args.append(added_to)
    if indexed:   # links from the Trends charts count only documents whose text is topic-classified
        where.append(trends.CLASSIFIED)
    actor_row = None
    if actor:
        where.append(actors.doc_clause()); args.append(actor)
    editions = series.doc_index()
    series_row = series.get(series_id) if series_id else None
    if series_id:   # editions of one report series
        ids = [d for d, e in editions.items() if e["id"] == series_id] or [0]
        where.append(f"d.id IN ({','.join('?' * len(ids))})"); args += ids
    cluster_keys = [k for k in cluster.split(",") if k][:200]
    if cluster_keys:   # link from a Network cluster: reports naming two of these actors in one passage
        sql, cargs = actors.cluster_clause(cluster_keys)
        where.append(sql); args += cargs
        with db.session() as con:
            actors.init()
            actor_row = con.execute("SELECT key, label FROM actors WHERE key=?", (actor,)).fetchone()
    if source:
        where.append("s.id=?"); args.append(source)
    fts = trends.or_query(q) if q.strip() else ""
    if q.strip() and indexed:
        # link from a Trends chart: exactly the full-text match the chart counted
        where.append("d.id IN (SELECT rowid FROM doc_text WHERE doc_text MATCH ?)"); args.append(fts or '""')
    elif q.strip():
        # metadata match OR full-text match inside the report ("a OR b" is handled by the full-text match)
        where.append("""(d.title LIKE ? OR s.agency LIKE ? OR s.name_local LIKE ? OR s.name_en LIKE ?
                         OR d.id IN (SELECT rowid FROM doc_text WHERE doc_text MATCH ?))""")
        args += [f"%{q}%"] * 4 + [fts or '""']
    base_where, base_args = " AND ".join(where), list(args)      # everything except the topic filter
    for t in chosen:                                              # several topics: a document must have all
        if main:   # link from the topic mind map: the topic must be one of the report's main topics
            sql, margs = topics.main_topic_clause()
            where.append(sql); args += [*margs, t]
        else:
            where.append("d.id IN (SELECT doc_id FROM doc_topics WHERE topic=?)"); args.append(t)
    return {"where": where, "args": args, "chosen": chosen, "fts": fts, "base_where": base_where,
            "base_args": base_args, "editions": editions, "series_row": series_row, "actor_row": actor_row}


def count(**params) -> int:
    """How many reports the Documents list shows for these parameters."""
    f = build(**params)
    with db.session() as con:
        topics.init()
        return con.execute(f"""SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                               WHERE {' AND '.join(f['where'])}""", f["args"]).fetchone()[0]
