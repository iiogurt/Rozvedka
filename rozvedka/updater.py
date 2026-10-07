"""Checking the agencies for new reports – what the Update page starts (the same steps as `python -m rozvedka update`).

Actions:
  full      check the report pages, download the new reports, improve titles, then extract text and match topics,
            OCR, dates and actors for them
  check     only check the report pages (new reports are listed, not downloaded)
  download  only download the reports waiting for download (optionally retrying failed ones)

Scope: every source, one country, chosen sources, or the sources not checked for N days. There is no periodic job:
updates run when started (owner's decision); the page shows how old the data is.
"""
import datetime as dt
import json
import logging

from . import crawler, db, downloader, progress

log = logging.getLogger("rozvedka.updater")
SECONDS_PER_PAGE = 10.0          # without history: polite fetching (2 s per host), report pages often link sub-pages
SECONDS_PER_DOWNLOAD = 6.0
ACTIONS = {"full": "Check for new reports, download and index them", "check": "Only check for new reports",
           "download": "Only download the reports waiting for download"}
# after downloading: extract text, recognise scanned reports, date and match – each in its own process
INDEX_STEPS = (("Extracting text and matching topics", "index-topics"), ("Recognising scanned reports (OCR)", "ocr"),
               ("Dating new reports", "date-documents"), ("Typing and grouping new reports", "type-documents"),
               ("Matching actors", "index-actors"))


def all_checked_since(con) -> str | None:
    """How old the data is: the moment by which every source fetched automatically had been checked – the oldest of
    the sources' latest checks (a single source checked today does not make the whole library fresh)."""
    return con.execute("""SELECT MIN(latest) FROM (SELECT s.id, MAX(COALESCE(p.last_crawled, '')) latest FROM sources s
                          JOIN pages p ON p.source_id=s.id AND p.active=1 WHERE s.active=1 AND s.access!='manual'
                          GROUP BY s.id)""").fetchone()[0] or None


def seconds_per_page(con) -> float:
    """Measured on the last crawls (they record their start since 0.29.0), else the default."""
    rows = con.execute("""SELECT started_at, finished_at, summary FROM runs WHERE kind='crawl' AND summary LIKE '{%'
                          ORDER BY id DESC LIMIT 5""").fetchall()
    secs, pages = 0.0, 0
    for r in rows:
        try:
            a, b = dt.datetime.fromisoformat(r[0][:19]), dt.datetime.fromisoformat(r[1][:19])
            n = json.loads(r[2]).get("pages", 0)
        except (TypeError, ValueError):
            continue
        if n and b > a:
            secs += (b - a).total_seconds(); pages += n
    return secs / pages if pages >= 20 else SECONDS_PER_PAGE


def plan(action: str = "full", scope: str = "all", country: str = "", sources=(), stale_days: int = 7,
         retry_failed: bool = False) -> dict:
    """What a run would do: the sources and pages to check, the reports waiting, and about how long it takes."""
    with db.session() as con:
        chosen = crawler.selection(con, **_scope_args(scope, country, sources, stale_days)) if action != "download" else []
        ids = [s["id"] for s, _ in chosen] if action != "download" else _source_ids(con, scope, country, sources)
        statuses = ("new", "failed") if retry_failed else ("new",)
        q = f"""SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id WHERE d.hidden=0 AND s.access!='manual'
                AND d.status IN ({','.join('?' * len(statuses))})"""
        args = list(statuses)
        if ids is not None:
            q += f" AND s.id IN ({','.join('?' * len(ids)) or 'NULL'})"; args += ids
        waiting = con.execute(q, args).fetchone()[0] if action != "check" else 0
        pages = sum(len(p) for _, p in chosen)
        manual = sum(1 for s, _ in chosen if s["access"] == "manual")
        fetched = sum(len(p) for s, p in chosen if s["access"] != "manual")     # manual sources are skipped
        spp = seconds_per_page(con)
    est = fetched * spp + (waiting * SECONDS_PER_DOWNLOAD / 4 if action != "check" else 0)
    return {"action": action, "sources": len(chosen), "pages": pages, "manual": manual, "waiting": waiting,
            "seconds": round(est), "seconds_per_page": round(spp, 1), "measured": spp != SECONDS_PER_PAGE,
            "note": "plus the time for new reports found and indexed" if action == "full" else ""}


