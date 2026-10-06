"""Watchlist: searches followed update by update – one shared list, no per-user state.

Each item is a search-console query (`actor:"Wagner Group"`, `topic:ransomware country:DE`, `"critical
infrastructure"`), stored in sources/watchlist.yaml (written by the portal, editable by hand). For every item the
portal shows, update by update (the days on which reports entered the library), how many of its reports each update
brought – each number the Documents list of exactly those reports – and its newest reports with a passage.
"""
import datetime as dt
import json
from pathlib import Path
from urllib.parse import urlencode

import yaml

from . import actors, compare, db, doclist, home, topics
from .config import ROOT

WATCHLIST = ROOT / "sources" / "watchlist.yaml"
HEADER = """# Watchlist – searches followed update by update on the portal's Watchlist page (/watch).
# Each item is a search-console query: words, "phrases", and filters such as country:DE actor:"Wagner Group"
# topic:ransomware year:2020..2025 (see the home page's "How search works"). Written by the portal; editable by hand.
"""
COLUMNS = 8          # the most recent updates shown as columns


def load(path: Path | None = None) -> list[dict]:
    path = path or WATCHLIST
    if not path.exists():
        return []
    return [i for i in (yaml.safe_load(path.read_text(encoding="utf-8")) or []) if isinstance(i, dict) and i.get("query")]


