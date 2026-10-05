"""Compare agencies on one question: what each agency's reports say about one actor or one topic.

One card per agency, ranked by how many of its reports in scope name the actor (or are tagged with the topic); in
each card the agency's reports that deal with it most, each with its densest passage – the WINDOW characters with the
most mentions of the actor or terms of the topic, passing over stretches that read like a reference list – and the
page of the PDF it is on.
"""
import datetime as dt
import json
import re

from . import actors, db, topics, trends
from .home import docs_url

WINDOW = actors.WINDOW         # characters: one passage
PER_AGENCY = 2                 # passages (reports) shown per agency
CONTEXT = 160                  # characters of context around the passage's mentions


_REFERENCE = re.compile(r"https?://|www\.|\baccessed\b|\bdoi\b|\bisbn\b|\bpp?\.\s*\d|\bibid\b|\bop\. cit", re.I)
_YEARS = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


def looks_like_references(text: str) -> bool:
    """A bibliography or endnotes rather than prose: links, 'accessed', DOI/ISBN, page ranges, or many years."""
    return len(_REFERENCE.findall(text)) >= 2 or len(_YEARS.findall(text)) >= 5


def _densest(spans: list[tuple[int, int]], body: str = "") -> tuple[int, int, list[tuple[int, int]]]:
    """The WINDOW-character stretch with the most spans: (start, end, spans inside) – skipping stretches that read
    like a reference list when another one has mentions too."""
    spans = sorted(spans)
    windows, j = [], 0
    for i in range(len(spans)):
        while spans[i][1] - spans[j][0] > WINDOW:
            j += 1
        windows.append((i - j + 1, -spans[j][0], j, i + 1))
    windows.sort(reverse=True)
    pick = windows[0]
    for w in windows:
        a, b = spans[w[2]][0], spans[w[3] - 1][1]
        if not body or not looks_like_references(body[max(0, a - CONTEXT):b + CONTEXT]):
            pick = w
            break
    inside = spans[pick[2]:pick[3]]
    return inside[0][0], inside[-1][1], inside


def _passage(body: str, inside: list[tuple[int, int]]) -> list[dict]:
    """Text around the spans as segments [{text, mark}], with … where it is cut."""
    a, b = max(0, inside[0][0] - CONTEXT), min(len(body), inside[-1][1] + CONTEXT)
    if a > 0:
        a = body.find(" ", a, inside[0][0]) + 1 or a
    if b < len(body):
        cut = body.rfind(" ", inside[-1][1], b)
        b = cut if cut > inside[-1][1] else b
    out, pos = [], a
    clean = lambda s: " ".join(s.split())  # noqa: E731
    for s, e in inside:
        if s < pos:
            continue
        out.append({"text": clean(body[pos:s]), "mark": False})
        out.append({"text": clean(body[s:e]), "mark": True})
        pos = e
    out.append({"text": clean(body[pos:b]), "mark": False})
    if a > 0:
        out.insert(0, {"text": "…", "mark": False})
    if b < len(body):
        out.append({"text": "…", "mark": False})
    return out


def fts_spans(con, doc_id: int, terms: list[str]) -> list[tuple[int, int]]:
    """Where the topic's terms (the ones the index found in this report) occur, from the full-text index:
    highlight() marks every match in the stored text, so the positions are those of the original text."""
    alts = [t for t in terms if not topics._CJK.search(topics.normalize(t))]
    query = " OR ".join('"' + t.rstrip("*").replace('"', "") + '"' + ("*" if t.endswith("*") else "") for t in alts)
    return highlight_spans(con, doc_id, query) if query else []


def highlight_spans(con, doc_id: int, query: str) -> list[tuple[int, int]]:
    """Positions of a full-text query's matches in a report's stored text (highlight() with its markers removed)."""
    try:
        row = con.execute("SELECT highlight(doc_text, 1, char(2), char(3)) FROM doc_text WHERE doc_text MATCH ? AND rowid=?",
                          (query, doc_id)).fetchone()
    except Exception:  # noqa: BLE001 - a term the query syntax cannot express: no passage rather than an error
        return []
    spans, shift, pos = [], 0, 0
    text = row[0] if row else ""
    while True:
        s = text.find("\x02", pos)
        if s < 0:
            break
        e = text.find("\x03", s)
        spans.append((s - shift, e - shift - 1))     # minus the markers before it (and the opening one)
        shift += 2
        pos = e + 1
    return spans


