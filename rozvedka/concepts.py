"""Cross-language search: a search word that names a concept in one language also finds the concept's names in
the other languages of the library ("Drohne" → drone, dron, drón …).

The concepts are hand-picked English Wikipedia titles (sources/concepts.yaml); their names in each language are the
labels and aliases of the matching Wikidata item, fetched by `fetch-concepts` with the item's revision and the
retrieval date (data/gazetteer/concepts.json). A word is expanded only when it equals one of those names; the
expansion is shown with its Wikidata source and can be switched off (exact search)."""
import datetime as dt
import json
import logging
import re
from functools import lru_cache
from pathlib import Path

import yaml

from . import topics
from .config import DATA, ROOT

log = logging.getLogger("rozvedka.concepts")

CONCEPTS = ROOT / "sources" / "concepts.yaml"
STORE = DATA / "gazetteer" / "concepts.json"
MIN_NAME = 3          # shorter names (abbreviations such as "AI", "IS") are too ambiguous to search for
MAX_ADDED = 40        # names added for one word at most: every language's label first, then aliases
EXACT_UP_TO = 4       # names this short match as whole words ("dron", not "dronning" – the Danish queen)


def titles(path: Path | None = None) -> dict[str, str]:
    """English Wikipedia title → topic category key."""
    data = yaml.safe_load((path or CONCEPTS).read_text(encoding="utf-8")) or {}
    return {t: cat for cat, ts in data.items() for t in ts or []}


def fetch(path: Path | None = None, out: Path | None = None) -> dict:
    """Resolve the titles to Wikidata items and store their labels and aliases per language."""
    from . import actor_sources as src
    wanted = titles(path)
    qids = src.resolve_titles(list(wanted), what="concept")
    ents = src.entities(list(set(qids.values())), "labels|aliases|info", src.LANGS)
    today = dt.date.today().isoformat()
    concepts = []
    for title, qid in sorted(qids.items()):
        e = ents.get(qid)
        if not e:
            continue
        names: dict[str, list[str]] = {}
        for lang, lab in e.get("labels", {}).items():
            names.setdefault(lang, []).append(lab["value"])
        for lang, als in e.get("aliases", {}).items():
            names.setdefault(lang, []).extend(a["value"] for a in als)
        concepts.append({"title": title, "category": wanted[title], "qid": qid, "revision": e.get("lastrevid"),
                         "names": {lang: list(dict.fromkeys(v)) for lang, v in sorted(names.items())}})
    missing = sorted(set(wanted) - set(qids))
    doc = {"source": "Wikidata (labels and aliases)", "retrieved": today, "concepts": concepts, "missing": missing}
    out = out or STORE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    load.cache_clear()
    log.info("concepts: %d stored, %d titles without a Wikidata item", len(concepts), len(missing))
    return {"concepts": len(concepts), "missing": missing, "file": str(out)}


@lru_cache(maxsize=1)
def load(path: Path | None = None) -> dict:
    """{normalised name: [concept, …]} plus the store's metadata."""
    p = path or STORE
    if not p.exists():
        return {"by_name": {}, "retrieved": None}
    doc = json.loads(p.read_text(encoding="utf-8"))
    by_name: dict[str, list[dict]] = {}
    for c in doc["concepts"]:
        for lang, names in c["names"].items():
            for n in names:
                key = topics.normalize(n).strip()
                if len(key) >= MIN_NAME and c not in by_name.setdefault(key, []):
                    by_name[key].append(c)
    return {"by_name": by_name, "retrieved": doc.get("retrieved")}


def _alternatives(concept: dict, typed: str) -> list[tuple[str, str]]:
    """(language, name) of a concept, the typed form and duplicates left out, short names left out."""
    seen, out = {topics.normalize(typed).strip()}, []
    depth = max((len(v) for v in concept["names"].values()), default=0)
    for i in range(depth):                       # labels (index 0) of all languages, then the aliases
        for lang, names in concept["names"].items():
            if i < len(names):
                key = topics.normalize(names[i]).strip()
                if len(key) >= MIN_NAME and key not in seen and re.search(r"\w", key):
                    seen.add(key)
                    out.append((lang, names[i]))
    return out[:MAX_ADDED]


def _fts(name: str) -> str:
    words = re.findall(r"\w+", topics.normalize(name))
    if not words:
        return ""
    return f'"{" ".join(words)}"' + ("*" if len(words) == 1 and len(words[0]) > EXACT_UP_TO else "")


def _covered_once(alts: list[str]) -> list[str]:
    """Drop alternatives a shorter prefix already finds ("terrorismus" once "terror"* is there): same matches, and
    far fewer terms for the full-text index to look up and highlight."""
    prefixes = sorted({a[1:-2].lower() for a in alts if a.endswith('"*')}, key=len)
    keep = []
    for a in dict.fromkeys(alts):
        word = a.strip('"*').lower()
        if any(word != p and word.startswith(p) for p in prefixes) and " " not in word:
            continue
        keep.append(a)
    return keep


def expand(q: str) -> tuple[str, list[dict]]:
    """Search text → (FTS5 query, expansions). Every word or quoted phrase that names a concept becomes
    (word OR its other names); queries with an explicit OR are left as typed."""
    from . import trends
    if not q.strip() or " OR " in q:
        return trends.or_query(q) if q.strip() else "", []
    store = load()
    phrases = re.findall(r'"([^"]+)"', q)
    words = re.findall(r"\w+", re.sub(r'"[^"]+"', " ", q))
    # the whole query may itself be a multi-word name ("unmanned aerial vehicle")
    whole = topics.normalize(q.replace('"', "")).strip()
    if not phrases and len(words) > 1 and whole in store["by_name"]:
        phrases, words = [q.replace('"', "")], []
    parts, notes = [], []
    for typed, is_phrase in [(p, True) for p in phrases] + [(w, False) for w in words]:
        own = f'"{typed.replace(chr(34), "")}"' + ("" if is_phrase else "*")
        concepts = store["by_name"].get(topics.normalize(typed).strip(), [])
        if not concepts:
            parts.append(own)
            continue
        alts, added = [own], []
        for c in concepts:
            new = _alternatives(c, typed)
            alts += [_fts(n) for _, n in new if _fts(n)]
            added.append({"typed": typed, "title": c["title"], "qid": c["qid"], "revision": c["revision"],
                          "url": f"https://www.wikidata.org/wiki/{c['qid']}", "names": new})
        parts.append("(" + " OR ".join(_covered_once(alts)) + ")")
        notes += added
    for n in notes:
        n["retrieved"] = store["retrieved"]
    return " AND ".join(parts), notes
