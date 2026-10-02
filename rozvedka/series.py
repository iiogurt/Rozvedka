"""Report series: recurring publications of a source (the BIS annual report in Czech and English, every year).

A series is recognised by the title with its year taken out ("Výroční zpráva BIS 2023" → "vyrocni zprava bis"),
per source and language; languages whose editions cover largely the same years are one series. The library
proposes series; the owner confirms or rejects them in the portal, which writes `sources/series.yaml` (the
source of truth, committed, hand-editable). For each confirmed series the portal shows, per year and language,
whether the edition is in the library, listed but not downloaded, missing, expected or confirmed as not published.
"""
import datetime as dt
import hashlib
import re
from collections import Counter
from pathlib import Path

import yaml

from . import db, topics
from .config import ROOT

SERIES_FILE = ROOT / "sources" / "series.yaml"
MIN_YEARS = 3          # a title recurring in at least this many years is proposed as a series
MERGE_OVERLAP = 0.5    # languages are one series when their years overlap at least this much (Jaccard)
LISTED = "d.hidden=0 AND d.status NOT IN ('missing','duplicate','skipped')"

_YEAR = re.compile(r"(?<!\d)(19|20)\d{2}(\s*[-/–]\s*((19|20)?\d{2}))?(?!\d)")
_NOISE = set("""pdf kb mb gb en eng english cs cz de fr es it nl pl version final web online print edition ed vol
volume no nr issue part teil the of for and und der die das des a an la le les el los del du di da za rok roku year
jahr annee ano anno""".split())


def stem(title: str) -> str:
    """Title without years, numbers, file-size notes and filler words – the same for every edition of a series."""
    t = topics.normalize(_YEAR.sub(" ", title or ""))
    words = [w for w in re.findall(r"[a-z]+", t) if w not in _NOISE and len(w) > 1]
    return " ".join(words)


def _key(source_key: str, stems: dict[str, list[str]]) -> str:
    raw = source_key + "|" + "|".join(f"{lg}:{s}" for lg in sorted(stems) for s in sorted(stems[lg]))
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


# ── sources/series.yaml ──
HEADER = """# Report series – recurring publications per source, confirmed in the portal (Sources → Coverage).
#
# Written by the portal when a proposed series is confirmed, renamed or rejected, or when an edition is marked as
# not published; it may also be edited by hand. `titles` are the title stems (title without year, lowercase,
# without accents and filler words) that identify the series' editions per language; `urls` adds editions whose
# title differs. `absent` lists editions confirmed as not published ("2003 en": reason).
"""


