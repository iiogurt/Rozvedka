"""Research notebooks: passages marked in reports and books, with notes, in named notebooks – one shared set, no
per-user state.

Kept in data/notebooks.yaml: written by the portal, editable by hand, never committed, and carried only by personal
backups (rozvedka/dataset.py) – what someone quotes says what they are working on. A note keeps the passage's exact
wording and its place (report id, character offsets in the indexed text, page), so it still reads the same if the
report is re-indexed; the citation (agency, title, year, page, official URL, retrieval date) is formed from the library
when the notebook is shown or exported.
"""
import datetime as dt
import hashlib
import json
import re
import unicodedata

import yaml

from . import config, db, topics

HEADER = """# Research notebooks – passages marked on the portal (/notebooks), with notes. Written by the portal; editable by hand.
# Kept for personal use: never committed, carried only by personal backups.
"""
MAX_PASSAGE = 1500       # characters of a passage (a pasted one is cut to this; an actor passage is one or two sentences)
MAX_NOTE = 4000
SENTENCE = 400           # how far an actor passage is widened to whole sentences, each side
PUBLISHER_KIND = {"official": "official", "independent": "think tank", "commercial": "commercial analyst"}


def path():
    return config.DATA / "notebooks.yaml"


def load(p=None) -> dict:
    p = p or path()
    raw = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}
    books = [b for b in (raw.get("notebooks") or []) if isinstance(b, dict) and b.get("slug") and b.get("name")]
    for b in books:
        b["notes"] = [n for n in (b.get("notes") or []) if isinstance(n, dict) and n.get("id") and n.get("doc")]
    current = raw.get("current") if any(b["slug"] == raw.get("current") for b in books) else None
    return {"current": current or (books[0]["slug"] if books else None), "notebooks": books}