def _scope_args(scope: str, country: str, sources, stale_days: int) -> dict:
    if scope == "country":
        return {"country": country or "--"}
    if scope == "sources":
        return {"source_ids": list(sources) or [0]}
    if scope == "stale":
        return {"stale_days": max(int(stale_days or 1), 1)}
    return {}


def _source_ids(con, scope: str, country: str, sources) -> list[int] | None:
    if scope == "country":
        return [r[0] for r in con.execute("SELECT id FROM sources WHERE active=1 AND country=?", (country.upper(),))]
    if scope == "sources":
        return [int(i) for i in sources] or [0]
    return None


def run(action: str = "full", scope: str = "all", country: str = "", sources=(), stale_days: int = 7,
        retry_failed: bool = False, index_steps=None) -> dict:
    """Run an update; `index_steps(steps)` runs the indexers (separate processes when started from the portal)."""
    started = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)     # reports' discovered_at is UTC
    out: dict = {"action": action, "scope": scope, "started": started.isoformat(timespec="seconds") + "Z"}
    args = _scope_args(scope, country, sources, stale_days)
    log.info("update: %s, scope %s %s", ACTIONS.get(action, action), scope, args or "")
    if action in ("full", "check"):
        out["crawl"] = crawler.crawl(**args)
        log.info("found %d new reports on %d pages (%d errors, %d skipped)", out["crawl"]["new_docs"],
                 out["crawl"]["pages"], out["crawl"]["errors"], out["crawl"]["skipped"])
    if action in ("full", "download"):
        with db.session() as con:
            ids = _source_ids(con, scope, country, sources) if scope in ("country", "sources") else None
        if scope == "stale" and "crawl" in out:          # the sources just checked
            with db.session() as con:
                keys = list(out["crawl"]["sources"])
                ids = [r[0] for r in con.execute(f"SELECT id FROM sources WHERE key IN ({','.join('?' * len(keys)) or 'NULL'})", keys)]
        out["download"] = downloader.download(retry_failed=retry_failed, source_ids=ids) if ids != [] else {}
    if action == "full":
        progress.tick("Improving titles")
        out["titles_improved"] = downloader.improve_titles()
        out["index"] = index_steps(INDEX_STEPS) if index_steps else _index_here()
    with db.session() as con:
        out["new_today"] = con.execute("SELECT COUNT(*) FROM documents WHERE discovered_at >= ?",
                                       (started.strftime("%Y-%m-%d %H:%M:%S"),)).fetchone()[0]
    out["day"] = started.date().isoformat()
    out["text"] = describe(out)
    return out


def _index_here() -> dict:
    from . import actor_sources, actors, dating, doctypes, ocr, topics, works
    res = {"index-topics": topics.index()}
    if ocr.available():
        res["ocr"] = ocr.run()
    res["date-documents"] = dating.date_documents()
    res["type-documents"] = doctypes.type_documents()
    res["group-works"] = works.group()
    if actor_sources.GAZETTEER.exists():
        res["index-actors"] = actors.index()
    return res


def describe(out: dict) -> str:
    lines = []
    c = out.get("crawl")
    if c:
        lines.append(f"Checked {c['pages']} report pages: {c['new_docs']} new report{'s' if c['new_docs'] != 1 else ''} found"
                     f"{', ' + str(c['errors']) + ' pages with errors' if c['errors'] else ''}"
                     f"{', ' + str(c['skipped']) + ' skipped (manual or blocked)' if c['skipped'] else ''}.")
        for key, v in sorted(c.get("sources", {}).items(), key=lambda kv: -kv[1]["new"]):
            lines.append(f"  {key}: {v['new']} new" + (f", {v['errors']} errors" if v["errors"] else ""))
    d = out.get("download")
    if d is not None and "download" in out:
        lines.append("Downloads: " + (", ".join(f"{k} {v}" for k, v in sorted(d.items())) or "nothing waiting") + ".")
    if "titles_improved" in out:
        lines.append(f"Titles improved: {out['titles_improved']}.")
    for step, res in (out.get("index") or {}).items():
        lines.append(f"{step}: {res if isinstance(res, str) else 'done'}")
    return "\n".join(lines)


