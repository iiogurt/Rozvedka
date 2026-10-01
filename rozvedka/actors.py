"""Actor index – recognise the named actors of the gazetteer in the report texts (offline).

    python -m rozvedka fetch-actors     # network: build data/gazetteer/actors.json (rozvedka/actor_sources.py)
    python -m rozvedka index-actors     # local: find the actors in every report's text

Matching is by name, not by understanding: a report "mentions" an actor when one of the actor's names occurs in
its text. To keep that honest, every match keeps its position (→ page and passage), every name says where it
comes from, and names are dropped – visibly, with the reason – when they are likely to mean something else:

  - names on the ignore list or excluded for the actor in sources/actors.yaml
  - one-word names that are lowercase, shorter than 3 characters, or 3 characters without being an abbreviation
  - names shared by several actors (unless one of them was added by hand)
  - one-word names that the reports use more often in lowercase than capitalised (ordinary words: "base")
  - one-word names that are generic words ("Centro", "Intelligence"), and one-word names of people other than
    the surname ("Donald")
  - weak names – letters-only abbreviations up to 5 characters ("FSB") and names made only of generic words
    and numbers ("Federal Security Service", "National Security Council", "Group 24") – count in a report only
    when the report also uses another name of the same actor ("Federal Security Service (FSB)")
  - reports of sources excluded for an actor by hand (sources/actors.yaml exclude_sources)
  - reports dated before the actor was founded (Wikidata P571) are not counted; actor pages list them apart
  - where names overlap, only the longest counts ("Al-Qaeda in the Arabian Peninsula" is not also "Al-Qaeda")
  - qualifiers in brackets are removed from names ("Hells Angels (disbanded)" → "Hells Angels")

Case matters (proper names), accents do not; text in capitals (headings) matches too. Names added by hand may
also match with a short lowercase ending of the last word, for inflected languages ("Putina", "Putinův").
"""
import bisect
import concurrent.futures as cf
import hashlib
import json
import logging
import re
import unicodedata
from functools import lru_cache

import yaml

from . import db, topics, trends
from .actor_sources import CONFIG, GAZETTEER