def compare(actor: str = "", topic: str = "", year_from: int | None = None, year_to: int | None = None,
            country: str = "", coalition: str = "", type: str = "", page: int = 1, per_page: int = 12) -> dict:
    now = dt.date.today().year
    year_from, year_to = year_from or now - 2, year_to or now
    where, args, params = trends.scope(country, coalition, type)
    where += " AND d.year BETWEEN ? AND ?"
    args = [*args, year_from, year_to]
    params = {**params, "year_from": year_from, "year_to": year_to}
    tax = topics.taxonomy()["topics"]
    with db.session() as con:
        topics.init()
        actors.init()
        if actor:
            row = con.execute("SELECT key, label, kind FROM actors WHERE key=?", (actor,)).fetchone()
            if not row:
                return {"error": f"no actor {actor}"}
            subject = {"kind": "actor", "key": row["key"], "label": row["label"], "page": f"/actors/{row['key']}",
                       "how": "names the actor (the same rule as the actor page)"}
            match = (f"d.id IN (SELECT da.doc_id FROM doc_actors da JOIN actors a ON a.key=da.actor_key "
                     f"JOIN documents d ON d.id=da.doc_id WHERE da.actor_key=? AND {actors.NOT_BEFORE_FOUNDED})")
            margs, link = [actor], {"actor": actor}
            weight = "(SELECT hits FROM doc_actors WHERE doc_id=d.id AND actor_key=?)"
        elif topic in tax:
            subject = {"kind": "topic", "key": topic, "label": tax[topic]["name"], "page": f"/documents?topic={topic}",
                       "how": "is tagged with the topic (its keywords, sources/topics.yaml)"}
            match, margs, link = "d.id IN (SELECT doc_id FROM doc_topics WHERE topic=?)", [topic], {"topic": topic}
            weight = "(SELECT score FROM doc_topics WHERE doc_id=d.id AND topic=?)"
        else:
            return {"error": "choose an actor or a topic"}
        frm = "FROM documents d JOIN sources s ON s.id=d.source_id"
        base = f"{frm} WHERE {where} AND {match}"
        rows = [dict(r) for r in con.execute(
            f"""SELECT s.id source_id, s.agency, s.country, s.type, s.name_en, s.name_local, COUNT(*) n, MIN(d.year) y0, MAX(d.year) y1
                {base} GROUP BY s.id ORDER BY n DESC, s.country, s.agency""", (*args, *margs))]
        in_scope = dict(con.execute(
            f"""SELECT s.id, COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id WHERE {where} GROUP BY s.id""",
            args).fetchall())
        total = sum(r["n"] for r in rows)
        offset = (max(page, 1) - 1) * per_page
        cards = rows[offset:offset + per_page]
        for c in cards:
            c["url"] = docs_url(**link, **params, source=c["source_id"])
            c["of"] = in_scope.get(c["source_id"], 0)
            c["of_url"] = docs_url(**params, source=c["source_id"])
            c["passages"] = []
            for d in con.execute(
                    f"""SELECT d.id, d.title, d.year, d.lang, d.url, d.local_path, i.pages, i.ocr
                        {frm} LEFT JOIN doc_index i ON i.doc_id=d.id WHERE {where} AND {match}
                        AND s.id=? ORDER BY {weight} DESC, d.year DESC LIMIT ?""",
                    (*args, *margs, c["source_id"], *margs, PER_AGENCY)):
                body = con.execute("SELECT body FROM doc_text WHERE rowid=?", (d["id"],)).fetchone()
                body = body[0] if body else ""
                if actor:
                    hit = con.execute("SELECT spans FROM doc_actors WHERE doc_id=? AND actor_key=?", (d["id"], actor)).fetchone()
                    spans = [tuple(x) for x in json.loads(hit[0])] if hit and hit[0] else []
                else:
                    t = con.execute("SELECT terms FROM doc_topics WHERE doc_id=? AND topic=?", (d["id"], topic)).fetchone()
                    spans = fts_spans(con, d["id"], json.loads(t[0]) if t and t[0] else [])
                own = {topics.normalize(x).strip() for x in (c["agency"], c["name_en"], c["name_local"]) if x}
                spans = [sp for sp in spans if topics.normalize(body[sp[0]:sp[1]]).strip() not in own]   # an agency naming itself
                p = {"mentions": len(spans)}
                p.update({"id": d["id"], "title": d["title"], "year": d["year"], "lang": d["lang"], "url": d["url"],
                          "ocr": actors._ocr_note(d["ocr"])})
                if spans:
                    s, e, inside = _densest(spans, body)
                    pages = json.loads(d["pages"]) if d["pages"] else None
                    p["page"] = topics.page_of(pages, s)
                    p["in_passage"] = len(inside)
                    p["segments"] = _passage(body, inside)
                p["open"] = (f"/doc/{d['id']}" + (f"#page={p['page']}" if p.get("page") else "")) if d["local_path"] else d["url"]
                c["passages"].append(p)
    return {"subject": subject, "agencies": cards, "n_agencies": len(rows), "total": total,
            "countries": len({r["country"] for r in rows}), "params": params, "year_from": year_from, "year_to": year_to,
            "url": docs_url(**link, **params), "offset": offset,
            "how": f"Reports from {year_from}–{year_to} whose text {subject['how']}, per agency. In each card: the agency's "
                   f"{PER_AGENCY} reports that deal with it most ({'most mentions' if actor else 'highest topic score'}), "
                   f"each with its densest passage – the {WINDOW} characters with the most "
                   f"{'mentions of the actor' if actor else 'terms of the topic'}, passing over reference lists and "
                   f"endnotes (links, “accessed”, DOI/ISBN, many years); an agency's own name in its own reports does not count."}


def figures(c: dict) -> list[tuple[str, int, str]]:
    out = [("total", c["total"], c["url"])]
    for a in c["agencies"]:
        out += [(f"agency {a['agency']}", a["n"], a["url"]), (f"in scope {a['agency']}", a["of"], a["of_url"])]
    return out

