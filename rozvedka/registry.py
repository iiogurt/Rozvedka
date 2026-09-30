"""Load sources/registry.yaml into the database (idempotent)."""
import yaml

from . import db
from .config import REGISTRY


def load(path=REGISTRY) -> list[dict]:
    return yaml.safe_load(open(path, encoding="utf-8"))


def source_key(src: dict) -> str:
    return f"{src['country']}/{src['agency']}"


def sync(path=REGISTRY) -> dict:
    db.init()
    srcs = load(path)
    seen_sources, seen_pages = set(), set()
    with db.session() as con:
        for s in srcs:
            key = source_key(s)
            hq = s.get("hq") or {}
            con.execute(
                """INSERT INTO sources(key,country,agency,name_local,name_en,homepage,description,logo_url,
                                      hq_address,lat,lon,hq_precision,
                                      type,access,frequency,report_types,notes,active)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
                   ON CONFLICT(key) DO UPDATE SET name_local=excluded.name_local, name_en=excluded.name_en,
                     homepage=excluded.homepage, description=excluded.description, logo_url=excluded.logo_url,
                     hq_address=excluded.hq_address, lat=excluded.lat, lon=excluded.lon,
                     hq_precision=excluded.hq_precision,
                     type=excluded.type, access=excluded.access, frequency=excluded.frequency,
                     report_types=excluded.report_types, notes=excluded.notes, active=1""",
                (key, s["country"], s["agency"], s.get("name_local"), s.get("name_en"), s.get("homepage"),
                 s.get("description"), s.get("logo"), hq.get("address"), hq.get("lat"), hq.get("lon"),
                 hq.get("precision"), s.get("type"), s.get("access", "auto"),
                 s.get("frequency"), ", ".join(s.get("report_types", [])), s.get("notes")))
            sid = con.execute("SELECT id FROM sources WHERE key=?", (key,)).fetchone()["id"]
            seen_sources.add(sid)
            pages = list(s.get("pages", []))
            pat = s.get("url_pattern")
            if pat and not pat["template"].lower().endswith(".pdf"):
                # an HTML pattern (one page per year) becomes ordinary pages to crawl
                y0, y1 = pat["years"]
                pages += [{"url": pat["template"].format(year=y, lang=l), "lang": l, "kind": "archive"}
                          for y in range(y0, y1 + 1) for l in pat.get("langs", [""])]
            for p in pages:
                con.execute(
                    """INSERT INTO pages(source_id,url,lang,kind,note,verified,active) VALUES(?,?,?,?,?,?,1)
                       ON CONFLICT(source_id,url) DO UPDATE SET lang=excluded.lang, kind=excluded.kind,
                         note=excluded.note, verified=excluded.verified, active=1""",
                    (sid, p["url"], p.get("lang"), p.get("kind"), p.get("note"), 0 if p.get("verified") is False else 1))
                seen_pages.add(con.execute("SELECT id FROM pages WHERE source_id=? AND url=?", (sid, p["url"])).fetchone()["id"])
        # deactivate things removed from the YAML (documents are kept)
        for (sid,) in con.execute("SELECT id FROM sources").fetchall():
            if sid not in seen_sources:
                con.execute("UPDATE sources SET active=0 WHERE id=?", (sid,))
        for (pid,) in con.execute("SELECT id FROM pages").fetchall():
            if pid not in seen_pages:
                con.execute("UPDATE pages SET active=0 WHERE id=?", (pid,))
    return {"sources": len(seen_sources), "pages": len(seen_pages)}


def patterns() -> dict[str, dict]:
    """url_pattern entries keyed by source key."""
    return {source_key(s): s["url_pattern"] for s in load() if s.get("url_pattern")}