def page_state(status: str | None) -> str:
    """ok | error | blocked | skipped | never – the outcome of a page's last check."""
    s = status or ""
    if not s:
        return "never"
    if s.startswith("ok"):
        return "ok"
    if s.startswith("skipped"):
        return "skipped"
    if "robots" in s:
        return "blocked"
    return "error"


def sources_status(country: str = "", state: str = "", q: str = "", stale_days: int = 7) -> list[dict]:
    """Every active source with its pages' last check, outcome, and the reports found by that check – for the table."""
    cutoff = (dt.datetime.now() - dt.timedelta(days=stale_days)).isoformat(timespec="seconds")
    with db.session() as con:
        rows = []
        for s in con.execute("""SELECT s.id, s.key, s.country, s.agency, s.name_en, s.access,
                                       (SELECT COUNT(*) FROM documents d WHERE d.source_id=s.id AND d.hidden=0
                                        AND d.status NOT IN ('missing','duplicate','skipped')) docs,
                                       (SELECT COUNT(*) FROM documents d WHERE d.source_id=s.id AND d.status='new' AND d.hidden=0) waiting
                                FROM sources s WHERE s.active=1 ORDER BY s.country, s.agency"""):
            pages = con.execute("SELECT url, last_crawled, last_status FROM pages WHERE source_id=? AND active=1",
                                (s["id"],)).fetchall()
            states = [page_state(p["last_status"]) for p in pages]
            last = max((p["last_crawled"] or "" for p in pages), default="") or None
            oldest = min((p["last_crawled"] or "" for p in pages), default="") or None
            worst = next((x for x in ("error", "blocked", "never", "skipped", "ok") if x in states), "never")
            if s["access"] == "manual":
                worst = "manual"
            day = last[:10] if last else None
            new = con.execute("""SELECT COUNT(*) FROM documents WHERE source_id=? AND date(discovered_at)=? AND hidden=0
                                 AND status NOT IN ('missing','duplicate','skipped')""",      # as the Documents list counts
                              (s["id"], day)).fetchone()[0] if day else 0
            r = {**dict(s), "pages": len(pages), "last": last, "oldest": oldest, "state": worst,
                 "stale": not oldest or oldest < cutoff, "new_last": new, "day": day,
                 "statuses": [{"url": p["url"], "when": p["last_crawled"], "status": p["last_status"],
                               "state": page_state(p["last_status"])} for p in pages]}
            rows.append(r)
    if country:
        rows = [r for r in rows if r["country"] == country]
    if state == "stale":
        rows = [r for r in rows if r["stale"] and r["state"] != "manual"]
    elif state:
        rows = [r for r in rows if r["state"] == state]
    if q.strip():
        t = q.strip().casefold()
        rows = [r for r in rows if t in f"{r['key']} {r['name_en'] or ''}".casefold()]
    return rows


def history(limit: int = 30) -> list[dict]:
    """The last crawls and downloads (runs table), newest first."""
    with db.session() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT kind, started_at, finished_at, summary FROM runs WHERE kind IN ('crawl','download') ORDER BY id DESC LIMIT ?",
            (limit,))]
    for r in rows:
        try:
            r["data"] = json.loads(r["summary"])
        except (TypeError, ValueError):
            import ast
            try:
                r["data"] = ast.literal_eval(r["summary"])     # runs before 0.29.0 stored a Python repr
            except (ValueError, SyntaxError):
                r["data"] = {}
        a, b = r["started_at"], r["finished_at"]
        try:
            r["seconds"] = (dt.datetime.fromisoformat(b[:19]) - dt.datetime.fromisoformat(a[:19])).total_seconds()
        except (TypeError, ValueError):
            r["seconds"] = None
    return rows