log = logging.getLogger("rozvedka.actors")
MATCHER_VERSION = "5"
MAX_OFFSETS = 300        # positions kept per name and document
WINDOW = 600             # characters: two actors this close count as mentioned together (one passage)
SNIPPET = 260            # characters of context on each side of a match
TOKEN = re.compile(r"\w+")
CJK = topics._CJK
KINDS = {"state": "State services & state-linked", "cyber": "Cyber threat groups", "terror": "Terrorist-designated groups",
         "armed": "Armed groups & private military", "crime": "Organised crime", "movement": "Movements & networks",
         "person": "People", "other": "Other"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS actors (
    key TEXT PRIMARY KEY, qid TEXT, kind TEXT, label TEXT, description TEXT, data TEXT,
    since_year INTEGER);                          -- founded (Wikidata P571): earlier reports mean something else
CREATE TABLE IF NOT EXISTS actor_names (
    id INTEGER PRIMARY KEY, actor_key TEXT NOT NULL, name TEXT NOT NULL, tokens TEXT, langs TEXT, origins TEXT,
    status TEXT, reason TEXT, docs INTEGER DEFAULT 0, hits INTEGER DEFAULT 0, lower_hits INTEGER DEFAULT 0,
    weak INTEGER DEFAULT 0);                      -- weak by configuration (sources/actors.yaml weak_aliases)
CREATE INDEX IF NOT EXISTS ix_actor_names_actor ON actor_names(actor_key);
CREATE TABLE IF NOT EXISTS actor_hits (           -- raw: every match of every candidate name
    doc_id INTEGER NOT NULL, name_id INTEGER NOT NULL, n INTEGER, spans TEXT, PRIMARY KEY (doc_id, name_id));
CREATE TABLE IF NOT EXISTS actor_lower (          -- the same one-word names written in lowercase (ordinary words)
    doc_id INTEGER NOT NULL, name_id INTEGER NOT NULL, n INTEGER, PRIMARY KEY (doc_id, name_id));
CREATE TABLE IF NOT EXISTS doc_actors (           -- what the portal shows: actor mentions after the rules above
    doc_id INTEGER NOT NULL, actor_key TEXT NOT NULL, hits INTEGER, spans TEXT, names TEXT,
    PRIMARY KEY (doc_id, actor_key));
CREATE INDEX IF NOT EXISTS ix_doc_actors_actor ON doc_actors(actor_key);
CREATE TABLE IF NOT EXISTS actor_meta (k TEXT PRIMARY KEY, v TEXT);
"""


def init() -> None:
    topics.init()
    with db.session() as con:
        con.executescript(SCHEMA)
        if "actors_hash" not in {r["name"] for r in con.execute("PRAGMA table_info(doc_index)")}:
            con.execute("ALTER TABLE doc_index ADD COLUMN actors_hash TEXT")
        if "since_year" not in {r["name"] for r in con.execute("PRAGMA table_info(actors)")}:
            con.execute("ALTER TABLE actors ADD COLUMN since_year INTEGER")
        if "weak" not in {r["name"] for r in con.execute("PRAGMA table_info(actor_names)")}:
            con.execute("ALTER TABLE actor_names ADD COLUMN weak INTEGER DEFAULT 0")


# ── names → match keys ──
_FOLD_CASE = str.maketrans({"ß": "ss", "ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ł": "l",
                            "Ł": "L", "đ": "d", "Đ": "D", "ð": "d", "þ": "th", "ı": "i"})


@lru_cache(maxsize=500_000)
def fold(token: str) -> str:
    """Accents removed, case kept: 'Lukašenko' → 'Lukasenko'."""
    t = unicodedata.normalize("NFKD", token.translate(_FOLD_CASE))
    return "".join(c for c in t if not unicodedata.combining(c))


def name_tokens(name: str) -> tuple[str, ...]:
    return tuple(fold(t) for t in TOKEN.findall(name))


def is_abbreviation(tokens: tuple[str, ...]) -> bool:
    return len(tokens) == 1 and tokens[0].isalpha() and tokens[0].isupper() and len(tokens[0]) <= 5


# words that describe what an organisation is rather than which one: a name made only of these is "weak"
GENERIC = set("""
s the of for and against de del la el los las da do dos der die das des und für et du le les pour contre di e per
national nacional nationale nazionale federal federale state estado staat etat security seguridad sicherheit securite
sicurezza seguranca intelligence inteligencia inteligencia renseignement information informacion informations
service services servicio servicios servizio dienst dienste council consejo conseil rat bureau office oficina amt
agency agencia agence agenzia ministry ministerio ministere ministerium department departamento departement
directorate direccion direction direktion general central centro center centre zentrum main chief principal
defence defense defensa verteidigung military militar militaire militare foreign exterior exteriores external
internal interior interieur innere protection proteccion schutz counter terrorism terrorismo terrorisme
investigation investigacion police policia polizei community communications headquarters cyber army ejercito armee
liberation people peoples popular revolutionary front frente organization organisation organizacion group grupo
gruppe party partido partei movement movimiento bewegung crime crimen organized organised organizado branch special
secret unit command staff operations forces force guard republic government gobierno institute executive board
committee comite commission brigade battalion corps network action
""".split())


def is_generic(tokens: tuple[str, ...]) -> bool:
    return all(t.casefold() in GENERIC or t.isdigit() for t in tokens)


def is_weak(tokens: tuple[str, ...]) -> bool:
    return is_abbreviation(tokens) or is_generic(tokens)


def load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def load_gazetteer() -> dict:
    return json.loads(GAZETTEER.read_text(encoding="utf-8"))


def prepare_names(gaz: dict, cfg: dict) -> list[dict]:
    """One row per distinct name of each actor, with status 'used' or the reason it is not matched."""
    ignore = {name_tokens(n) for n in cfg.get("ignore_aliases", [])}
    weak_cfg = {k: {name_tokens(n) for n in v} for k, v in (cfg.get("weak_aliases") or {}).items()}
    excluded = {k: {name_tokens(n) for n in v} for k, v in (cfg.get("exclude_aliases") or {}).items()}
    rows: dict[tuple, dict] = {}
    for a in gaz["actors"]:
        for n in a["names"]:
            name = " ".join(re.sub(r"\([^)]*\)", " ", n["name"]).split())   # "X (disbanded)" → "X"
            toks = name_tokens(name)
            cjk = bool(CJK.search(name))
            key = (a["key"], name if cjk else toks)
            r = rows.setdefault(key, {"actor_key": a["key"], "name": name, "tokens": list(toks), "cjk": cjk,
                                      "langs": set(), "origins": set(), "manual": False, "seed": False,
                                      "person": a["kind"] == "person",
                                      "surname": (name_tokens(a["label"]) or ("",))[-1]})
            if n["lang"]:
                r["langs"].add(n["lang"])
            r["origins"].add(n["origin"])
            r["manual"] |= n["origin"].startswith("added by hand")
            r["seed"] |= any(x["via"] == "seed" for x in a["reasons"])
    # names shared by different actors
    owners: dict[tuple, set] = {}
    for (actor, k), r in rows.items():
        if not r["cjk"]:
            owners.setdefault(k, set()).add(actor)
    out = []
    for (actor, k), r in sorted(rows.items(), key=lambda x: (x[0][0], str(x[0][1]))):
        toks = tuple(r["tokens"])
        reason = None
        if r["cjk"]:
            if len(r["name"]) < 2:
                reason = "too short"
        elif not toks:
            reason = "no letters (or only a qualifier in brackets)"
        elif all(t.islower() or t.isdigit() for t in toks):
            reason = "lowercase words"
        elif len("".join(toks)) < 3 or (len(toks) > 1 and all(len(t) <= 2 for t in toks)):
            reason = "too short"
        elif toks in ignore:
            reason = "on the ignore list (sources/actors.yaml)"
        elif toks in excluded.get(actor, set()):
            reason = "excluded for this actor (sources/actors.yaml)"
        elif r["person"] and len(toks) == 1 and not r["manual"] and toks[0] != r["surname"]:
            reason = "one word of a person's name that is not the surname (first names are shared by many people)"
        elif len(toks) == 1 and is_generic(toks):
            reason = "a generic word"
        elif len(toks) == 1 and len(toks[0]) < 3:
            reason = "shorter than 3 characters"
        elif len(toks) == 1 and len(toks[0]) == 3 and not toks[0].isupper():
            reason = "3 letters without being an abbreviation"
        elif len(owners.get(k, ())) > 1:
            others = owners[k] - {actor}
            seeded = [o for o in owners[k] if rows[(o, k)]["seed"]]
            if not (r["seed"] and len(seeded) == 1):
                reason = "shared with " + ", ".join(sorted(others)[:5])
        out.append({"actor_key": actor, "name": r["name"], "tokens": r["tokens"], "cjk": r["cjk"],
                    "langs": sorted(r["langs"]), "origins": sorted(r["origins"]), "manual": r["manual"],
                    "status": "used" if reason is None else "ignored", "reason": reason,
                    "weak": toks in weak_cfg.get(actor, set())})
    for i, r in enumerate(out, 1):
        r["id"] = i
    return out


def names_hash(gaz: dict, cfg: dict) -> str:
    h = hashlib.sha256()
    h.update(MATCHER_VERSION.encode())
    h.update(json.dumps([(a["key"], a["names"]) for a in gaz["actors"]], ensure_ascii=False, sort_keys=True).encode())
    h.update(json.dumps(cfg, ensure_ascii=False, sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]


# ── matching (worker processes) ──
_M: dict = {}


def _init_matcher(names: list[dict]) -> None:
    first, single_long, upper, lower, cjk = {}, {}, {}, {}, []
    for n in names:
        if n["status"] != "used":
            continue
        if n["cjk"]:
            cjk.append((n["name"], n["id"]))
            continue
        toks = tuple(n["tokens"])
        first.setdefault(toks[0], []).append((toks, n["id"]))
        if n["manual"] and len(toks) == 1 and len(toks[0]) >= 5 and not is_abbreviation(toks):
            single_long.setdefault(toks[0], []).append((toks, n["id"]))
        up = tuple(t.upper() for t in toks)
        if up != toks and len("".join(up)) > 3:
            upper.setdefault(up[0], []).append((up, n["id"]))
        if len(toks) == 1 and not is_abbreviation(toks):
            lower.setdefault(toks[0].lower(), []).append(n["id"])
    _M.update(first=first, single_long=single_long, upper=upper, lower=lower, cjk=cjk)


def _inflected(t: str, base: str) -> bool:
    tail = t[len(base):]
    return t.startswith(base) and 0 < len(tail) <= 3 and tail.islower()


def match_text(text: str) -> tuple[dict[int, list], dict[int, int]]:
    """{name_id: [[start, end], …]} for every candidate name, and {name_id: n} of its lowercase uses."""
    hits: dict[int, list] = {}
    lower: dict[int, int] = {}
    spans = [(m.start(), m.end()) for m in TOKEN.finditer(text)]
    folded = [fold(text[s:e]) for s, e in spans]
    first, single_long, upper, low = _M["first"], _M["single_long"], _M["upper"], _M["lower"]
    n = len(folded)

    def add(name_id, i, j):
        lst = hits.setdefault(name_id, [])
        if len(lst) < MAX_OFFSETS:
            lst.append([spans[i][0], spans[j][1]])

    for i, t in enumerate(folded):
        for toks, name_id in first.get(t, ()):
            k = len(toks)
            if k == 1:
                add(name_id, i, i)
            elif i + k <= n and all(folded[i + j] == toks[j] for j in range(1, k)):
                add(name_id, i, i + k - 1)
        if len(t) >= 6 and t[-1].islower():
            for cut in (1, 2, 3):
                for toks, name_id in single_long.get(t[:-cut], ()):
                    if _inflected(t, toks[0]):
                        add(name_id, i, i)
        if len(t) > 3 and t.isupper():
            for toks, name_id in upper.get(t, ()):
                k = len(toks)
                if i + k <= n and all(folded[i + j] == toks[j] for j in range(1, k)):
                    add(name_id, i, i + k - 1)
        if t.islower():
            for name_id in low.get(t, ()):
                lower[name_id] = lower.get(name_id, 0) + 1
    if _M["cjk"] and CJK.search(text):
        for name, name_id in _M["cjk"]:
            start = text.find(name)
            while start >= 0 and len(hits.get(name_id, ())) < MAX_OFFSETS:
                hits.setdefault(name_id, []).append([start, start + len(name)])
                start = text.find(name, start + len(name))
    return _longest(hits), lower


def _longest(hits: dict[int, list]) -> dict[int, list]:
    """Where names overlap, keep the longest: "Islamic State of Iraq and the Levant" is not also
    "Islamic State of Iraq", "Al-Qaeda in the Arabian Peninsula" is not also "Al-Qaeda"."""
    spans = sorted(((s, e, nid) for nid, lst in hits.items() for s, e in lst), key=lambda x: (x[0], -(x[1] - x[0])))
    kept: dict[int, list] = {}
    end = -1
    for s, e, nid in spans:
        if s < end:       # starts inside a longer (or earlier, equally long) match
            continue
        kept.setdefault(nid, []).append([s, e])
        end = e
    return kept


def _match_doc(item: tuple[int, str]) -> tuple[int, dict, dict]:
    doc_id, body = item
    hits, lower = match_text(body or "")
    return doc_id, hits, lower


# ── indexing ──
def index(workers: int = 4, batch: int = 50, rematch: bool = False) -> dict:
    init()
    gaz, cfg = load_gazetteer(), load_config()
    names = prepare_names(gaz, cfg)
    h = names_hash(gaz, cfg)
    stats = {"actors": len(gaz["actors"]), "names_used": sum(n["status"] == "used" for n in names),
             "names_ignored": sum(n["status"] != "used" for n in names), "matched_docs": 0}
    con = db.connect()
    con.execute("PRAGMA synchronous=NORMAL")
    try:
        old = (con.execute("SELECT v FROM actor_meta WHERE k='names_hash'").fetchone() or [None])[0]
        if old != h or rematch:   # names changed: ids are new, every document is matched again
            con.executescript("DELETE FROM actor_hits; DELETE FROM actor_lower; DELETE FROM doc_actors;"
                              "DELETE FROM actor_names; DELETE FROM actors; UPDATE doc_index SET actors_hash=NULL;")
            con.executemany("INSERT INTO actors(key,qid,kind,label,description,data,since_year) VALUES(?,?,?,?,?,?,?)",
                            [(a["key"], a["qid"], a["kind"], a["label"], a["description"],
                              json.dumps(a, ensure_ascii=False), _year(a.get("inception"))) for a in gaz["actors"]])
            con.executemany("""INSERT INTO actor_names(id,actor_key,name,tokens,langs,origins,status,reason,weak)
                               VALUES(?,?,?,?,?,?,?,?,?)""",
                            [(n["id"], n["actor_key"], n["name"], json.dumps(n["tokens"], ensure_ascii=False),
                              ",".join(n["langs"]), json.dumps(n["origins"], ensure_ascii=False),
                              n["status"], n["reason"], int(n["weak"])) for n in names])
            con.execute("INSERT OR REPLACE INTO actor_meta VALUES('names_hash', ?)", (h,))
            con.execute("INSERT OR REPLACE INTO actor_meta VALUES('gazetteer_retrieved', ?)", (gaz["retrieved"],))
            con.commit()
        todo = [tuple(r) for r in con.execute(
            """SELECT i.doc_id, t.body FROM doc_index i JOIN doc_text t ON t.rowid=i.doc_id
               WHERE i.error IS NULL AND (i.actors_hash IS NULL OR i.actors_hash != ?)""", (h,))]
        with cf.ProcessPoolExecutor(workers, initializer=_init_matcher, initargs=(names,)) as ex:
            for k, (doc_id, hits, lower) in enumerate(ex.map(_match_doc, todo, chunksize=4), 1):
                con.execute("DELETE FROM actor_hits WHERE doc_id=?", (doc_id,))
                con.execute("DELETE FROM actor_lower WHERE doc_id=?", (doc_id,))
                con.executemany("INSERT INTO actor_hits VALUES(?,?,?,?)",
                                [(doc_id, nid, len(sp), json.dumps(sp)) for nid, sp in hits.items()])
                con.executemany("INSERT INTO actor_lower VALUES(?,?,?)", [(doc_id, nid, c) for nid, c in lower.items()])
                con.execute("UPDATE doc_index SET actors_hash=? WHERE doc_id=?", (h, doc_id))
                stats["matched_docs"] += 1
                if k % batch == 0:
                    con.commit()
                    log.info("actors matched in %d/%d documents", k, len(todo))
        con.commit()
        stats.update(derive(con, cfg))
        con.commit()
    finally:
        con.close()
    return stats


def derive(con, cfg: dict | None = None) -> dict:
    """Apply the corpus-wide rules to the raw matches and (re)build doc_actors."""
    cfg = cfg if cfg is not None else load_config()
    # per actor: sources whose reports use the name for something else (sources/actors.yaml exclude_sources)
    source_of = dict(con.execute("SELECT d.id, s.key FROM documents d JOIN sources s ON s.id=d.source_id").fetchall())
    skip_sources = {k: set(v) for k, v in (cfg.get("exclude_sources") or {}).items()}
    name_rows = {r["id"]: dict(r) for r in con.execute("SELECT * FROM actor_names")}
    totals = {r["name_id"]: (r["d"], r["n"]) for r in con.execute(
        "SELECT name_id, COUNT(*) d, SUM(n) n FROM actor_hits GROUP BY name_id")}
    lowers = dict(con.execute("SELECT name_id, SUM(n) FROM actor_lower GROUP BY name_id").fetchall())
    dropped = set()
    for nid, r in name_rows.items():
        d, n = totals.get(nid, (0, 0))
        low = lowers.get(nid, 0)
        status, reason = r["status"], r["reason"]
        if status == "used" or (reason or "").startswith("written in lowercase"):
            manual = "added by hand" in (r["origins"] or "")
            if low > n and not manual:
                status, reason = "ignored", f"written in lowercase more often than capitalised ({low} vs {n}) – an ordinary word"
            else:
                status, reason = "used", None
        if status != "used":
            dropped.add(nid)
        con.execute("UPDATE actor_names SET status=?, reason=?, docs=?, hits=?, lower_hits=? WHERE id=?",
                    (status, reason, d, n, low, nid))
    weak = {nid for nid, r in name_rows.items() if r["weak"] or is_weak(tuple(json.loads(r["tokens"] or "[]")))}
    con.execute("DELETE FROM doc_actors")
    cur = con.execute("SELECT doc_id, name_id, spans FROM actor_hits ORDER BY doc_id")
    written = 0

    def flush(doc_id, by_actor):
        nonlocal written
        rows = []
        for actor, items in by_actor.items():
            if source_of.get(doc_id) in skip_sources.get(actor, ()):
                continue        # excluded by hand for this source
            if all(nid in weak for nid, _ in items) and len(items) < 2:
                continue        # one weak name only: not corroborated by another name of the actor in this report
            spans = sorted(s for _, sp in items for s in sp)[:MAX_OFFSETS]
            used = {name_rows[nid]["name"]: len(sp) for nid, sp in items}
            rows.append((doc_id, actor, sum(len(sp) for _, sp in items), json.dumps(spans),
                         json.dumps(used, ensure_ascii=False)))
        con.executemany("INSERT INTO doc_actors VALUES(?,?,?,?,?)", rows)
        written += len(rows)

    current, by_actor = None, {}
    for r in cur:
        if r["name_id"] in dropped:
            continue
        if r["doc_id"] != current:
            if current is not None:
                flush(current, by_actor)
            current, by_actor = r["doc_id"], {}
        by_actor.setdefault(name_rows[r["name_id"]]["actor_key"], []).append((r["name_id"], json.loads(r["spans"])))
    if current is not None:
        flush(current, by_actor)
    return {"mentions": written, "names_dropped_as_words": sum(
        1 for nid in dropped if (name_rows[nid]["reason"] or "").startswith("written in lowercase"))}


def _year(date: str | None) -> int | None:
    return int(date[:4]) if date and date[:4].isdigit() else None


# a report dated before the actor was founded uses the name for something else ("Wagner" in 2011)
NOT_BEFORE_FOUNDED = "(a.since_year IS NULL OR d.year IS NULL OR d.year >= a.since_year)"


def doc_clause() -> str:
    """Documents-page filter: reports that mention actor ? (same rule as the actor pages)."""
    return f"""d.id IN (SELECT da.doc_id FROM doc_actors da JOIN actors a ON a.key=da.actor_key
                        JOIN documents d ON d.id=da.doc_id WHERE da.actor_key=? AND {NOT_BEFORE_FOUNDED})"""


# ── queries for the portal ──
def kind_name(kind: str) -> str:
    return KINDS.get(kind, kind)


def actor_list(kind: str = "", q: str = "", min_docs: int = 1) -> list[dict]:
    where, args, _ = trends.scope()
    sql = f"""SELECT a.key, a.qid, a.kind, a.label, a.description, COUNT(DISTINCT da.doc_id) docs,
                     COUNT(DISTINCT d.source_id) agencies, COUNT(DISTINCT s.country) countries,
                     MIN(d.year) y0, MAX(d.year) y1
              FROM actors a JOIN doc_actors da ON da.actor_key=a.key JOIN documents d ON d.id=da.doc_id
              JOIN sources s ON s.id=d.source_id WHERE {where} AND {NOT_BEFORE_FOUNDED}"""
    if kind:
        sql += " AND a.kind=?"; args.append(kind)
    if q.strip():
        sql += " AND (a.label LIKE ? OR a.key IN (SELECT actor_key FROM actor_names WHERE name LIKE ?))"
        args += [f"%{q.strip()}%"] * 2
    sql += " GROUP BY a.key HAVING docs >= ? ORDER BY docs DESC, a.label"
    args.append(min_docs)
    with db.session() as con:
        init()
        return [dict(r) for r in con.execute(sql, args)]


def _snippet(body: str, start: int, end: int) -> dict:
    a = max(0, start - SNIPPET)
    b = min(len(body), end + SNIPPET)
    if a > 0:
        a = body.find(" ", a, start) + 1 or a
    if b < len(body):
        b = body.rfind(" ", end, b) if body.rfind(" ", end, b) > end else b
    clean = lambda s: " ".join(s.split())  # noqa: E731
    return {"before": ("…" if a > 0 else "") + clean(body[a:start]) + " ", "match": clean(body[start:end]),
            "after": " " + clean(body[end:b]) + ("…" if b < len(body) else "")}


def actor_detail(key: str, passages: int = 40) -> dict | None:
    where, args, _ = trends.scope()
    with db.session() as con:
        init()
        row = con.execute("SELECT * FROM actors WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        data = json.loads(row["data"])
        names = [dict(r) for r in con.execute(
            "SELECT * FROM actor_names WHERE actor_key=? ORDER BY status DESC, hits DESC, name", (key,))]
        for n in names:
            n["origins"] = json.loads(n["origins"] or "[]")
        docs = [dict(r) for r in con.execute(
            f"""SELECT da.doc_id, da.hits, da.spans, da.names, d.title, d.year, d.lang, d.url, d.status, d.local_path,
                       s.id source_id, s.agency, s.country, s.name_en, i.pages
                FROM doc_actors da JOIN documents d ON d.id=da.doc_id JOIN sources s ON s.id=d.source_id
                JOIN doc_index i ON i.doc_id=d.id
                WHERE da.actor_key=? AND {where} ORDER BY d.year DESC NULLS LAST, da.hits DESC""", (key, *args))]
        since = row["since_year"]
        before = [d for d in docs if since and d["year"] and d["year"] < since]
        docs = [d for d in docs if d not in before]
        # per year: documents mentioning the actor ÷ documents in scope (same base as the Trends pages)
        years = sorted({d["year"] for d in docs if d["year"] and d["year"] >= trends.MIN_YEAR})
        timeline = []
        if years:
            den = dict(con.execute(f"""SELECT d.year, COUNT(*) FROM documents d JOIN sources s ON s.id=d.source_id
                                       WHERE {where} AND {trends.CLASSIFIED} AND d.year BETWEEN ? AND ? GROUP BY d.year""",
                                   (*args, years[0], years[-1])).fetchall())
            for y in range(years[0], years[-1] + 1):
                n = sum(1 for d in docs if d["year"] == y)
                timeline.append({"year": y, "docs": n, "of": den.get(y, 0),
                                 "share": round(n / den[y], 4) if den.get(y) else None,
                                 "link": trends.docs_url({"actor": key}, year=y)})
        agencies: dict[int, dict] = {}
        for d in docs:
            a = agencies.setdefault(d["source_id"], {"source_id": d["source_id"], "agency": d["agency"],
                                                    "country": d["country"], "name_en": d["name_en"], "docs": 0,
                                                    "y0": d["year"], "y1": d["year"]})
            a["docs"] += 1
            if d["year"]:
                a["y0"] = min(a["y0"] or d["year"], d["year"]); a["y1"] = max(a["y1"] or d["year"], d["year"])
        doc_ids = [d["doc_id"] for d in docs]
        topic_rows, related = [], []
        if doc_ids:
            marks = ",".join("?" * len(doc_ids))
            tax = topics.taxonomy()["topics"]
            topic_rows = [{"key": r["topic"], "name": tax.get(r["topic"], {}).get("name", r["topic"]), "docs": r["n"],
                           "link": f"/?actor={key}&topic={r['topic']}"}
                          for r in con.execute(f"""SELECT topic, COUNT(*) n FROM doc_topics WHERE doc_id IN ({marks})
                                                   GROUP BY topic ORDER BY n DESC LIMIT 15""", doc_ids)
                          if not tax.get(r["topic"], {}).get("meta")]
            related = _related(con, key, docs, marks, doc_ids)
        shown = []
        for d in docs[:passages]:
            body = con.execute("SELECT body FROM doc_text WHERE rowid=?", (d["doc_id"],)).fetchone()[0] or ""
            s, e = json.loads(d["spans"])[0]
            pages = json.loads(d["pages"]) if d["pages"] else None
            page = topics.page_of(pages, s)
            shown.append({**{k: d[k] for k in ("doc_id", "title", "year", "agency", "country", "lang", "hits", "url")},
                          "names": json.loads(d["names"]), "page": page, **_snippet(body, s, e),
                          "open": f"/doc/{d['doc_id']}" + (f"#page={page}" if page else "")})
    return {"actor": data, "row": dict(row), "names": names, "docs": len(docs), "timeline": timeline,
            "agencies": sorted(agencies.values(), key=lambda a: -a["docs"]), "topics": topic_rows,
            "related": related, "passages": shown, "kind_name": kind_name(row["kind"]), "window": WINDOW,
            "before": [{**{k: d[k] for k in ("doc_id", "title", "year", "agency", "country")},
                        "names": json.loads(d["names"])} for d in before]}


def _related(con, key: str, docs: list[dict], marks: str, doc_ids: list[int], limit: int = 25) -> list[dict]:
    """Actors mentioned within WINDOW characters of this actor (same passage), counted per document."""
    mine = {d["doc_id"]: [s for s, _ in json.loads(d["spans"])] for d in docs}
    together: dict[str, set] = {}
    for r in con.execute(f"SELECT doc_id, actor_key, spans FROM doc_actors WHERE doc_id IN ({marks}) AND actor_key != ?",
                         (*doc_ids, key)):
        own = mine[r["doc_id"]]
        for s, _ in json.loads(r["spans"]):
            i = bisect.bisect_left(own, s - WINDOW)
            if i < len(own) and own[i] <= s + WINDOW:
                together.setdefault(r["actor_key"], set()).add(r["doc_id"])
                break
    if not together:
        return []
    labels = {r["key"]: (r["label"], r["kind"]) for r in con.execute(
        f"SELECT key, label, kind FROM actors WHERE key IN ({','.join('?' * len(together))})", list(together))}
    out = [{"key": k, "label": labels[k][0], "kind": labels[k][1], "docs": len(v)} for k, v in together.items()]
    return sorted(out, key=lambda x: (-x["docs"], x["label"]))[:limit]


def stamp() -> dict:
    with db.session() as con:
        init()
        return dict(con.execute("SELECT k, v FROM actor_meta").fetchall())


def top_names(limit: int = 300, status: str = "used") -> list[dict]:
    """Names with the most matches – the place to spot a name that means something else."""
    with db.session() as con:
        init()
        rows = [dict(r) for r in con.execute(
            """SELECT n.*, a.label, a.kind FROM actor_names n JOIN actors a ON a.key=n.actor_key
               WHERE n.status=? AND n.docs > 0 ORDER BY n.docs DESC, n.hits DESC LIMIT ?""", (status, limit))]
    for r in rows:
        r["origins"] = json.loads(r["origins"] or "[]")
        r["weak"] = is_weak(tuple(json.loads(r["tokens"] or "[]")))
    return rows
