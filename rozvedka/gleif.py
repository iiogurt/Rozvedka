"""GLEIF: who owns which company, for the companies on the sanctions lists (CC0, https://www.gleif.org).

The Global Legal Entity Identifier Foundation publishes every legal entity identifier (LEI) – 3.5 million companies, funds
and branches with their legal name, registered address, number in their national register and status – and which entity
consolidates which ("Level 2": direct and ultimate parents, branches), as files updated three times a day (the "golden
copy", CC0). They are downloaded once per run (~500 MB), read as a stream from the zip and kept only for the companies the
network already has:

- matched to a list entry (rozvedka/sanctions.py) by
  1. the LEI the entry states (OFAC gives one for some 185 entries) – certain;
  2. the entry's registration or tax number, in the same country, when either the record shares a distinctive name word
     with the entry (Cyrillic read in Latin letters) or the number is a Russian or Belarusian main state registration
     number (OGRN, 13 or 15 digits, unique in its country) – registration numbers repeat across registers otherwise;
  3. the entry's name, written the same after normalising (sanctions.normalise), in the same country, when only one
     record carries it and the name is distinctive (two words beyond the legal form, or one of 8 letters or more:
     "Orion LLC" is not, there are many).
  Entries without a country are not matched by name. Measured on hand-read samples (see ROADMAP G9).
- one step out: the direct and ultimate parents, the branches and the entities they consolidate (layer "gleif",
  rozvedka/ties.py), each with its relationship record: type, status, period and how it was validated.

    python -m rozvedka fetch-gleif        # download, match, keep (~15 minutes on a Raspberry Pi), then build-graph
"""
import csv
import datetime as dt
import io
import json
import logging
import re
import zipfile
from functools import lru_cache

from . import fetch, identity, sanctions
from .config import DATA

log = logging.getLogger("rozvedka.gleif")
DIR = DATA / "gleif"
FILE = DIR / "gleif.json"
LATEST = "https://goldencopy.gleif.org/api/v2/golden-copies/publishes/latest"
RECORD = "https://search.gleif.org/#/record/{}"
LICENCE = "CC0 1.0"
RELATIONS = {     # GLEIF relationship type → (start node → end node, end node → start node)
    "IS_DIRECTLY_CONSOLIDATED_BY": ("directly owned by", "direct parent of"),
    "IS_ULTIMATELY_CONSOLIDATED_BY": ("ultimately owned by", "ultimate parent of"),
    "IS_INTERNATIONAL_BRANCH_OF": ("branch of", "has the branch"),
}
LEGAL_FORMS = {"limited", "ltd", "llc", "inc", "co", "company", "corporation", "corp", "plc", "ag", "gmbh", "sa", "sarl", "bv",
               "nv", "srl", "spa", "fze", "fzco", "fzc", "dmcc", "jsc", "pjsc", "ojsc", "cjsc", "oao", "zao", "ooo", "pao", "ao",
               "joint", "stock", "public", "closed", "open", "liability", "society", "the", "of", "and", "obshchestvo", "s",
               "ogranichennoi", "ogranichennoy", "otvetstvennostyu", "aktsionernoe", "publichnoe", "akcionernoe", "tov",
               "llp", "lp", "private", "pte", "pvt", "holding", "holdings", "group", "international", "trading", "general",
               "obshchestvom", "obshestvo", "unitary", "enterprise", "federal", "state", "as", "ab", "oy", "kft", "doo", "sas",
               "aktsionernoye", "aktsionernogo", "tovarystvo", "pp", "chp", "uk", "ltda"}
OGRN = re.compile(r"\d{13}|\d{15}")
CYR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюяіїєў",
               ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f",
                "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya", "i", "i", "ye", "u"]))
