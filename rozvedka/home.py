"""Home page: the search console (operators, suggestions) and the dashboards of what is new in the library.

Every number on the home page comes with the Documents link that lists exactly what it counts; `figures()` returns
them all so tools/check_links.py can compare each count with its list.
"""
import datetime as dt
import re
from urllib.parse import urlencode

from . import actors, collect, countries, db, topics, trends

LISTED = trends.LISTED      # the Documents list's default: active sources, not hidden, not duplicate/skipped/missing
DOCS = "/documents"
TYPE_ALIASES = {"intelligence": "intelligence-civil", "civil": "intelligence-civil", "military": "intelligence-military",
                "foreign": "intelligence-military", "cyber": "cyber", "civil-protection": "civil-protection",
                "crisis": "civil-protection", "police": "police-ct", "ct": "police-ct", "eu": "eu-body", "nato": "nato"}
OPERATORS = {   # operator → what it filters (shown in the syntax help)
    "country": "country code or name – country:DE, country:Estonia",
    "coalition": "EU, NATO, FVEY … – coalition:NATO",
    "agency": "agency abbreviation, with country: if it is ambiguous – agency:BIS",
    "type": "agency type – type:cyber, type:military, type:police",
    "topic": "topic from the Topics page; repeat for several – topic:ransomware",
    "actor": "actor name or alias – actor:\"Fancy Bear\"",
    "year": "year or range – year:2024, year:2020..2024",
    "lang": "language code – lang:de",
}
_OP = re.compile(r'\b(' + "|".join(OPERATORS) + r'):("([^"]*)"|\S+)', re.I)


def docs_url(**params) -> str:
    return DOCS + ("?" + urlencode({k: v for k, v in params.items() if v not in ("", None, [], 0)}, doseq=True)
                   if any(v not in ("", None, [], 0) for v in params.values()) else "")


# ---------------------------------------------------------------- search console

def _fold(s: str) -> str:
    return topics.normalize(s or "").strip()


def _country(con, value: str) -> str | None:
    v = value.strip()
    names = countries.names()
    if v.upper() in names or con.execute("SELECT 1 FROM sources WHERE country=? AND active=1", (v.upper(),)).fetchone():
        return v.upper()
    return next((code for code, name in names.items() if _fold(name) == _fold(v)), None)


def _topic(value: str) -> str | None:
    tax = topics.taxonomy()["topics"]
    v = _fold(value)
    if value in tax:
        return value
    exact = [k for k, t in tax.items() if _fold(t["name"]) == v or _fold(k.replace("-", " ")) == v]
    starts = [k for k, t in tax.items() if _fold(t["name"]).startswith(v)]
    return (exact or (starts if len(starts) == 1 else [None]))[0]


def _actor(con, value: str) -> dict | None:
    """Actor by key (Q-id), label or used alias; the one named in most reports wins."""
    actors.init()
    row = con.execute(
        """SELECT a.key, a.label FROM actors a LEFT JOIN actor_names n ON n.actor_key=a.key AND n.status='used'
           WHERE a.key=? OR lower(a.label)=lower(?) OR lower(n.name)=lower(?)
           GROUP BY a.key ORDER BY (SELECT COUNT(*) FROM doc_actors WHERE actor_key=a.key) DESC LIMIT 1""",
        (value, value, value)).fetchone()
    return dict(row) if row else None


def _agency(con, value: str, country: str = "") -> list[dict]:
    rows = con.execute(
        """SELECT id, key, country, agency, name_en FROM sources WHERE active=1
           AND (lower(agency)=lower(?) OR lower(key)=lower(?) OR lower(name_en)=lower(?) OR lower(name_local)=lower(?))
           ORDER BY country, agency""", (value, value, value, value)).fetchall()
    rows = [dict(r) for r in rows]
    return [r for r in rows if r["country"] == country] if country and len(rows) > 1 else rows


