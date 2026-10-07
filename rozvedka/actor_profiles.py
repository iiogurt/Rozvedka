"""Profiles of the actors named in the reports: a picture (a group's flag or logo, a person's photo), key facts and the
Wikipedia summary – mainly from the English Wikipedia, with facts from Wikidata and pictures from Wikimedia Commons.

`python -m rozvedka fetch-actor-profiles` (also part of `fetch-actors`) fetches them for every actor that at least one
report names, into data/gazetteer/actor_profiles.json, and stores each picture once as a small thumbnail in
data/gazetteer/actor_images/ – the portal itself makes no outside calls. Only freely licensed Commons files are used;
each keeps its author, licence and file page. Countries are left out: they have their flags already.
"""
import datetime as dt
import html
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

from . import db
from .actor_sources import UA, WD_API, WP_API, _chunks, _get
from .config import DATA

log = logging.getLogger(__name__)

STORE = DATA / "gazetteer" / "actor_profiles.json"
IMAGES = DATA / "gazetteer" / "actor_images"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
THUMB = 360                     # px wide; Commons renders SVG flags and logos to PNG at this size
MAX_VALUES = 6                  # values shown per fact (positions held, occupations …)
IMAGE_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}

# facts shown per kind of actor: (Wikidata property, label); founded/dissolved/country are in the gazetteer already
PERSON_FACTS = [("P569", "Born"), ("P19", "Place of birth"), ("P570", "Died"), ("P27", "Citizenship"),
                ("P106", "Occupation"), ("P39", "Positions held"), ("P102", "Party"), ("P108", "Employer"),
                ("P463", "Member of")]
GROUP_FACTS = [("P112", "Founded by"), ("P488", "Chair / leader"), ("P1037", "Director"), ("P1142", "Ideology"),
               ("P159", "Headquarters"), ("P2124", "Members"), ("P749", "Parent organisation"),
               ("P127", "Owned by"), ("P856", "Official website")]
# where a picture comes from, in order of preference: a group is best recognised by its flag or emblem, a person by a photo
GROUP_PICTURES = [("P41", "flag"), ("P154", "logo"), ("P94", "coat of arms"), ("wp", "Wikipedia article image"),
                  ("P18", "image")]
PERSON_PICTURES = [("wp", "Wikipedia article image"), ("P18", "image")]


def _claims(ent: dict, prop: str) -> list[dict]:
    """Statements of a property, best rank only (preferred if any, else normal; never deprecated)."""
    cs = [c for c in ent.get("claims", {}).get(prop, []) if c.get("rank") != "deprecated"
          and c.get("mainsnak", {}).get("snaktype") == "value"]
    pref = [c for c in cs if c.get("rank") == "preferred"]
    return pref or cs


def _time(v: dict) -> str:
    """Wikidata time value → '1952-10-07', '1952-10' or '1952' by its precision."""
    t, prec = v["time"].lstrip("+"), v.get("precision", 11)
    if t.startswith("-"):
        return t[1:5].lstrip("0") + " BC"
    return t[:10] if prec >= 11 else t[:7] if prec == 10 else t[:4]


def _year_range(c: dict) -> str:
    q = c.get("qualifiers", {})
    s = q.get("P580", [{}])[0].get("datavalue", {}).get("value")
    e = q.get("P582", [{}])[0].get("datavalue", {}).get("value")
    if not s and not e:
        return ""
    return f"{_time(s)[:4] if s else '?'}–{_time(e)[:4] if e else ''}"


def _commons_file(ent: dict, prop: str) -> str | None:
    cs = _claims(ent, prop)
    return cs[0]["mainsnak"]["datavalue"]["value"] if cs else None


def wikipedia_pages(titles: list[str]) -> dict[str, dict]:
    """Main (infobox) image – free licence only – lead text and revision of each English Wikipedia article."""
    out = {}
    for chunk in _chunks(titles, 20):            # extracts come at most 20 per request
        d = _get(WP_API, {"action": "query", "prop": "pageimages|extracts|revisions", "piprop": "name",
                          "pilicense": "free", "exintro": 1, "explaintext": 1, "exlimit": 20, "rvprop": "ids|timestamp",
                          "titles": "|".join(chunk), "redirects": 1, "format": "json", "formatversion": 2})["query"]
        back = {}
        for n in d.get("normalized", []) + d.get("redirects", []):
            back[n["to"]] = back.get(n["from"], n["from"])
        for p in d["pages"]:
            if p.get("missing"):
                continue
            rev = (p.get("revisions") or [{}])[0]
            text = re.sub(r"\n{2,}", "\n", (p.get("extract") or "").strip())
            out[back.get(p["title"], p["title"])] = {
                "title": p["title"], "image": p.get("pageimage"),
                "extract": text[:1500] + ("…" if len(text) > 1500 else ""),
                "revision": rev.get("revid"), "revision_time": rev.get("timestamp"),
                "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(p["title"].replace(" ", "_")),
                "revision_url": f"https://en.wikipedia.org/w/index.php?oldid={rev.get('revid')}"}
        log.info("wikipedia pages %d/%d", len(out), len(titles))
    return out


