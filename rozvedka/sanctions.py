"""Sanctions and designations of the actors the reports name – from the official consolidated lists of the European
Union, the United Kingdom, the United Nations Security Council and the United States (OFAC SDN).

`python -m rozvedka fetch-sanctions` downloads the four lists (public XML files of the issuing bodies) into
data/sanctions/, reads each entry's names, type, date, programme and legal basis, and matches the names with the
actors by exact name (see `normalise`). The matches are kept in data/sanctions/matches.json with the list, the
entry's reference, the name that matched, the legal text and the retrieval date; `index-actors` renews them. The
portal itself makes no outside calls.

Honest matching: a match is a *name* match, not an identification. A person's name must have at least two words and
must be the actor's own name; a one-word name needs at least five letters ("Hamas", not "JIT"); a name that belongs to two actors is skipped; a person's nom de guerre ("Abu Obeida") counts only with a third word; a group's name is compared with groups and organisations only (not with people);
names the actor index ignores (ordinary words, weak abbreviations) are not used. Every match shows how it was made
so the reader can check it against the list entry.
"""
import datetime as dt
import json
import logging
import re
import unicodedata
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

from . import actors, db, fetch
from .config import DATA

log = logging.getLogger("rozvedka.sanctions")

DIR = DATA / "sanctions"
MATCHES = DIR / "matches.json"
LISTS = {
    "EU": {"name": "EU consolidated financial sanctions list", "issuer": "European Commission (FPI)",
           "file": "eu.xml", "page": "https://www.sanctionsmap.eu/",
           "url": "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw"},
    "UK": {"name": "UK Sanctions List", "issuer": "Foreign, Commonwealth & Development Office",
           "file": "uk.xml", "page": "https://www.gov.uk/government/publications/the-uk-sanctions-list",
           "url": "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml"},
    "UN": {"name": "UN Security Council Consolidated List", "issuer": "UN Security Council",
           "file": "un.xml", "page": "https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list",
           "url": "https://scsanctions.un.org/resources/xml/en/consolidated.xml"},
    "US": {"name": "OFAC Specially Designated Nationals (SDN) list", "issuer": "US Treasury, OFAC",
           "file": "ofac.xml", "page": "https://ofac.treasury.gov/specially-designated-nationals-and-blocked-persons-list-sdn-human-readable-lists",
           "url": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.XML"},
}
KUNYA = {"abu", "abou", "umm", "oum", "abd", "abdul", "sheikh", "mullah", "haji"}
MIN_SINGLE = 5          # a one-word name must have at least this many letters ("Hamas", not "JIT")
PERSON_KINDS = {"person"}
GROUP_KINDS = {"state", "cyber", "terror", "armed", "crime", "movement", "party", "org", "other"}


def normalise(name: str) -> str:
    """'Hizb Allah' → 'hizb allah': no accents, case or punctuation; words separated by one space."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    return " ".join(re.findall(r"\w+", s))


def _tag(e) -> str:
    return e.tag.rsplit("}", 1)[-1]


def _text(e, tag: str) -> str:
    for c in e:
        if _tag(c) == tag:
            return (c.text or "").strip()
    return ""


def _iso(s: str) -> str:
    """'29/06/2012' or '2012-06-29' → '2012-06-29' (else ''): the lists write dates differently."""
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})$", s or "")
    if m:
        return f"{m[3]}-{m[2]}-{m[1]}"
    return s[:10] if re.match(r"\d{4}-\d{2}-\d{2}", s or "") else ""


def _entries(path: Path, kind: str):
    """Yield the entries of one list file as dicts: ref, type (person/group/other), name, names, date, programme, legal."""
    for _, e in ET.iterparse(path, events=("end",)):
        t = _tag(e)
        if kind == "UN" and t in ("INDIVIDUAL", "ENTITY"):
            names = [" ".join(x for x in (_text(e, f) for f in ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME")) if x)]
            for a in e:
                if _tag(a) in ("INDIVIDUAL_ALIAS", "ENTITY_ALIAS") and _text(a, "ALIAS_NAME") and _text(a, "QUALITY") != "Low":
                    names.append(_text(a, "ALIAS_NAME"))
            yield {"ref": _text(e, "REFERENCE_NUMBER") or _text(e, "DATAID"), "type": "person" if t == "INDIVIDUAL" else "group",
                   "name": names[0], "names": names, "primary": 1, "date": _iso(_text(e, "LISTED_ON")),
                   "programme": _text(e, "UN_LIST_TYPE"), "legal": [], "url": None}
            e.clear()
        elif kind == "UK" and t == "Designation":
            names, aliases = [], []
            for n in e.iter():
                if _tag(n) == "Name" and any(_tag(c) == "Name6" for c in n):
                    (names if _text(n, "NameType").casefold().startswith("primary") else aliases).append(
                        " ".join(_text(n, f"Name{i}") for i in range(1, 7) if _text(n, f"Name{i}")))
            primary = len(names)
            names += aliases
            shape = _text(e, "IndividualEntityShip")
            yield {"ref": _text(e, "UniqueID"), "type": "person" if shape == "Individual" else "group" if shape == "Entity" else "other",
                   "name": names[0] if names else "", "names": names, "primary": primary or 1, "date": _iso(_text(e, "DateDesignated")),
                   "programme": _text(e, "RegimeName"), "legal": [], "url": None}
            e.clear()
        elif kind == "US" and t == "sdnEntry":
            def full(x):
                return " ".join(p for p in (_text(x, "firstName"), _text(x, "lastName")) if p)
            names = [full(e)]
            for a in e.iter():
                if _tag(a) == "aka" and full(a) and _text(a, "category") != "weak":
                    names.append(full(a))
            typ = _text(e, "sdnType")
            progs = [(p.text or "").strip() for p in e.iter() if _tag(p) == "program"]
            yield {"ref": _text(e, "uid"), "type": "person" if typ == "Individual" else "group" if typ == "Entity" else "other",
                   "name": names[0], "names": names, "primary": 1, "date": "", "programme": ", ".join(progs), "legal": [],
                   "url": f"https://sanctionssearch.ofac.treas.gov/Details.aspx?id={_text(e, 'uid')}"}
            e.clear()
        elif kind == "EU" and t == "sanctionEntity":
            names = [a.get("wholeName") for a in e if _tag(a) == "nameAlias" and a.get("wholeName")]
            code = next((s.get("code") for s in e if _tag(s) == "subjectType"), "")
            regs = [r for r in e if _tag(r) == "regulation"]
            regs.sort(key=lambda r: r.get("publicationDate", ""))
            legal = [{"text": f"{r.get('numberTitle')} ({r.get('programme')})", "url": (r.findtext("{*}publicationUrl") or "").strip() or None}
                     for r in regs]
            yield {"ref": e.get("euReferenceNumber") or e.get("logicalId"),
                   "type": "person" if code == "person" else "group" if code == "enterprise" else "other",
                   "name": names[0] if names else "", "names": names, "primary": 1,
                   "date": _iso(e.get("designationDate") or "") or (regs[0].get("entryIntoForceDate", "") if regs else ""),
                   "programme": ", ".join(dict.fromkeys(r.get("programme", "") for r in regs if r.get("programme"))),
                   "legal": legal, "url": None}
            e.clear()


def fetch_lists() -> dict:
    """Download the four lists (a polite single request each); returns {list: {retrieved, bytes} or error}."""
    DIR.mkdir(parents=True, exist_ok=True)
    meta = {}
    for key, spec in LISTS.items():
        try:
            r = fetch.download(spec["url"], DIR / spec["file"], max_bytes=120 * 2**20)
            meta[key] = {"retrieved": dt.date.today().isoformat(), "bytes": (DIR / spec["file"]).stat().st_size,
                         "status": getattr(r, "status", 200)}
        except Exception as e:  # noqa: BLE001 - one list failing must not lose the others
            log.warning("sanctions list %s: %s", key, e)
            meta[key] = {"error": str(e)[:200], "retrieved": None}
    (DIR / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return meta


def _actor_names(con) -> dict[str, list[tuple[str, str, str]]]:
    """normalised name → [(actor key, kind, name as written)] for the names the actor index uses."""
    out: dict[str, list] = {}
    for r in con.execute("""SELECT a.key, a.kind, a.label, n.name FROM actors a JOIN actor_names n ON n.actor_key=a.key
                            WHERE n.status='used' AND n.weak=0 AND a.kind != 'country'"""):
        out.setdefault(normalise(r["name"]), []).append((r["key"], r["kind"], r["name"]))
    return out


def match(meta: dict | None = None) -> dict:
    """Match every entry of the downloaded lists with the actors; writes matches.json."""
    if meta is None:
        meta = json.loads((DIR / "meta.json").read_text(encoding="utf-8")) if (DIR / "meta.json").exists() else {}
    with db.session() as con:
        actors.init()
        names = _actor_names(con)
    found: dict[str, list] = {}
    totals = {}
    for key, spec in LISTS.items():
        path = DIR / spec["file"]
        if not path.exists():
            continue
        n = 0
        for ent in _entries(path, key):
            n += 1
            kinds = PERSON_KINDS if ent["type"] == "person" else GROUP_KINDS if ent["type"] == "group" else set()
            if not kinds:
                continue
            hit: dict[str, tuple[str, str]] = {}
            for i, nm in enumerate(ent["names"]):
                norm = normalise(nm)
                if not norm or (ent["type"] == "person" and len(norm.split()) < 2):
                    continue
                alias = i >= ent["primary"]
                if alias and ent["type"] == "person" and len(norm.split()) < 3 and norm.split()[0] in KUNYA:
                    continue                                # "Abu Obeida" is a nom de guerre many men use
                if len(norm.split()) == 1 and len(norm) < MIN_SINGLE:      # "JIT", "SSA": too ambiguous
                    continue
                cands = [c for c in names.get(norm, ()) if c[1] in kinds]
                if len({c[0] for c in cands}) > 1:         # two actors share the name ("Ministry of State Security"): unclear which
                    continue
                for akey, kind, written in cands:
                    if kind in kinds:
                        hit.setdefault(akey, (nm, "alias" if alias else "name"))
            for akey, (nm, via) in hit.items():
                found.setdefault(akey, []).append({
                    "list": key, "ref": ent["ref"], "entry": ent["name"], "matched": nm, "via": via, "date": ent["date"],
                    "programme": ent["programme"], "legal": ent["legal"], "url": ent["url"] or LISTS[key]["page"],
                    "type": ent["type"]})
        totals[key] = n
    out = {"retrieved": {k: (meta.get(k) or {}).get("retrieved") for k in LISTS}, "entries": totals, "actors": found,
           "matched": sum(len(v) for v in found.values())}
    DIR.mkdir(parents=True, exist_ok=True)
    MATCHES.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    _load.cache_clear()
    return {"entries": totals, "actors_with_designations": len(found), "matches": out["matched"]}


@lru_cache(maxsize=1)
def _load(mtime: float = 0.0) -> dict:
    return json.loads(MATCHES.read_text(encoding="utf-8")) if MATCHES.exists() else {}


def data() -> dict:
    return _load(MATCHES.stat().st_mtime if MATCHES.exists() else 0.0)


def of_actor(key: str) -> list[dict]:
    """Designations of one actor, newest first (empty if the lists were not fetched)."""
    rows = list(data().get("actors", {}).get(key, []))
    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    return rows


def overview() -> dict:
    """What the lists say overall (for the sources note on the actor page and the Actors page)."""
    d = data()
    return {"lists": LISTS, "retrieved": d.get("retrieved", {}), "entries": d.get("entries", {}),
            "actors": sorted(d.get("actors", {})), "matched": d.get("matched", 0)}


def fetch_all() -> dict:
    meta = fetch_lists()
    return {"download": {k: v.get("error") or "ok" for k, v in meta.items()}, **match(meta)}


def table(list_: str = "", via: str = "", kind: str = "") -> dict:
    """All actors with a designation (filter by list, by how the name matched, by actor kind), most lists first."""
    d = data()
    with db.session() as con:
        actors.init()
        info = {r["key"]: dict(r) for r in con.execute("SELECT key, label, kind FROM actors")}
    rows = []
    for key, ms in d.get("actors", {}).items():
        ms = [m for m in ms if (not list_ or m["list"] == list_) and (not via or m["via"] == via)]
        a = info.get(key)
        if not ms or not a or (kind and a["kind"] != kind):
            continue
        rows.append({"key": key, "label": a["label"], "kind": a["kind"], "kind_name": actors.kind_name(a["kind"]),
                     "lists": sorted({m["list"] for m in ms}), "n": len(ms), "via": sorted({m["via"] for m in ms}),
                     "first": min((m["date"] for m in ms if m["date"]), default="")})
    rows.sort(key=lambda r: (-len(r["lists"]), -r["n"], r["label"]))
    kinds = sorted({info[k]["kind"] for k in d.get("actors", {}) if k in info})
    return {"rows": rows, "lists": LISTS, "retrieved": d.get("retrieved", {}), "entries": d.get("entries", {}),
            "list_": list_, "via": via, "kind": kind, "kinds_present": kinds, "total": len(d.get("actors", {})),
            "have_data": bool(d)}