def parse(query: str) -> dict:
    """Search-console text → Documents filters.

    Returns {"params": …, "text": free text, "problems": [{"token", "message", "options": [(label, query)]}]}.
    Free text is searched in titles, agency names and the full text (same as the Documents search box).
    """
    params: dict = {"topic": []}
    problems = []
    found = [(m.group(1).lower(), m.group(3) if m.group(3) is not None else m.group(2), m.group(0))
             for m in _OP.finditer(query)]
    text = _OP.sub(" ", query)
    text = re.sub(r"\s+", " ", text).strip()
    with db.session() as con:
        topics.init()
        for op, value, token in sorted(found, key=lambda f: f[0] != "country"):   # country first: it narrows agency
            value = value.strip()
            if op == "country":
                code = _country(con, value)
                if code:
                    params["country"] = code
                else:
                    problems.append({"token": token, "message": f"no country “{value}” in the library"})
            elif op == "coalition":
                key = next((k for k, c in countries.coalitions().items()
                            if _fold(k) == _fold(value) or _fold(c["short"]) == _fold(value)), None)
                if key:
                    params["coalition"] = key
                else:
                    problems.append({"token": token, "message": f"unknown coalition “{value}”",
                                     "options": [(c["short"], f"coalition:{c['short']}") for c in countries.coalitions().values()]})
            elif op == "type":
                v = value.lower()
                from .app import TYPE_NAMES
                key = v if v in TYPE_NAMES else TYPE_ALIASES.get(v)
                if key:
                    params["type"] = key
                else:
                    problems.append({"token": token, "message": f"unknown agency type “{value}”",
                                     "options": [(n, f"type:{k}") for k, n in TYPE_NAMES.items()]})
            elif op == "agency":
                rows = _agency(con, value, params.get("country", ""))
                if len(rows) == 1:
                    params["source"] = rows[0]["id"]
                elif rows:
                    problems.append({"token": token, "message": f"“{value}” is the name of {len(rows)} agencies – add country:",
                                     "options": [(f"{r['agency']} ({r['country']})", f"country:{r['country']} agency:{value}")
                                                 for r in rows]})
                else:
                    problems.append({"token": token, "message": f"no agency “{value}” – see the Sources page"})
            elif op == "topic":
                key = _topic(value)
                if key:
                    params["topic"].append(key)
                else:
                    tax = topics.taxonomy()["topics"]
                    close = [k for k, t in tax.items() if _fold(value) in _fold(t["name"])][:8]
                    problems.append({"token": token, "message": f"no topic “{value}”",
                                     "options": [(tax[k]["name"], f'topic:"{tax[k]["name"]}"') for k in close]})
            elif op == "actor":
                a = _actor(con, value)
                if a:
                    params["actor"] = a["key"]
                else:
                    problems.append({"token": token, "message": f"no actor named “{value}” – try the Actors page"})
            elif op == "year":
                m = re.fullmatch(r"(\d{4})(?:\s*(?:\.\.|-|–)\s*(\d{4}))?", value)
                if m and m.group(2):
                    params["year_from"], params["year_to"] = sorted((int(m.group(1)), int(m.group(2))))
                elif m:
                    params["year"] = int(m.group(1))
                else:
                    problems.append({"token": token, "message": f"year must be 2024 or 2020..2024, not “{value}”"})
            elif op == "lang":
                params["lang"] = value.lower()[:3]
    if text:
        params["q"] = text
    return {"params": params, "text": text, "problems": problems}