def load(path: Path | None = None) -> dict:
    path = path or SERIES_FILE
    if not path.exists():
        return {"series": [], "rejected": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {"series": data.get("series") or [], "rejected": data.get("rejected") or []}


def save(data: dict, path: Path | None = None) -> None:
    path = path or SERIES_FILE
    body = {"series": sorted(data["series"], key=lambda s: (s["source"], s["name"])),
            "rejected": sorted(set(data.get("rejected") or []))}
    path.write_text(HEADER + yaml.safe_dump(body, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")


# ── detection ──
def _documents(con, source_id: int | None = None) -> list[dict]:
    sql = f"""SELECT d.id, d.source_id, d.url, d.title, d.lang, d.year, d.status, d.local_path, s.key source_key
              FROM documents d JOIN sources s ON s.id=d.source_id WHERE {LISTED} AND s.active=1 AND d.year IS NOT NULL"""
    args = []
    if source_id:
        sql += " AND d.source_id=?"; args.append(source_id)
    return [dict(r) for r in con.execute(sql, args)]


def propose(con, source_id: int | None = None) -> list[dict]:
    """Candidate series from the titles in the library, minus confirmed and rejected ones."""
    data = load()
    taken = {(s["source"], lg, t) for s in data["series"] for lg, ts in s["titles"].items() for t in ts}
    rejected = set(data["rejected"])
    groups: dict[tuple, dict] = {}
    for d in _documents(con, source_id):
        st = stem(d["title"])
        if len(st.split()) < 2 or not d["lang"]:
            continue
        g = groups.setdefault((d["source_key"], d["lang"], st), {"years": Counter(), "titles": Counter(), "source_id": d["source_id"]})
        g["years"][d["year"]] += 1
        g["titles"][d["title"]] += 1
    cands = [(k, g) for k, g in groups.items() if len(g["years"]) >= MIN_YEARS and k not in taken]
    # merge languages of one source whose years overlap
    merged: list[dict] = []
    for (src, lang, st), g in sorted(cands, key=lambda x: -len(x[1]["years"])):
        years = set(g["years"])
        home = next((m for m in merged if m["source"] == src and lang not in m["titles"]
                     and len(years & m["years"]) / len(years | m["years"]) >= MERGE_OVERLAP), None)
        if home is None:
            home = {"source": src, "source_id": g["source_id"], "titles": {}, "years": set(), "examples": {}, "per_year": 1}
            merged.append(home)
        home["titles"].setdefault(lang, []).append(st)
        home["years"] |= years
        home["examples"][lang] = g["titles"].most_common(1)[0][0]
        home["per_year"] = max(home["per_year"], sorted(g["years"].values())[len(g["years"]) // 2])
    out = []
    for m in merged:
        key = _key(m["source"], m["titles"])
        if key in rejected:
            continue
        name = _clean_name(m["examples"].get("en") or next(iter(m["examples"].values())))
        out.append({"key": key, "source": m["source"], "source_id": m["source_id"], "name": name,
                    "languages": sorted(m["titles"]), "titles": m["titles"], "per_year": m["per_year"],
                    "since": min(m["years"]), "examples": m["examples"], "years": sorted(m["years"])})
    return sorted(out, key=lambda s: (-len(s["years"]), s["source"]))


_LINK_TEXT = re.compile(r"(download hier het volledige verslag|ouvre une nouvelle fen[eê]tre|opens? in a new (window|tab)|"
                        r"download( here)?( the)?( full)?( report)?|descargue el contenido del|"
                        r"t[eé]l[eé]charger|herunterladen|st[aá]hnout|pobierz)", re.I)
_TRAILING = set("for of za w roku in del de la des der the vigencia au for year rok roku".split())


def _clean_name(title: str) -> str:
    """A readable series name from one edition's title: years, sizes, link texts and dangling words removed."""
    t = _LINK_TEXT.sub(" ", _YEAR.sub(" ", title))
    t = re.sub(r"\bpdf\b|\d+([.,]\d+)?\s*[kKmM][bB]|\b\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*", " ", t, flags=re.I)
    t = re.sub(r"[\u200b\u200e\u200f]", "", t)
    t = re.sub(r"\(\s*[,;:]?\s*\)|\[\s*\]|\s/\d+\b|\b\d{1,2}\b", " ", t)
    words = t.split()
    while words and (words[-1].lower().strip(".,:;-–") in _TRAILING or not words[-1].strip(".,:;-–()")):
        words.pop()
    name = " ".join(words).strip(" -–:,.;")
    if name.count("(") > name.count(")"):
        name += ")"
    return name.strip() or title


# ── coverage ──
def coverage(con, s: dict, today: dt.date | None = None) -> dict:
    """Editions of a confirmed (or proposed) series per year and language, with their state."""
    today = today or dt.date.today()
    src = con.execute("SELECT id, key, country, agency FROM sources WHERE key=?", (s["source"],)).fetchone()
    if not src:
        return {"series": s, "rows": [], "years": []}
    docs = _documents(con, src["id"])
    urls = set(s.get("urls") or [])
    per_year = s.get("per_year", 1)
    have: dict[tuple, list] = {}
    for d in docs:
        if d["url"] in urls or (d["lang"] in s["titles"] and stem(d["title"]) in s["titles"][d["lang"]]):
            have.setdefault((d["year"], d["lang"]), []).append(d)
    present = [y for (y, _) in have]
    first = s.get("since") or (min(present) if present else today.year)
    last = max(present) if present else first
    years = list(range(first, max(last, today.year - 1) + 1))
    absent = {str(k): v for k, v in (s.get("absent") or {}).items()}
    rows = []
    for lang in s["languages"]:
        cells = []
        lang_years = [y for (y, lg) in have if lg == lang]
        lang_last = max(lang_years) if lang_years else None
        for y in years:
            docs_here = have.get((y, lang), [])
            downloaded = [d for d in docs_here if d["local_path"]]
            if f"{y} {lang}" in absent:
                state = "absent"
            elif downloaded and len(downloaded) >= per_year:
                state = "have"
            elif docs_here:
                state = "listed"              # known, but not (all) downloaded – blocked or failed
            elif lang_last is None or y > lang_last:
                state = "expected"            # after the latest edition: may not be published yet
            else:
                state = "missing"
            cells.append({"year": y, "state": state, "docs": [d["id"] for d in docs_here],
                          "n": len(docs_here), "note": absent.get(f"{y} {lang}")})
        rows.append({"lang": lang, "cells": cells})
    counts = Counter(c["state"] for r in rows for c in r["cells"])
    return {"series": s, "source": dict(src), "years": years, "rows": rows, "counts": dict(counts),
            "complete": counts.get("missing", 0) == 0 and counts.get("listed", 0) == 0}


def all_coverage() -> list[dict]:
    with db.session() as con:
        return [coverage(con, s) for s in load()["series"]]


def by_source() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for c in all_coverage():
        out.setdefault(c["series"]["source"], []).append(c)
    return out


# ── changes from the portal ──
def confirm(proposal: dict, name: str | None = None, per_year: int | None = None, into: str | None = None) -> dict:
    """Confirm a proposal as a new series, or add its titles to an existing series of the same source (`into`)."""
    data = load()
    target = next((s for s in data["series"] if s["source"] == proposal["source"] and s["name"] == into), None) if into else None
    if target:
        for lang, stems in proposal["titles"].items():
            have = target["titles"].setdefault(lang, [])
            have += [x for x in stems if x not in have]
        target["languages"] = sorted(target["titles"])
        target["since"] = min(target.get("since") or proposal["since"], proposal["since"])
        s = target
    else:
        s = {"source": proposal["source"], "name": (name or proposal["name"]).strip(),
             "per_year": per_year or proposal["per_year"], "languages": proposal["languages"],
             "titles": proposal["titles"], "since": proposal["since"]}
        data["series"].append(s)
    save(data)
    return s


def reject(key: str) -> None:
    data = load()
    data["rejected"].append(key)
    save(data)


def find(source: str, name: str) -> dict | None:
    return next((s for s in load()["series"] if s["source"] == source and s["name"] == name), None)


def mark_absent(source: str, name: str, year: int, lang: str, reason: str) -> None:
    data = load()
    for s in data["series"]:
        if s["source"] == source and s["name"] == name:
            s.setdefault("absent", {})[f"{year} {lang}"] = reason.strip() or "not published"
    save(data)


def unmark_absent(source: str, name: str, year: int, lang: str) -> None:
    data = load()
    for s in data["series"]:
        if s["source"] == source and s["name"] == name:
            (s.get("absent") or {}).pop(f"{year} {lang}", None)
    save(data)


def remove(source: str, name: str) -> None:
    data = load()
    data["series"] = [s for s in data["series"] if not (s["source"] == source and s["name"] == name)]
    save(data)