COLS = {"lei": "LEI", "name": "Entity.LegalName", "city": "Entity.LegalAddress.City", "country": "Entity.LegalAddress.Country",
        "hq": "Entity.HeadquartersAddress.Country", "reg": "Entity.RegistrationAuthority.RegistrationAuthorityEntityID",
        "jurisdiction": "Entity.LegalJurisdiction", "form": "Entity.LegalForm.EntityLegalFormCode",
        "status": "Entity.EntityStatus", "registration": "Registration.RegistrationStatus",
        "initial": "Registration.InitialRegistrationDate", "updated": "Registration.LastUpdateDate"}
OTHER = ([f"Entity.OtherEntityNames.OtherEntityName.{i}" for i in range(1, 6)]
         + [f"Entity.TransliteratedOtherEntityNames.TransliteratedOtherEntityName.{i}" for i in range(1, 6)])


def latin(s: str) -> str:
    return "".join(CYR.get(c, c) for c in (s or "").lower())


def words(name: str) -> set[str]:
    """Distinctive words of a company name: Cyrillic read in Latin letters, legal forms and short words left out."""
    return {w for w in sanctions.normalise(latin(name)).split() if len(w) >= 4 and w not in LEGAL_FORMS}


def distinctive(name: str) -> bool:
    w = words(name)
    return len(w) >= 2 or any(len(x) >= 8 for x in w)


@lru_cache(maxsize=1)
def _country_names() -> dict[str, str]:
    """Country names as the sanctions lists write them → ISO 3166 alpha-2 (the map's outlines, the World Bank's names, and
    the lists' own spellings)."""
    from . import ratings
    from .config import ROOT
    out: dict[str, str] = {}
    geo = json.loads((ROOT / "rozvedka" / "static" / "geo" / "countries.geojson").read_text(encoding="utf-8"))
    for f in geo["features"]:
        out[f["properties"]["name"].casefold()] = f["properties"]["iso"]
    s = ratings.load()
    i32 = {v: k for k, v in (s.get("iso2to3") or {}).items()}
    for a3, n in (s.get("names") or {}).items():
        if a3 in i32:
            out.setdefault(n.casefold(), i32[a3])
    out.update({"russia": "RU", "iran": "IR", "syria": "SY", "korea, north": "KP", "korea, south": "KR", "burma": "MM",
                "venezuela": "VE", "turkey": "TR", "türkiye": "TR", "congo, democratic republic of the": "CD", "hong kong": "HK",
                "macau": "MO", "taiwan": "TW", "united states": "US", "united kingdom": "GB", "czech republic": "CZ", "laos": "LA",
                "vietnam": "VN", "egypt": "EG", "yemen": "YE", "kyrgyzstan": "KG", "slovakia": "SK", "west bank": "PS",
                "gaza": "PS", "british virgin islands": "VG", "virgin islands, british": "VG", "cayman islands": "KY",
                "isle of man": "IM", "jersey": "JE", "guernsey": "GG", "gibraltar": "GI", "marshall islands": "MH",
                "seychelles": "SC", "liechtenstein": "LI", "monaco": "MC", "malta": "MT", "singapore": "SG", "bahrain": "BH",
                "mauritius": "MU", "luxembourg": "LU", "cyprus": "CY", "moldova": "MD", "north macedonia": "MK",
                "bosnia and herzegovina": "BA", "brunei": "BN", "curacao": "CW", "curaçao": "CW", "andorra": "AD",
                "san marino": "SM", "belize": "BZ", "panama": "PA", "bahamas, the": "BS", "gambia, the": "GM",
                "russian federation": "RU", "uae": "AE", "the netherlands": "NL", "republic of korea": "KR"})
    return out


def country(name: str) -> str:
    c = (name or "").strip()
    return c.upper() if re.fullmatch(r"[A-Za-z]{2}", c) else _country_names().get(c.casefold(), "")


def list_companies() -> dict[str, dict]:
    """The companies, organisations, vessels' owners … of the sanctions lists: names, numbers, countries."""
    out = {}
    for lst, spec in sanctions.LISTS.items():
        path = sanctions.DIR / spec["file"]
        if not path.exists():
            continue
        for e in sanctions._entries(path, lst):
            if e["type"] == "person":
                continue
            d = e["details"]
            cs = {country(a["country"]) for a in d["addresses"] if a} | {country(c) for _k, _v, c in d["ids"] if c}
            out[f"{lst}:{e['ref']}"] = {"names": e["names"], "countries": sorted(cs - {""}),
                                        "leis": sorted({v for k, v, _c in d["ids"] if k == "lei"}),
                                        "numbers": sorted({v for k, v, _c in d["ids"] if k in ("registration", "tax")})}
    return out