def save(data: dict, p=None) -> None:
    p = p or path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(HEADER + yaml.safe_dump({"current": data.get("current"), "notebooks": data["notebooks"]},
                                         allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")


def slugify(name: str) -> str:
    """The notebook's address: lower case, accents dropped, letters of any script kept, anything else a hyphen."""
    s = "".join(ch for ch in unicodedata.normalize("NFKD", name.lower()) if not unicodedata.combining(ch))
    return re.sub(r"[\W_]+", "-", s).strip("-")[:60] or "notebook"


def _get(data: dict, slug: str) -> dict | None:
    return next((b for b in data["notebooks"] if b["slug"] == slug), None)


def create(name: str) -> dict:
    """A new, empty notebook (it becomes the current one) – or the existing one of that name."""
    name = " ".join(name.split())[:120]
    if not name:
        return {"error": "a notebook needs a name"}
    data = load()
    same = next((b for b in data["notebooks"] if b["name"].casefold() == name.casefold()), None)
    if same:
        data["current"] = same["slug"]
        save(data)
        return {"exists": same["slug"]}
    slug, base, i = slugify(name), slugify(name), 2
    while _get(data, slug):
        slug, i = f"{base}-{i}", i + 1
    data["notebooks"].append({"slug": slug, "name": name, "created": dt.date.today().isoformat(), "notes": []})
    data["current"] = slug
    save(data)
    return {"added": slug}


def rename(slug: str, name: str) -> bool:
    name = " ".join(name.split())[:120]
    data = load()
    b = _get(data, slug)
    if not b or not name:
        return False
    b["name"] = name
    save(data)
    return True


def delete(slug: str) -> bool:
    data = load()
    keep = [b for b in data["notebooks"] if b["slug"] != slug]
    if len(keep) == len(data["notebooks"]):
        return False
    data["notebooks"] = keep
    if data["current"] == slug:
        data["current"] = keep[0]["slug"] if keep else None
    save(data)
    return True


def set_current(slug: str) -> bool:
    data = load()
    if not _get(data, slug):
        return False
    data["current"] = slug
    save(data)
    return True


# ── passages ──
def _body(con, doc_id: int) -> str:
    row = con.execute("SELECT body FROM doc_text WHERE rowid=?", (doc_id,)).fetchone()
    return (row[0] if row else "") or ""


def _offsets(con, doc_id: int) -> list[int] | None:
    row = con.execute("SELECT pages FROM doc_index WHERE doc_id=?", (doc_id,)).fetchone()
    return json.loads(row[0]) if row and row[0] else None


def find(body: str, text: str) -> tuple[int, int] | None:
    """Where a passage copied from the report (PDF viewer, another page) sits in its indexed text: the same words in
    the same order, whatever the line breaks, hyphens at line ends, spacing and case between them."""
    words = re.findall(r"[^\W_]+", text)[:200]
    if not words:
        return None
    # between two words: any spacing or punctuation – or nothing, for a word the copy split at a line end
    # ("infra- structure") that the text holds whole
    rx = re.compile(re.escape(words[0]) + "".join(r"[\W_]*" + re.escape(w) for w in words[1:]), re.IGNORECASE)
    m = rx.search(body)
    if not m:
        return None
    end = m.end()
    if re.search(r"[^\w\s]$", text.strip()):          # punctuation copied after the last word: take it from the text too
        end += len(re.match(r"[^\w\s]*", body[end:]).group())
    return m.start(), end


def _sentence(body: str, start: int, end: int) -> tuple[int, int]:
    """A passage widened to the whole sentence(s) it is part of (at most SENTENCE characters each side)."""
    lo = max(0, start - SENTENCE)
    cut = [m.end() for m in re.finditer(r"[.!?…]\s+(?=[\"“«(\[]?[A-ZÀ-ÞА-ЯΑ-Ω0-9])|\n\s*\n", body[lo:start])]
    a = lo + cut[-1] if cut else (body.rfind(" ", lo, start) + 1 if lo > 0 else 0)
    hi = min(len(body), end + SENTENCE)
    m = re.search(r"[.!?…](?=\s|$)|\n\s*\n", body[end:hi])
    b = end + m.end() if m else (body.rfind(" ", end, hi) if hi < len(body) and body.rfind(" ", end, hi) > end else hi)
    return a, b


def _note_id(ref: str, start: int, end: int) -> str:
    """The same passage of the same file has the same id in every library (report ids differ between libraries)."""
    return hashlib.sha1(f"{ref}:{start}:{end}".encode()).hexdigest()[:10]


def add(doc_id: int, start: int, end: int, note: str = "", slug: str | None = None, widen: bool = False) -> dict:
    """Mark the passage at [start, end) of a report's indexed text in a notebook (the current one by default).
    widen: extend it to whole sentences (a name found in a passage → the sentence naming it)."""
    data = load()
    slug = slug or data["current"]
    if not slug:
        create("Notes")
        data = load()
        slug = data["current"]
    b = _get(data, slug)
    if b is None:
        return {"error": "no such notebook"}
    with db.session() as con:
        body = _body(con, doc_id)
        if not body or not 0 <= start < end <= len(body):
            return {"error": "the report has no indexed text at that place"}
        if widen:
            start, end = _sentence(body, start, end)
        end = min(end, start + MAX_PASSAGE)
        offsets = _offsets(con, doc_id)
        url, sha = con.execute("SELECT url, sha256 FROM documents WHERE id=?", (doc_id,)).fetchone() or (None, None)
    quote = " ".join(body[start:end].split())
    nid = _note_id(sha or url or str(doc_id), start, end)
    if any(n["id"] == nid for n in b["notes"]):
        return {"exists": nid, "notebook": b["name"], "slug": slug}
    # url and sha256 find the report again in another library (a personal backup restored elsewhere)
    b["notes"].append({"id": nid, "doc": doc_id, "url": url, "sha256": sha, "start": start, "end": end,
                       "page": topics.page_of(offsets, start), "quote": quote, "note": note.strip()[:MAX_NOTE],
                       "added": dt.datetime.now().isoformat(timespec="seconds")})
    data["current"] = slug
    save(data)
    return {"added": nid, "notebook": b["name"], "slug": slug}


def add_text(doc_id: int, text: str, note: str = "", slug: str | None = None) -> dict:
    """Mark a passage given as text (pasted from the report): found in the indexed text, kept as worded there."""
    with db.session() as con:
        body = _body(con, doc_id)
    if not body:
        return {"error": "the report has no indexed text to find the passage in"}
    at = find(body, text[:MAX_PASSAGE * 2])
    if at is None:
        return {"error": "the passage was not found in the report's text – copy it as it appears, a sentence or two"}
    return add(doc_id, at[0], at[1], note, slug)


def _update_note(slug: str, nid: str, fn) -> bool:
    data = load()
    b = _get(data, slug)
    n = next((n for n in (b["notes"] if b else []) if n["id"] == nid), None)
    if n is None:
        return False
    fn(b, n)
    save(data)
    return True


def set_note(slug: str, nid: str, note: str) -> bool:
    return _update_note(slug, nid, lambda b, n: n.update(note=note.strip()[:MAX_NOTE]))


def remove(slug: str, nid: str) -> bool:
    return _update_note(slug, nid, lambda b, n: b["notes"].remove(n))


def move(slug: str, nid: str, step: int) -> bool:
    def mv(b, n):
        i = b["notes"].index(n)
        j = max(0, min(len(b["notes"]) - 1, i + step))
        b["notes"].insert(j, b["notes"].pop(i))
    return _update_note(slug, nid, mv)


def _clean_note(n) -> dict | None:
    """A passage from a backup file (anyone could have written it): only the known fields, of the right types."""
    if not isinstance(n, dict) or not isinstance(n.get("quote"), str) or not str(n.get("id") or "").isalnum():
        return None
    num = lambda v: v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None  # noqa: E731
    text = lambda v, k: v[:k] if isinstance(v, str) else None  # noqa: E731
    return {"id": str(n["id"])[:20], "doc": num(n.get("doc")), "url": text(n.get("url"), 2000), "sha256": text(n.get("sha256"), 64),
            "start": num(n.get("start")) or 0, "end": num(n.get("end")) or 0, "page": num(n.get("page")),
            "quote": n["quote"][:MAX_PASSAGE], "note": text(n.get("note"), MAX_NOTE) or "", "added": text(str(n.get("added") or ""), 25)}


def merge(theirs: dict) -> dict:
    """A personal backup's notebooks added to these: new notebooks whole, new passages into notebooks of the same name.
    Each passage is tied to this library's copy of its report (same file, else same address); passages of reports
    this library does not hold are left out. Returns {added, missing}."""
    data, added, missing = load(), 0, 0
    with db.session() as con:
        def local(n: dict) -> int | None:
            for col in ("sha256", "url"):
                if n.get(col):
                    r = con.execute(f"SELECT id FROM documents WHERE {col}=? ORDER BY id LIMIT 1", (n[col],)).fetchone()
                    if r:
                        return r[0]
            return None
        for tb in theirs.get("notebooks") or []:
            if not isinstance(tb, dict) or not isinstance(tb.get("name"), str) or not tb["name"].strip():
                continue
            name = " ".join(tb["name"].split())[:120]
            ours = next((b for b in data["notebooks"] if b["name"].casefold() == name.casefold()), None)
            if ours is None:
                base = slugify(str(tb.get("slug") or name))
                slug, i = base, 2
                while _get(data, slug):
                    slug, i = f"{base}-{i}", i + 1
                created = tb.get("created")
                ours = {"slug": slug, "name": name, "created": str(created)[:10] if created else dt.date.today().isoformat(),
                        "notes": []}
                data["notebooks"].append(ours)
            have = {n["id"] for n in ours["notes"]}
            for raw in tb.get("notes") or []:
                n = _clean_note(raw)
                if n is None or n["id"] in have:
                    continue
                n["doc"] = local(n)
                if n["doc"] is None:
                    missing += 1
                    continue
                ours["notes"].append(n)
                have.add(n["id"])
                added += 1
    if data["notebooks"] and not data["current"]:
        data["current"] = data["notebooks"][0]["slug"]
    save(data)
    return {"added": added, "missing": missing}


# ── reading and citing ──
def _sources(doc_ids: list[int]) -> dict[int, dict]:
    if not doc_ids:
        return {}
    ph = ",".join("?" * len(doc_ids))
    with db.session() as con:
        rows = {r["id"]: dict(r) for r in con.execute(
            f"""SELECT d.id, d.source_id, d.title, d.year, d.url, d.lang, d.local_path, d.downloaded_at, d.discovered_at,
                       s.agency, s.name_en, s.name_local, s.country, COALESCE(s.publisher, 'official') publisher,
                       u.official hand_official
                FROM documents d JOIN sources s ON s.id=d.source_id LEFT JOIN uploads u ON u.doc_id=d.id
                WHERE d.id IN ({ph})""", doc_ids)}
        try:
            for r in con.execute(f"SELECT doc_id, title, authors, publisher, year FROM books WHERE doc_id IN ({ph})", doc_ids):
                if r["doc_id"] in rows:
                    rows[r["doc_id"]]["book"] = dict(r) | {"authors": [a.get("name", a) if isinstance(a, dict) else a
                                                                        for a in json.loads(r["authors"] or "[]")]}
        except Exception:  # noqa: BLE001 - no books table in this library
            pass
    return rows


def cite(src: dict | None, page: int | None, doc_id: int) -> dict:
    """The citation of a passage: text (Markdown-free), the official address, the publisher kind, warnings."""
    from . import books
    where = books.page_name(doc_id, page) if page else ""
    if src is None:
        return {"text": f"Report {doc_id} (no longer in the library){', ' + where if where else ''}.", "url": None,
                "kind": None, "warn": "no longer in the library"}
    retrieved = (src.get("downloaded_at") or src.get("discovered_at") or "")[:10]
    if src.get("book"):
        b = src["book"]
        who = "; ".join(b["authors"]) or src["agency"]
        text = f"{who}, {b['title'] or src['title']}" + (f" ({b['publisher']}" if b.get("publisher") else " (") \
               + (f", {b['year']})" if b.get("year") else ")") + (f", {where}" if where else "") + "."
        return {"text": text.replace(" ()", ""), "url": None, "kind": "book", "warn": None}
    agency = src["agency"] + (f" – {src['name_en']}" if src.get("name_en") and src["name_en"] != src["agency"] else "")
    text = (f"{agency} ({src['country']}), “{src['title'] or 'untitled'}”, {src['year'] or 'n.d.'}"
            + (f", {where}" if where else "") + "." + (f" Retrieved {retrieved}." if retrieved else ""))
    warn = "added by hand from an address outside the agency's official domains" if src.get("hand_official") == 0 else None
    return {"text": text, "url": src["url"], "kind": PUBLISHER_KIND.get(src["publisher"], src["publisher"]), "warn": warn}


def overview() -> dict:
    data = load()
    return {"current": data["current"], "notebooks": [
        {"slug": b["slug"], "name": b["name"], "created": b.get("created"), "n": len(b["notes"]),
         "reports": len({n["doc"] for n in b["notes"]}), "last": max((n.get("added") or "" for n in b["notes"]), default="")[:10]}
        for b in data["notebooks"]]}


def notebook(slug: str) -> dict | None:
    """A notebook with every passage, its citation and the report it comes from."""
    data = load()
    b = _get(data, slug)
    if b is None:
        return None
    srcs = _sources(sorted({n["doc"] for n in b["notes"]}))
    notes = []
    for i, n in enumerate(b["notes"]):
        src = srcs.get(n["doc"])
        notes.append(n | {"n": i + 1, "src": src, "cite": cite(src, n.get("page"), n["doc"]),
                          "pdf": f"/doc/{n['doc']}" + (f"#page={n['page']}" if n.get("page") else "") if src and src.get("local_path") else None})
    kinds = sorted({x["cite"]["kind"] for x in notes if x["cite"]["kind"]})
    return {"slug": b["slug"], "name": b["name"], "created": b.get("created"), "current": data["current"] == slug,
            "notes": notes, "kinds": kinds, "reports": len(srcs)}


def markdown(slug: str, base: str) -> str | None:
    """The notebook as Markdown: every passage quoted, its note, and a numbered citation with the official address."""
    nb = notebook(slug)
    if nb is None:
        return None
    out = [f"# {nb['name']}", "",
           f"Exported {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} from Rozvedka ({base}). {len(nb['notes'])} passage"
           f"{'s' if len(nb['notes']) != 1 else ''} from {nb['reports']} report{'s' if nb['reports'] != 1 else ''}"
           + (f" – publishers: {', '.join(nb['kinds'])}" if nb["kinds"] else "") + ". Every passage is quoted as worded "
           "in the library's text of the report; the page is the page of the file.", ""]
    for x in nb["notes"]:
        out += [f"## {x['n']}. {x['src']['title'] if x['src'] else 'Report ' + str(x['doc'])}", ""]
        out += ["> " + x["quote"] + f" [{x['n']}]", ""]
        if x["note"]:
            out += [x["note"], ""]
    out += ["## Sources", ""]
    for x in nb["notes"]:
        c = x["cite"]
        out.append(f"{x['n']}. {c['text']}" + (f" <{c['url']}>" if c["url"] else "")
                   + (f" – {c['kind']}" if c["kind"] and c["kind"] != "official" else "")
                   + (f" – {c['warn']}" if c["warn"] else "") + f" In the library: <{base}/report/{x['doc']}>")
    out.append("")
    return "\n".join(out)