def suggest(q: str, limit: int = 6) -> dict:
    """Live suggestions for the search console, grouped; each item is a Documents link and its count.

    The count is what that link lists (the Documents default: active sources, not hidden, not duplicate).
    While an operator is being typed (`actor:fan`) only that operator's values are suggested.
    """
    q = q or ""
    last = re.search(r'(\w+):("[^"]*|\S*)$', q)
    if last and last.group(1).lower() in OPERATORS:      # an operator being typed: suggest its values
        op, term, prefix = last.group(1).lower(), last.group(2).lstrip('"'), q[:last.start()]
    else:                                                 # free text, perhaps after finished operators
        op, term, prefix = "", _OP.sub(" ", q), " ".join(m.group(0) for m in _OP.finditer(q))
    term, prefix = term.strip(), prefix.strip()
    out = {"q": q, "op": op, "prefix": prefix, "groups": []}
    if len(term) < 2 and op not in ("type", "coalition"):
        return out
    like = f"%{term}%"
    with db.session() as con:
        topics.init()
        actors.init()

        def n_docs(where: str, args: tuple) -> int:
            return con.execute(f"""SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                                   WHERE {LISTED} AND {where}""", args).fetchone()[0]

        if op in ("", "actor"):
            # the matching actors first (names only), then their reports: joining every name with every report
            # before filtering took seconds per keystroke
            rows = con.execute(
                f"""WITH m AS (SELECT a.key, MIN(CASE WHEN lower(a.label) LIKE lower(?) THEN NULL ELSE n.name END) alias
                               FROM actors a JOIN actor_names n ON n.actor_key=a.key AND n.status='used'
                               WHERE (a.label LIKE ? OR n.name LIKE ?) AND a.kind != 'country' GROUP BY a.key)
                    SELECT a.key, a.label, a.kind, a.description, m.alias, COUNT(DISTINCT d.id) n
                    FROM m JOIN actors a ON a.key=m.key JOIN doc_actors da ON da.actor_key=m.key
                    JOIN documents d ON d.id=da.doc_id JOIN sources s ON s.id=d.source_id
                    WHERE {LISTED} AND {actors.NOT_BEFORE_FOUNDED}
                    GROUP BY a.key ORDER BY n DESC LIMIT ?""", (like, like, like, limit)).fetchall()
            out["groups"].append({"name": "Actors", "items": [
                {"label": r["label"], "sub": (f"also “{r['alias']}” · " if r["alias"] else "") + actors.KINDS.get(r["kind"], r["kind"]),
                 "n": r["n"], "url": docs_url(actor=r["key"]), "page": f"/actors/{r['key']}",
                 "token": f'actor:"{r["label"]}"' if " " in r["label"] else f"actor:{r['label']}"} for r in rows]})
        if op in ("", "topic"):
            tax = topics.taxonomy()["topics"]
            keys = [k for k, t in tax.items() if _fold(term) in _fold(t["name"]) or _fold(term) in k][:limit]
            out["groups"].append({"name": "Topics", "items": [
                {"label": tax[k]["name"], "sub": tax[k].get("category_name", ""),
                 "n": n_docs("d.id IN (SELECT doc_id FROM doc_topics WHERE topic=?)", (k,)), "url": docs_url(topic=k),
                 "token": f'topic:"{tax[k]["name"]}"' if " " in tax[k]["name"] else f"topic:{tax[k]['name']}"}
                for k in keys]})
        if op in ("", "agency"):
            rows = con.execute(
                f"""SELECT s.id, s.country, s.agency, s.name_en, s.name_local, COUNT(d.id) n
                    FROM sources s LEFT JOIN documents d ON d.source_id=s.id AND d.hidden=0
                         AND d.status NOT IN ('missing','duplicate','skipped')
                    WHERE s.active=1 AND (s.agency LIKE ? OR s.name_en LIKE ? OR s.name_local LIKE ?)
                    GROUP BY s.id ORDER BY n DESC LIMIT ?""", (like, like, like, limit)).fetchall()
            out["groups"].append({"name": "Agencies", "items": [
                {"label": r["agency"], "sub": f"{r['country']} · {r['name_en'] or r['name_local'] or ''}", "n": r["n"],
                 "url": docs_url(source=r["id"]), "country": r["country"],
                 "token": f"country:{r['country']} agency:" + (f'"{r["agency"]}"' if " " in r["agency"] else r["agency"])}
                for r in rows]})
        if op in ("", "country"):
            names = countries.names()
            have = {r[0] for r in con.execute("SELECT DISTINCT country FROM sources WHERE active=1")}
            codes = [c for c in sorted(have, key=lambda c: names.get(c, c))
                     if _fold(names.get(c, c)).startswith(_fold(term)) or c.lower() == term.lower()][:limit]
            out["groups"].append({"name": "Countries", "items": [
                {"label": names.get(c, c), "sub": c, "n": n_docs("s.country=?", (c,)), "url": docs_url(country=c),
                 "country": c, "token": f"country:{c}"} for c in codes]})
        if op == "type":
            from .app import TYPE_NAMES
            out["groups"].append({"name": "Agency types", "items": [
                {"label": name, "sub": key, "n": n_docs("s.type=?", (key,)), "url": docs_url(type=key), "token": f"type:{key}"}
                for key, name in TYPE_NAMES.items() if not term or term.lower() in (key + " " + name).lower()]})
        if op == "coalition":
            out["groups"].append({"name": "Coalitions", "items": [
                {"label": c["name"], "sub": c["short"], "n": _coalition_docs(con, k), "url": docs_url(coalition=k),
                 "token": f"coalition:{c['short']}"}
                for k, c in countries.coalitions().items() if not term or term.lower() in (c["short"] + " " + c["name"]).lower()]})
    out["groups"] = [g for g in out["groups"] if g["items"]]
    if prefix:   # other filters are set: a suggestion runs the whole query, whose count is shown on the Documents page
        for g in out["groups"]:
            for it in g["items"]:
                it["url"], it["n"] = "/search?" + urlencode({"q": f"{prefix} {it['token']}"}), None
    return out


def _coalition_docs(con, key: str) -> int:
    codes = sorted(countries.scope(key))
    return con.execute(f"""SELECT COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                           WHERE {LISTED} AND s.country IN ({','.join('?' * len(codes))})""", codes).fetchone()[0]