def _rows(path):
    z = zipfile.ZipFile(path)
    with z.open(z.namelist()[0]) as f:
        r = csv.reader(io.TextIOWrapper(f, encoding="utf-8", newline=""))
        head = next(r)
        yield {c: i for i, c in enumerate(head)}
        yield from r


def _record(row, ix) -> dict:
    rec = {k: row[ix[c]] for k, c in COLS.items()}
    rec["other"] = [row[ix[c]] for c in OTHER if row[ix[c]]]
    return rec


def match(companies: dict[str, dict], records: dict[str, dict]) -> dict[str, dict]:
    """List entry → {"leis": [...], "how": "lei" | "registration" | "name"} by the rules above."""
    by_lei = {lei: k for k, c in companies.items() for lei in c["leis"]}
    by_num: dict[str, set] = {}
    by_name: dict[str, set] = {}
    for k, c in companies.items():
        for n in c["numbers"]:
            by_num.setdefault(n, set()).add(k)
        for nm in c["names"]:
            by_name.setdefault(sanctions.normalise(nm), set()).add(k)
    found: dict[str, dict[str, set]] = {}
    for lei, rec in records.items():
        names = [rec["name"], *rec["other"]]
        rw = set().union(*(words(n) for n in names))
        if lei in by_lei:
            found.setdefault(by_lei[lei], {}).setdefault("lei", set()).add(lei)
        num = identity.number(rec["reg"])
        for k in by_num.get(num, ()) if len(num) >= 6 else ():
            c = companies[k]
            if rec["country"] not in c["countries"]:
                continue
            if (rec["country"] in ("RU", "BY") and OGRN.fullmatch(num)) or any(words(n) & rw for n in c["names"]):
                found.setdefault(k, {}).setdefault("registration", set()).add(lei)
        for n in {sanctions.normalise(x) for x in names}:
            for k in by_name.get(n, ()):
                c = companies[k]
                if rec["country"] in c["countries"] and any(distinctive(x) for x in c["names"] if sanctions.normalise(x) == n):
                    found.setdefault(k, {}).setdefault("name", set()).add(lei)
    out = {}
    for k, how in found.items():
        for h in ("lei", "registration"):
            if how.get(h):
                out[k] = {"leis": sorted(how[h]), "how": h}
                break
        else:
            if len(how["name"]) == 1:              # one record with this name in the country: the same company
                out[k] = {"leis": sorted(how["name"]), "how": "name"}
    return out


def _stamp(path) -> str:
    """The publication of a downloaded golden-copy file, from the name of the file inside the zip."""
    try:
        return zipfile.ZipFile(path).namelist()[0][:13]
    except (OSError, zipfile.BadZipFile, IndexError):
        return ""


def _latest() -> dict:
    d = json.loads(fetch.get(LATEST).body)["data"]
    return {"publish_date": d["publish_date"], "lei2": d["lei2"]["full_file"]["csv"]["url"],
            "rr": d["rr"]["full_file"]["csv"]["url"]}


