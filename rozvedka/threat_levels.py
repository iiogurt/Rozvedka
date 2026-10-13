"""Terrorism threat levels of states over time, as the official sources state them – each with its passage.

sources/threat_levels.yaml is hand-curated, two kinds of entry:
  report        – a level that a report in this library states. The quote must be in the stored text of that report; this is
                  checked against the library every time (no network) and the page of the passage is found from it.
  announcement  – an official notice of a change (UK MI5), on a page the crawler may fetch; `fetch-threat-levels` downloads
                  the page and confirms the quote, and the result is stored with the retrieval date.
A report that states a level shows the level at that time only – not when it began, and not a complete history."""
import datetime as dt
import json
import logging
import re
from functools import lru_cache

import yaml

from . import actors, attributions, db, fetch, topics
from .config import DATA, ROOT

log = logging.getLogger(__name__)
FILE = ROOT / "sources" / "threat_levels.yaml"
CHECKS = DATA / "gazetteer" / "threat_levels.json"
normalise = attributions.normalise


@lru_cache(maxsize=2)
def _load(mtime: float) -> tuple:
    return tuple(yaml.safe_load(FILE.read_text(encoding="utf-8")).get("threat_levels", []))


def load() -> list[dict]:
    return [dict(e) for e in _load(FILE.stat().st_mtime)] if FILE.exists() else []


def scale_max(scale: str) -> int | None:
    m = re.match(r"\s*\d\s*[–-]\s*(\d)", scale or "")
    return int(m.group(1)) if m else None


# ── announcements: checked on the web page ──
def fetch_all() -> dict:
    entries = [e for e in load() if e["kind"] == "announcement"]
    out, texts = {}, {}
    for e in entries:
        if e["url"] not in texts:
            try:
                r = fetch.get(e["url"])
                texts[e["url"]] = (r.status, attributions.page_text(r.text) if r.status == 200 else "")
            except Exception as ex:      # blocked by robots.txt, network error …
                texts[e["url"]] = (0, "")
                log.warning("%s: %s", e["url"], ex)
        status, text = texts[e["url"]]
        out[f"{e['url']}#{e['as_of']}#{e['system']}"] = {"status": status, "ok": normalise(e["quote"]) in text,
                                                         "checked": dt.date.today().isoformat()}
    CHECKS.parent.mkdir(parents=True, exist_ok=True)
    CHECKS.write_text(json.dumps(out, indent=1), encoding="utf-8")
    _checks.cache_clear()
    return {"entries": len(out), "confirmed": sum(v["ok"] for v in out.values())}


@lru_cache(maxsize=1)
def _checks_cached(mtime: float) -> dict:
    return json.loads(CHECKS.read_text(encoding="utf-8"))


def _checks() -> dict:
    return _checks_cached(CHECKS.stat().st_mtime) if CHECKS.exists() else {}


_checks.cache_clear = _checks_cached.cache_clear


# ── reports: checked against the library ──
@db.cached
def _located() -> dict:
    """{url: {doc_id, title, agency, year, text (normalised) offsets…}} for the reports the entries cite: where the quote is."""
    want = {e["url"]: e for e in load() if e["kind"] == "report"}
    out = {}
    if not want:
        return out
    with db.session() as con:
        topics.init()
        for url, e in want.items():
            row = con.execute("""SELECT d.id, d.title, d.year, d.lang, s.agency, s.country, d.local_path, i.pages
                                 FROM documents d JOIN sources s ON s.id=d.source_id LEFT JOIN doc_index i ON i.doc_id=d.id
                                 WHERE d.url=?""", (url,)).fetchone()
            if not row:
                out[url] = {"found": False}
                continue
            body = (con.execute("SELECT body FROM doc_text WHERE rowid=?", (row["id"],)).fetchone() or [""])[0] or ""
            norm_body, mapping = _normalised_with_map(body)
            pos = norm_body.find(" ".join(_fold(e["quote"]).split()))
            if pos < 0:
                out[url] = {"found": False, "doc_id": row["id"], "title": row["title"]}
                continue
            start = mapping[pos]
            pages = json.loads(row["pages"]) if row["pages"] else None
            page = topics.page_of(pages, start)
            out[url] = {"found": True, "doc_id": row["id"], "title": row["title"], "year": row["year"], "lang": row["lang"],
                        "agency": row["agency"], "page": page, "open": f"/doc/{row['id']}" + (f"#page={page}" if page else "")
                        if row["local_path"] else url}
    return out


_FOLD = str.maketrans({"‘": "'", "’": "'", "‚": "'", "′": "'", "`": "'", "´": "'", "“": '"', "”": '"', "„": '"', "″": '"',
                       "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-", "\u00a0": " "})