def save(items: list[dict], path: Path | None = None) -> None:
    path = path or WATCHLIST
    path.write_text(HEADER + yaml.safe_dump(items, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")


def add(query: str, path: Path | None = None) -> dict:
    """Add a query (if it parses without problems and is not on the list yet)."""
    query = " ".join(query.split())
    if not query:
        return {"error": "empty query"}
    parsed = home.parse(query)
    if parsed["problems"]:
        return {"error": "; ".join(f"{p['token']}: {p['message']}" for p in parsed["problems"])}
    items = load(path)
    if any(i["query"] == query for i in items):
        return {"exists": query}
    items.append({"query": query, "added": dt.date.today().isoformat()})
    save(items, path)
    return {"added": query}


def remove(query: str, path: Path | None = None) -> None:
    save([i for i in load(path) if i["query"] != query], path)


def to_query(params: dict) -> str | None:
    """Documents-list parameters → a search-console query, or None when a filter has no query form."""
    if any(params.get(k) for k in ("cluster", "series", "main", "indexed", "status", "show_hidden", "undated",
                                   "added_from", "added_to", "doc_type", "all_types")):
        return None
    tax = topics.taxonomy()["topics"]
    quote = lambda v: f'"{v}"' if " " in v else v   # noqa: E731
    parts = []
    with db.session() as con:
        if params.get("source"):
            row = con.execute("SELECT country, agency FROM sources WHERE id=?", (params["source"],)).fetchone()
            if not row:
                return None
            parts += [f"country:{row['country']}", f"agency:{quote(row['agency'])}"]
        elif params.get("country"):
            parts.append(f"country:{params['country']}")
        if params.get("actor"):
            actors.init()
            row = con.execute("SELECT label FROM actors WHERE key=?", (params["actor"],)).fetchone()
            parts.append(f"actor:{quote(row['label'])}" if row else f"actor:{params['actor']}")
    for k in ("coalition", "type", "lang"):
        if params.get(k):
            parts.append(f"{k}:{params[k]}")
    for t in params.get("topic") or []:
        parts.append(f"topic:{quote(tax[t]['name'])}" if t in tax else f"topic:{t}")
    if params.get("year"):
        parts.append(f"year:{params['year']}")
    elif params.get("year_from") or params.get("year_to"):
        parts.append(f"year:{params.get('year_from') or 1990}..{params.get('year_to') or dt.date.today().year}")
    if params.get("q"):
        parts.append(params["q"])
    return " ".join(parts) or None


def _per_day(con, params: dict) -> dict[str, int]:
    f = doclist.build(**params)
    return dict(con.execute(f"""SELECT date(d.discovered_at) day, COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                                WHERE {' AND '.join(f['where'])} GROUP BY day""", f["args"]).fetchall())


def overview(path: Path | None = None) -> dict:
    """Every item with its total, its count per update (newest updates as columns) and its newest reports;
    and the updates newest first with the items that got reports in each."""
    from . import updates
    items = []
    with db.session() as con:
        topics.init()
        actors.init()
        days = [d["day"] for d in updates.days(con)]
        cols = days[:COLUMNS]
        for it in load(path):
            parsed = home.parse(it["query"])
            if parsed["problems"]:
                items.append({**it, "problems": parsed["problems"]})
                continue
            params = {k: v for k, v in parsed["params"].items() if v not in ("", None, [])}
            by_day = _per_day(con, params)
            total = sum(by_day.values())
            items.append({**it, "params": params, "total": total, "url": home.docs_url(**params, sort="added"),
                          "cells": [{"day": d, "n": by_day.get(d, 0),
                                     "url": home.docs_url(**params, added_from=d, added_to=d, sort="added")} for d in cols],
                          "older": {"n": sum(n for d, n in by_day.items() if d not in cols),
                                    "url": home.docs_url(**params, added_to=days[len(cols)], sort="added")}
                                   if len(days) > len(cols) else None,
                          "last_day": max(by_day) if by_day else None,
                          "feed": "/feed.atom?" + urlencode({"watch": it["query"]})})
        timeline = []
        for d in days:
            hits = [{"query": i["query"], "n": c["n"], "url": c["url"]} for i in items if "cells" in i
                    for c in i["cells"] if c["day"] == d and c["n"]]
            if d not in cols:     # older updates: count them directly
                hits = []
                for i in items:
                    if "params" in i:
                        n = _per_day(con, {**i["params"], "added_from": d, "added_to": d}).get(d, 0)
                        if n:
                            hits.append({"query": i["query"], "n": n,
                                         "url": home.docs_url(**i["params"], added_from=d, added_to=d, sort="added")})
            timeline.append({"day": d, "hits": hits})
    return {"entries": items, "columns": cols, "timeline": timeline}   # not "items": Jinja would see dict.items


def latest(query: str, limit: int = 5) -> list[dict]:
    """The item's newest reports (by when they entered the library), each with a passage where one can be found:
    for an actor its densest mentions, for a topic its densest terms, for words the full-text snippet."""
    parsed = home.parse(query)
    if parsed["problems"]:
        return []
    params = {k: v for k, v in parsed["params"].items() if v not in ("", None, [])}
    f = doclist.build(**params)
    out = []
    with db.session() as con:
        topics.init()
        actors.init()
        rows = [dict(r) for r in con.execute(
            f"""SELECT d.id, d.title, d.year, d.lang, d.url, d.local_path, d.discovered_at, s.country, s.agency, s.name_en,
                       s.name_local, i.pages, i.ocr
                FROM documents d JOIN sources s ON s.id=d.source_id LEFT JOIN doc_index i ON i.doc_id=d.id
                WHERE {' AND '.join(f['where'])} ORDER BY d.discovered_at DESC, d.year DESC NULLS LAST, d.id DESC LIMIT ?""",
            (*f["args"], limit))]
        for r in rows:
            body = (con.execute("SELECT body FROM doc_text WHERE rowid=?", (r["id"],)).fetchone() or [""])[0] or ""
            spans = []
            if params.get("actor"):
                hit = con.execute("SELECT spans FROM doc_actors WHERE doc_id=? AND actor_key=?", (r["id"], params["actor"])).fetchone()
                spans = [tuple(x) for x in json.loads(hit[0])] if hit and hit[0] else []
            elif f["fts"]:
                spans = compare.highlight_spans(con, r["id"], f["fts"])
            elif params.get("topic"):
                t = con.execute("SELECT terms FROM doc_topics WHERE doc_id=? AND topic=?", (r["id"], params["topic"][0])).fetchone()
                spans = compare.fts_spans(con, r["id"], json.loads(t[0]) if t and t[0] else [])
            own = {topics.normalize(x).strip() for x in (r["agency"], r["name_en"], r["name_local"]) if x}
            spans = [sp for sp in spans if topics.normalize(body[sp[0]:sp[1]]).strip() not in own]
            item = {k: r[k] for k in ("id", "title", "year", "lang", "url", "country", "agency")}
            item["found"] = (r["discovered_at"] or "")[:10]
            item["ocr"] = actors._ocr_note(r["ocr"])
            if spans:
                s, _, inside = compare._densest(spans, body)
                item["segments"] = compare._passage(body, inside)
                item["page"] = topics.page_of(json.loads(r["pages"]) if r["pages"] else None, s)
            item["open"] = (f"/doc/{r['id']}" + (f"#page={item['page']}" if item.get("page") else "")) if r["local_path"] else r["url"]
            out.append(item)
    return out


def figures(o: dict) -> list[tuple[str, int, str]]:
    out = []
    for i in o["entries"]:
        if "cells" not in i:
            continue
        out.append((f"{i['query']} total", i["total"], i["url"]))
        out += [(f"{i['query']} {c['day']}", c["n"], c["url"]) for c in i["cells"]]
        if i["older"]:
            out.append((f"{i['query']} older", i["older"]["n"], i["older"]["url"]))
    return out