def fetch_all(download: bool = True) -> dict:
    """Download the golden copy (unless it is current), match the list companies, keep their records and one step of
    relationships in data/gleif/gleif.json."""
    DIR.mkdir(parents=True, exist_ok=True)
    meta = {"retrieved": dt.date.today().isoformat(), "licence": LICENCE, "source": "https://www.gleif.org/en/lei-data/gleif-golden-copy"}
    if download:
        latest = _latest()
        stamp = latest["publish_date"][:16].replace("-", "").replace(" ", "-").replace(":", "")     # 20261021-0800
        for k in ("lei2", "rr"):
            if _stamp(DIR / f"{k}.csv.zip") != stamp:     # the files of this publication are here already
                log.info("GLEIF: downloading %s", latest[k])
                fetch.download(latest[k], DIR / f"{k}.csv.zip", max_bytes=2 * 2**30)
        meta["publish_date"] = latest["publish_date"]
    else:
        meta["publish_date"] = stored()["meta"].get("publish_date", "")
    companies = list_companies()
    wanted_names = {sanctions.normalise(n) for c in companies.values() for n in c["names"]}
    wanted_nums = {n for c in companies.values() for n in c["numbers"]}
    wanted_leis = {l for c in companies.values() for l in c["leis"]}
    rows = _rows(DIR / "lei2.csv.zip")
    ix = next(rows)
    name_cols = [ix[COLS["name"]], *(ix[c] for c in OTHER)]
    cands = {}
    for row in rows:                                     # pass 1: records that could be a list company
        if (row[0] in wanted_leis or identity.number(row[ix[COLS["reg"]]]) in wanted_nums
                or any(row[i] and sanctions.normalise(row[i]) in wanted_names for i in name_cols)):
            cands[row[0]] = _record(row, ix)
    matches = match(companies, cands)
    mine = {l for m in matches.values() for l in m["leis"]}
    relations = []
    rr = _rows(DIR / "rr.csv.zip")
    rx = next(rr)
    for row in rr:                                      # the relationships of the matched companies
        a, b, typ = row[rx["Relationship.StartNode.NodeID"]], row[rx["Relationship.EndNode.NodeID"]], row[rx["Relationship.RelationshipType"]]
        if typ in RELATIONS and (a in mine or b in mine):
            periods = {row[rx[f"Relationship.Period.{i}.periodType"]]: (row[rx[f"Relationship.Period.{i}.startDate"]][:10],
                                                                         row[rx[f"Relationship.Period.{i}.endDate"]][:10]) for i in range(1, 6)}
            rel_p, acc_p = periods.get("RELATIONSHIP_PERIOD", ("", "")), periods.get("ACCOUNTING_PERIOD", ("", ""))
            relations.append({"child": a, "parent": b, "type": typ, "status": row[rx["Relationship.RelationshipStatus"]],
                              "start": rel_p[0], "end": rel_p[1], "accounts": list(acc_p) if acc_p[0] else [],
                              "validation": row[rx["Registration.ValidationSources"]], "reference": row[rx["Registration.ValidationReference"]]})
    need = {x for r in relations for x in (r["child"], r["parent"])} - set(cands)
    records = {l: cands[l] for l in mine}
    if need:
        rows = _rows(DIR / "lei2.csv.zip")
        ix = next(rows)
        for row in rows:                                 # pass 2: the related companies' own records
            if row[0] in need:
                records[row[0]] = _record(row, ix)
    for r in relations:
        for x in (r["child"], r["parent"]):
            if x in cands:
                records.setdefault(x, cands[x])
    data = {"meta": meta, "matches": matches, "records": records, "relations": relations}
    FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    stored.cache_clear()
    by_how: dict[str, int] = {}
    for m in matches.values():
        by_how[m["how"]] = by_how.get(m["how"], 0) + 1
    return {"list companies": len(companies), "matched": len(matches), "by": by_how, "records": len(records),
            "relations": len(relations)}


@lru_cache(maxsize=1)
def stored() -> dict:
    if not FILE.exists():
        return {"meta": {}, "matches": {}, "records": {}, "relations": []}
    return json.loads(FILE.read_text(encoding="utf-8"))


def label(rec: dict) -> str:
    """A record's name in Latin letters where GLEIF gives one (a transliterated or English name), else its legal name."""
    if re.search(r"[A-Za-z]", rec["name"]) and not re.search(r"[Ѐ-ӿ؀-ۿ]", rec["name"]):
        return rec["name"]
    return next((n for n in rec.get("other", []) if re.search(r"[A-Za-z]{3}", n)
                 and not re.search(r"[Ѐ-ӿ؀-ۿ]", n)), rec["name"])