EXAMPLES = [   # shown under the search box if they resolve in this library
    ('"critical infrastructure" country:DE', "a phrase in German agencies' reports"),
    ('actor:"Fancy Bear" year:2020..2025', "reports naming APT28, 2020–2025"),
    ("topic:drones coalition:NATO", "a topic across NATO members"),
    ("type:civil-protection blackout", "civil protection reports on blackouts"),
    ("agency:BIS lang:en", "one agency, English editions"),
]


def examples() -> list[dict]:
    out = []
    for q, note in EXAMPLES:
        p = parse(q)
        if not p["problems"]:
            out.append({"q": q, "note": note})
    return out


# ---------------------------------------------------------------- dashboards

def dashboard(today: dt.date | None = None) -> dict:
    """Numbers and lists for the home page. Each count has the Documents link that lists exactly those reports."""
    today = today or dt.date.today()
    year_now = today.year
    with db.session() as con:
        topics.init()
        actors.init()
        base = f"FROM documents d JOIN sources s ON s.id=d.source_id WHERE {LISTED}"
        one = lambda sql, args=(): con.execute(sql, args).fetchone()   # noqa: E731
        listed = one(f"SELECT COUNT(*) {base}")[0]
        totals = {
            "reports": {"n": listed, "url": DOCS},
            "agencies": {"n": one(f"SELECT COUNT(DISTINCT s.id) {base} AND {trends.OFFICIAL}")[0], "url": "/sources"},
            # independent publishers (think tanks): counted apart from the official agencies, always marked ◆
            "think_tanks": {"n": one(f"SELECT COUNT(DISTINCT s.id) {base} AND NOT {trends.OFFICIAL}")[0],
                            "url": "/sources#independent",
                            "reports": one(f"SELECT COUNT(*) {base} AND NOT {trends.OFFICIAL}")[0],
                            "reports_url": docs_url(type="think-tank")},
            "countries": {"n": one(f"SELECT COUNT(DISTINCT s.country) {base} AND s.country NOT IN ('EU','NATO','OTHER')")[0],
                          "url": "/map"},
            "languages": {"n": one(f"SELECT COUNT(DISTINCT d.lang) {base} AND d.lang != ''")[0], "url": DOCS},
            "searchable": {"n": one(f"SELECT COUNT(*) {base} AND {trends.CLASSIFIED}")[0], "url": docs_url(indexed=1),
                           "words": one(f"SELECT SUM(i.words) FROM documents d JOIN sources s ON s.id=d.source_id "
                                        f"JOIN doc_index i ON i.doc_id=d.id WHERE {LISTED} AND {trends.CLASSIFIED}")[0] or 0},
        }
        # newest editions: by publication year, then when they entered the library
        newest_year = one(f"SELECT MAX(d.year) {base} AND d.year <= ?", (year_now,))[0]
        newest = [dict(r) for r in con.execute(
            f"""SELECT d.id, d.title, d.year, d.lang, d.status, d.url, d.local_path, s.country, s.agency, s.id source_id
                {base} AND d.year <= ? ORDER BY d.year DESC, d.discovered_at DESC, d.id DESC LIMIT 8""", (year_now,))]
        newest_n = one(f"SELECT COUNT(*) {base} AND d.year=?", (newest_year,))[0] if newest_year else 0
        # recently added to the library
        added = []
        for days in (7, 30, 90):
            since = (today - dt.timedelta(days=days)).isoformat()
            added.append({"days": days, "since": since, "url": docs_url(added_from=since, sort="added"),
                          "n": one(f"SELECT COUNT(*) {base} AND date(d.discovered_at) >= ?", (since,))[0]})
        recent = [dict(r) for r in con.execute(
            f"""SELECT d.id, d.title, d.year, d.lang, d.status, d.url, d.local_path, d.discovered_at, s.country, s.agency, s.id source_id
                {base} ORDER BY d.discovered_at DESC, d.id DESC LIMIT 8""")]
        last_added = recent[0]["discovered_at"][:10] if recent else None
        first_added = (one(f"SELECT MIN(d.discovered_at) {base}")[0] or "")[:10] or None
        # reports by publication year: the last 15 years, older ones and undated ones – together all listed reports
        y0 = year_now - 14
        per_year = dict(con.execute(f"SELECT d.year, COUNT(*) {base} AND d.year BETWEEN ? AND ? GROUP BY d.year",
                                    (y0, year_now)).fetchall())
        years = [{"year": y, "n": per_year.get(y, 0), "url": docs_url(year=y), "partial": y == year_now}
                 for y in range(year_now, y0 - 1, -1)]
        older = {"n": one(f"SELECT COUNT(*) {base} AND d.year < ?", (y0,))[0], "url": docs_url(year_to=y0 - 1), "before": y0}
        later = one(f"SELECT COUNT(*) {base} AND d.year > ?", (year_now,))[0]     # misdated into the future
        undated = {"n": one(f"SELECT COUNT(*) {base} AND d.year IS NULL")[0], "url": docs_url(undated=1)}
        # by agency type
        from .app import TYPE_NAMES
        by_type = [{"key": r[0], "name": TYPE_NAMES.get(r[0], r[0]), "n": r[1], "url": docs_url(type=r[0])}
                   for r in con.execute(f"SELECT s.type, COUNT(*) n {base} GROUP BY s.type ORDER BY n DESC")]
        # actors named in the last complete year's reports (countries left out – they are named everywhere)
        actor_year = year_now - 1
        top_actors = [{"key": r["key"], "label": r["label"], "kind": actors.KINDS.get(r["kind"], r["kind"]), "n": r["n"],
                       "url": docs_url(actor=r["key"], year=actor_year), "page": f"/actors/{r['key']}"}
                      for r in con.execute(
                          f"""SELECT a.key, a.label, a.kind, COUNT(DISTINCT d.id) n FROM doc_actors da
                              JOIN actors a ON a.key=da.actor_key JOIN documents d ON d.id=da.doc_id
                              JOIN sources s ON s.id=d.source_id
                              WHERE {LISTED} AND d.year=? AND a.kind != 'country' AND {actors.NOT_BEFORE_FOUNDED}
                              GROUP BY a.key ORDER BY n DESC, a.label LIMIT 10""", (actor_year,))]
        actor_year_docs = one(f"SELECT COUNT(*) {base} AND d.year=?", (actor_year,))[0]
        # library status
        status = {r[0]: r[1] for r in con.execute(f"SELECT d.status, COUNT(*) {base} GROUP BY d.status")}
        health = [{"key": k, "label": label, "n": status.get(k, 0), "url": docs_url(status=k)}
                  for k, label in (("downloaded", "downloaded"), ("new", "waiting for download"),
                                   ("browser-only", "open in a browser only"), ("failed", "download failed"))]
    rise = trends.rising(limit=6)
    return {"today": today.isoformat(), "totals": totals,
            "newest": newest, "newest_year": newest_year, "newest_n": newest_n, "newest_url": docs_url(year=newest_year),
            "added": added, "recent": recent, "last_added": last_added, "recent_url": docs_url(sort="added"), "first_added": first_added,
            "years": years, "years_max": max([y["n"] for y in years] + [1]), "older": older, "undated": undated,
            "later": later, "by_type": by_type, "type_max": max([t["n"] for t in by_type] + [1]),
            "top_actors": top_actors, "actor_year": actor_year, "actor_year_docs": actor_year_docs,
            "actor_max": max([a["n"] for a in top_actors] + [1]),
            "health": health, "collect": collect.status_counts(), "fresh": collect.freshness(), "rising": rise}


