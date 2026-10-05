"""Precision review of actor matches in the portal: sample passages, mark them right or wrong.

Matching is by name, so some matches mean something else ("Wagner Silva de Araújo" is not the Wagner Group). The
review queue shows, for the names that put the most reports on actors (impact), a few random passages each – the
same ones until they are reviewed. Every verdict is kept with its passage as evidence in sources/actor_reviews.yaml
(written by the portal, editable by hand); a "wrong" verdict removes that report from the actor at once, and the
index applies it on every rebuild (actors.derive). The verdicts give each name a measured precision.
"""
import datetime as dt
import json
from collections import Counter
from pathlib import Path

import yaml

from . import actors, db, paging, topics
from .config import ROOT

REVIEWS = ROOT / "sources" / "actor_reviews.yaml"
HEADER = """# Actor match reviews – passages checked in the portal (Actors → Review). Each entry: the actor (Wikidata item or
# MITRE ATT&CK id), the name that matched, the report (official URL), the passage as evidence and the verdict.
# "wrong" removes that report from the actor (applied by the index on every rebuild); "right" only counts towards the
# name's measured precision. Written by the portal; editable by hand.
"""
SAMPLE = 3          # passages per name in the queue
ENOUGH = 5          # a name with this many verdicts has left the queue


def load(path: Path | None = None) -> list[dict]:
    path = path or REVIEWS
    if not path.exists():
        return []
    return [r for r in (yaml.safe_load(path.read_text(encoding="utf-8")) or []) if isinstance(r, dict)]


def save(rows: list[dict], path: Path | None = None) -> None:
    path = path or REVIEWS
    path.write_text(HEADER + yaml.safe_dump(rows, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")


def wrong_pairs(path: Path | None = None) -> set[tuple[str, str]]:
    """(actor, report URL) pairs marked wrong – for actors.derive."""
    return {(r["actor"], r["url"]) for r in load(path) if r.get("verdict") == "wrong"}


def record(actor: str, doc_id: int, verdict: str, name: str = "", says: str = "", path: Path | None = None) -> dict:
    """Store a verdict (replacing an earlier one for the same actor and report); "wrong" takes effect at once."""
    if verdict not in ("right", "wrong"):
        return {"error": "verdict must be right or wrong"}
    with db.session() as con:
        actors.init()
        row = con.execute("SELECT url FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not row or not con.execute("SELECT 1 FROM actors WHERE key=?", (actor,)).fetchone():
            return {"error": "unknown report or actor"}
        rows = [r for r in load(path) if not (r.get("actor") == actor and r.get("url") == row["url"])]
        rows.append({"actor": actor, "name": name, "url": row["url"], "says": " ".join(says.split())[:300],
                     "verdict": verdict, "checked": dt.date.today().isoformat()})
        save(rows, path)
        if verdict == "wrong":         # the next rebuild (derive) does the same; do it now for this report
            con.execute("DELETE FROM doc_actors WHERE doc_id=? AND actor_key=?", (doc_id, actor))
            con.execute("DELETE FROM actor_pairs WHERE doc_id=? AND (a=? OR b=?)", (doc_id, actor, actor))
    return {"recorded": verdict}


def _passage(con, doc_id: int, spans: list) -> dict:
    body = (con.execute("SELECT body FROM doc_text WHERE rowid=?", (doc_id,)).fetchone() or [""])[0] or ""
    s, e = spans[0]
    pages = con.execute("SELECT pages FROM doc_index WHERE doc_id=?", (doc_id,)).fetchone()
    page = topics.page_of(json.loads(pages[0]) if pages and pages[0] else None, s)
    return {**actors._snippet(body, s, e), "page": page}


def queue(page: int | str = 1, per_page: int = 5, kind: str = "", path: Path | None = None) -> dict:
    """Names by impact (reports they put on their actor), each with up to SAMPLE unreviewed random passages."""
    reviews = load(path)
    by_name = Counter((r["actor"], r.get("name", ""), r["verdict"]) for r in reviews)
    reviewed = {(r["actor"], r["url"]) for r in reviews}
    with db.session() as con:
        actors.init()
        where = "AND a.kind = ?" if kind else "AND a.kind != 'country'"
        # impact: the reports a name puts on its actor after all the rules (doc_actors), not its raw matches
        names = [dict(r) for r in con.execute(
            f"""SELECT n.id, n.name, c.docs, n.actor_key, a.label, a.kind
                FROM (SELECT da.actor_key, je.key name, COUNT(*) docs FROM doc_actors da, json_each(da.names) je
                      GROUP BY da.actor_key, je.key) c
                JOIN actor_names n ON n.actor_key=c.actor_key AND n.name=c.name JOIN actors a ON a.key=n.actor_key
                WHERE n.status='used' {where} ORDER BY c.docs DESC, n.id""", ([kind] if kind else []))]
        for n in names:
            n["right"] = by_name[(n["actor_key"], n["name"], "right")]
            n["wrong"] = by_name[(n["actor_key"], n["name"], "wrong")]
            n["checked"] = n["right"] + n["wrong"]
        todo = [n for n in names if n["checked"] < ENOUGH]
        done = [n for n in names if n["checked"]]
        pg = paging.paginate(len(todo), page, per_page, "/actors/review", {"kind": kind,
                             "per_page": per_page if per_page != 5 else ""}, default=5)
        for n in todo[pg["offset"]:pg["offset"] + per_page]:
            n["kind_name"] = actors.kind_name(n["kind"])
            n["samples"] = []
            # stable pseudo-random order: the same passages until they are reviewed
            for r in con.execute(
                    """SELECT h.doc_id, h.spans, d.title, d.year, d.url, d.local_path, s.agency, s.country
                       FROM actor_hits h JOIN doc_actors da ON da.doc_id=h.doc_id AND da.actor_key=?
                       JOIN documents d ON d.id=h.doc_id JOIN sources s ON s.id=d.source_id
                       WHERE h.name_id=? AND EXISTS (SELECT 1 FROM json_each(da.names) WHERE key=?)
                       ORDER BY (h.doc_id * 2654435761 + h.name_id) % 1000003""",
                    (n["actor_key"], n["id"], n["name"])):
                if (n["actor_key"], r["url"]) in reviewed:
                    continue
                spans = json.loads(r["spans"] or "[]")
                if not spans:
                    continue
                p = _passage(con, r["doc_id"], spans)
                n["samples"].append({**{k: r[k] for k in ("doc_id", "title", "year", "url", "agency", "country")}, **p,
                                     "open": (f"/doc/{r['doc_id']}" + (f"#page={p['page']}" if p["page"] else ""))
                                     if r["local_path"] else r["url"]})
                if len(n["samples"]) >= SAMPLE:
                    break
        totals = Counter(r["verdict"] for r in reviews)
    return {"names": todo[pg["offset"]:pg["offset"] + per_page], "pg": pg, "todo": len(todo), "all": len(names),
            "done": sorted(done, key=lambda n: (n["wrong"] / n["checked"], n["docs"]), reverse=True),
            "right": totals["right"], "wrong": totals["wrong"], "sample": SAMPLE, "enough": ENOUGH}


def of_actor(key: str, path: Path | None = None) -> list[dict]:
    """The reports removed from an actor by review, with the passage that showed it (for the actor page)."""
    return [r for r in load(path) if r["actor"] == key and r.get("verdict") == "wrong"]