def _fold(text: str) -> str:
    """Same loose comparison as attributions.normalise, but one character stays one character (so offsets survive)."""
    return text.translate(_FOLD).lower()


def _normalised_with_map(text: str) -> tuple[str, list[int]]:
    """The loosely-normalised text (whitespace collapsed) and, for each of its characters, its offset in the original."""
    out, mapping = [], []
    for m in re.finditer(r"\s+|\S+", text):
        if m.group().isspace():
            if out:
                out.append(" "); mapping.append(m.start())
        else:
            out.append(_fold(m.group())); mapping.extend(range(m.start(), m.end()))
    return "".join(out).rstrip(), mapping


# ── for the portal ──
def when(as_of: str) -> float:
    """A statement's date as a fractional year: '2023-10-17' → 2023.79, '2026-06' → 2026.46, '2024' → 2024.5 (the middle)."""
    parts = [int(p) for p in str(as_of).split("-")]
    if len(parts) == 1:
        return parts[0] + 0.5
    day = parts[2] if len(parts) > 2 else 15
    return parts[0] + (parts[1] - 1 + (day - 0.5) / 31) / 12


def charts(countries: list[dict], today: dt.date | None = None) -> dict:
    """Small multiples: one chart per state and scale on a shared time axis. An announcement is a change, so the level
    holds until the next one (a step line); a level stated in a report is a reading at that time (a dot, never joined)."""
    today = today or dt.date.today()
    xs = [when(e["as_of"]) for c in countries for s in c["systems"] for e in s["entries"]]
    if not xs:
        return {"y0": None, "y1": None, "ticks": []}
    y0, y1 = int(min(xs)), today.year + 1
    pos = lambda x: round(100 * (x - y0) / (y1 - y0), 2)   # noqa: E731
    for c in countries:
        for s in c["systems"]:
            top = s["max"] or max((e["rank"] or 1) for e in s["entries"])
            ypos = lambda r: round(100 * (top - r) / (top - 1), 2) if top > 1 else 50   # noqa: E731
            s["steps"] = [{"rank": r, "y": ypos(r), "label": next((e["label"] for e in s["entries"] if e["rank"] == r), "")}
                          for r in range(top, 0, -1)]
            s["marks"] = [{"x": pos(when(e["as_of"])), "y": ypos(e["rank"]), "kind": e["kind"], "as_of": e["as_of"],
                           "label": e["label"], "rank": e["rank"],
                           "link": f"#tl-{c['country']}-{s['entries'].index(e)}-{c['systems'].index(s)}"}
                          for e in s["entries"] if e["rank"]]
            changes = sorted((when(e["as_of"]), e["rank"]) for e in s["entries"] if e["kind"] == "announcement" and e["rank"])
            path = []
            for i, (x, r) in enumerate(changes):
                end = changes[i + 1][0] if i + 1 < len(changes) else (today.year + today.timetuple().tm_yday / 366)
                path.append(f"{'M' if not path else 'L'}{pos(x)},{ypos(r)} L{pos(end)},{ypos(r)}")
            s["path"] = " ".join(path)
    return {"y0": y0, "y1": y1, "ticks": [{"year": y, "x": pos(y)} for y in range(y0, y1 + 1, 2 if y1 - y0 > 8 else 1)]}


def overview() -> dict:
    checks, located = _checks(), _located()
    by_country: dict[str, dict] = {}
    for e in load():
        if e["kind"] == "report":
            loc = located.get(e["url"], {"found": False})
            ev = {"confirmed": loc.get("found", False), "checked": "library", **{k: loc.get(k) for k in ("doc_id", "title", "page", "open")}}
        else:
            c = checks.get(f"{e['url']}#{e['as_of']}#{e['system']}", {})
            ev = {"confirmed": bool(c.get("ok")), "checked": c.get("checked"), "open": e["url"]}
        c = by_country.setdefault(e["country"], {"country": e["country"], "systems": {}})
        s = c["systems"].setdefault(e["system"], {"system": e["system"], "scale": e["scale"], "max": scale_max(e["scale"]),
                                                  "entries": []})
        s["entries"].append({**e, "as_of": str(e["as_of"]), "evidence": ev})
    for c in by_country.values():
        for s in c["systems"].values():
            s["entries"].sort(key=lambda x: x["as_of"], reverse=True)
            s["latest"] = s["entries"][0]
        c["systems"] = list(c["systems"].values())
    countries = sorted(by_country.values(), key=lambda c: c["country"])
    n = [x for c in countries for s in c["systems"] for x in s["entries"]]
    return {"countries": countries, "axis": charts(countries), "n": len(n), "confirmed": sum(x["evidence"]["confirmed"] for x in n),
            "checked": max((v["checked"] for v in checks.values()), default=None)}