def figures(d: dict) -> list[tuple[str, int, str]]:
    """Every (label, count, Documents link) on the home page – for checking that each count matches its list."""
    out = [("reports", d["totals"]["reports"]["n"], d["totals"]["reports"]["url"]),
           ("searchable", d["totals"]["searchable"]["n"], d["totals"]["searchable"]["url"]),
           ("think-tank reports", d["totals"]["think_tanks"]["reports"], d["totals"]["think_tanks"]["reports_url"]),
           ("newest year", d["newest_n"], d["newest_url"]),
           ("before", d["older"]["n"], d["older"]["url"]), ("undated", d["undated"]["n"], d["undated"]["url"])]
    out += [(f"added {a['days']} days", a["n"], a["url"]) for a in d["added"]]
    out += [(f"year {y['year']}", y["n"], y["url"]) for y in d["years"]]
    out += [(f"type {t['key']}", t["n"], t["url"]) for t in d["by_type"]]
    out += [(f"actor {a['label']}", a["n"], a["url"]) for a in d["top_actors"]]
    out += [(f"status {h['key']}", h["n"], h["url"]) for h in d["health"]]
    out += [(f"rising {r['key']} {p}", r[f"n_{p}"], r[f"link_{p}"]) for r in d["rising"]["rising"] for p in ("earlier", "recent")]
    return out