def wikidata(qids: list[str]) -> dict[str, dict]:
    out = {}
    for chunk in _chunks(qids, 50):
        d = _get(WD_API, {"action": "wbgetentities", "ids": "|".join(chunk), "props": "claims|info",
                          "format": "json"})
        out.update(d.get("entities", {}))
        log.info("wikidata %d/%d", len(out), len(qids))
    return out


def labels(qids: set[str]) -> dict[str, str]:
    out = {}
    for chunk in _chunks(sorted(qids), 50):
        d = _get(WD_API, {"action": "wbgetentities", "ids": "|".join(chunk), "props": "labels",
                          "languages": "en|mul", "languagefallback": 1, "format": "json"})
        for q, e in d.get("entities", {}).items():
            lab = e.get("labels", {})
            out[q] = (lab.get("en") or lab.get("mul") or {}).get("value", q)
    return out


def _plain(s: str | None) -> str:
    """Commons metadata is HTML ('<a href=…>Name</a>'): keep the text."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def commons_info(files: list[str]) -> dict[str, dict]:
    """Thumbnail URL, author and licence of Commons files; files that are not on Commons are left out."""
    out = {}
    for chunk in _chunks(files, 40):
        d = _get(COMMONS_API, {"action": "query", "prop": "imageinfo", "iiprop": "url|extmetadata|mime",
                               "iiurlwidth": THUMB, "titles": "|".join("File:" + f for f in chunk), "redirects": 1,
                               "format": "json", "formatversion": 2})["query"]
        back = {}
        for n in d.get("normalized", []) + d.get("redirects", []):
            back[n["to"]] = back.get(n["from"], n["from"])
        for p in d.get("pages", []):
            ii = (p.get("imageinfo") or [None])[0]
            if p.get("missing") or not ii or not ii.get("thumburl"):
                continue
            m = ii.get("extmetadata", {})
            name = back.get(p["title"], p["title"]).removeprefix("File:")
            lic = _plain(m.get("LicenseShortName", {}).get("value"))
            if m.get("NonFree", {}).get("value") in ("true", True):
                continue                         # free licences only
            out[name] = {"file": name, "page": ii.get("descriptionurl"), "thumb": ii["thumburl"],
                         "author": _plain(m.get("Artist", {}).get("value"))[:200] or None,
                         "credit": _plain(m.get("Credit", {}).get("value"))[:200] or None,
                         "licence": lic or None, "licence_url": m.get("LicenseUrl", {}).get("value")}
        log.info("commons %d/%d", len(out), len(files))
    return out


def _download(url: str, dest_stem: Path) -> str | None:
    url = url.split("?", 1)[0]                   # Commons adds tracking parameters to thumbnail URLs
    ext = url.rsplit(".", 1)[-1].lower()
    if ext not in IMAGE_TYPES:
        return None
    dest = dest_stem.with_suffix("." + ext)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                dest.write_bytes(r.read())
            time.sleep(1.0)
            return dest.name
        except Exception as e:  # noqa: BLE001 - a missing picture is not worth failing the whole fetch
            log.warning("image %s: %s", url[:90], e)
            time.sleep(5 * (attempt + 1))
    return None


def _facts(ent: dict, spec: list, names: dict[str, str]) -> list[dict]:
    facts = []
    for prop, label in spec:
        vals = []
        for c in _claims(ent, prop):
            v = c["mainsnak"]["datavalue"]
            t, val = v["type"], v["value"]
            if t == "wikibase-entityid":
                q = val["id"]
                vals.append({"text": names.get(q, q), "qid": q, "when": _year_range(c)})
            elif t == "time":
                vals.append({"text": _time(val)})
            elif t == "quantity":
                when = c.get("qualifiers", {}).get("P585", [{}])[0].get("datavalue", {}).get("value")
                vals.append({"text": f"{float(val['amount']):,.0f}", "when": _time(when) if when else ""})
            elif t == "string" and prop == "P856":
                vals.append({"text": re.sub(r"^https?://(www\.)?", "", val).rstrip("/"), "url": val})
        if vals:
            facts.append({"prop": prop, "label": label, "values": vals[:MAX_VALUES], "more": max(0, len(vals) - MAX_VALUES)})
    return facts


def targets() -> list[dict]:
    """Actors named by at least one report (countries left out), from the gazetteer as loaded into the database."""
    from . import actors
    gaz = {a["key"]: a for a in actors.load_gazetteer()["actors"]}
    with db.session() as con:
        actors.init()
        keys = [r[0] for r in con.execute("""SELECT DISTINCT da.actor_key FROM doc_actors da JOIN actors a
                                             ON a.key=da.actor_key WHERE a.kind != 'country'""")]
    return [gaz[k] for k in keys if k in gaz]


def fetch(refresh: bool = False) -> str:
    """Fetch profiles for every actor the reports name; pictures already stored are kept unless `refresh`."""
    today = dt.date.today().isoformat()
    todo = targets()
    old = load()["profiles"] if STORE.exists() and not refresh else {}
    IMAGES.mkdir(parents=True, exist_ok=True)
    pages = wikipedia_pages(sorted({a["wikipedia"]["title"] for a in todo if a.get("wikipedia")}))
    ents = wikidata(sorted({a["qid"] for a in todo if a.get("qid")}))
    refs = set()
    for a in todo:
        e = ents.get(a.get("qid") or "", {})
        for prop, _ in PERSON_FACTS if a["kind"] == "person" else GROUP_FACTS:
            for c in _claims(e, prop):
                v = c["mainsnak"]["datavalue"]
                if v["type"] == "wikibase-entityid":
                    refs.add(v["value"]["id"])
    names = labels(refs)
    # the picture of each actor: the first source in the kind's order of preference that Commons has, freely licensed
    choice: dict[str, list[tuple[str, str]]] = {}
    for a in todo:
        e, page = ents.get(a.get("qid") or "", {}), pages.get((a.get("wikipedia") or {}).get("title", ""), {})
        options = []
        for src, what in PERSON_PICTURES if a["kind"] == "person" else GROUP_PICTURES:
            f = page.get("image") if src == "wp" else _commons_file(e, src)
            if f:
                options.append((f.replace("_", " "), what if src == "wp" else f"{what} (Wikidata {src})"))
        choice[a["key"]] = options
    info = commons_info(sorted({f for opts in choice.values() for f, _ in opts}))
    profiles, n_img = {}, 0
    for a in todo:
        e, page = ents.get(a.get("qid") or "", {}), pages.get((a.get("wikipedia") or {}).get("title", ""), {})
        picture = None
        for f, what in choice[a["key"]]:
            if f in info:
                picture = {**info[f], "what": what}
                break
        if picture:
            prev = (old.get(a["key"]) or {}).get("picture") or {}
            if prev.get("file") == picture["file"] and prev.get("local") and (IMAGES / prev["local"]).exists():
                picture["local"] = prev["local"]
            else:
                for stale in IMAGES.glob(f"{a['key']}.*"):
                    stale.unlink()
                picture["local"] = _download(picture["thumb"], IMAGES / a["key"])
            if not picture["local"]:
                picture = None
            else:
                n_img += 1
        profiles[a["key"]] = {
            "picture": picture,
            "facts": _facts(e, PERSON_FACTS if a["kind"] == "person" else GROUP_FACTS, names),
            "wikidata_revision": e.get("lastrevid"),
            "wikipedia": page and {k: page[k] for k in ("title", "extract", "revision", "revision_time", "url",
                                                        "revision_url")},
        }
    STORE.write_text(json.dumps({"retrieved": today, "profiles": profiles,
                                 "sources": {"wikipedia": WP_API, "wikidata": WD_API, "commons": COMMONS_API}},
                                ensure_ascii=False))
    load.cache_clear()
    return (f"actor profiles: {len(profiles)} actors, {n_img} pictures, "
            f"{sum(1 for p in profiles.values() if p['facts'])} with facts → {STORE}")


@lru_cache(maxsize=1)
def load() -> dict:
    try:
        return json.loads(STORE.read_text())
    except (OSError, ValueError):
        return {"retrieved": None, "profiles": {}}


def profile(key: str) -> dict | None:
    d = load()
    p = d["profiles"].get(key)
    return p and {**p, "retrieved": d["retrieved"]}


def image_path(key: str) -> Path | None:
    p = (load()["profiles"].get(key) or {}).get("picture")
    if not p or not p.get("local"):
        return None
    path = (IMAGES / p["local"]).resolve()
    return path if path.is_relative_to(IMAGES.resolve()) and path.exists() else None
