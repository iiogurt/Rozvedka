"""Credibility profiles of independent publishers (think tanks): evidence, not a score (docs/PUBLISHER_PROFILES.md).

Hand-researched (sources/publishers.yaml): how openly the publisher discloses its funding, which governments fund it,
former transparency ratings. Fetched (`fetch-publishers`, stored in data/gazetteer/publishers.json):
  - EU Transparency Register entry, matched by website domain (official; declared EU grants and lobbying costs);
  - US FARA registrations as agent of a foreign principal, matched by name (official, efile.fara.gov API);
  - sanctions lists of the US (OFAC SDN), UK, EU and UN, matched by name (official);
  - identity from Wikidata and Wikipedia (founded, headquarters, founders, leaders; revision and date).
The rating is a rule over those checks – shown with every reason, never as a number:
  red flag   – on a sanctions list, or registered in the US as agent of a foreign principal
  concerns   – donors not disclosed, or a donor government that V-Dem rates an autocracy
  partial    – donors named without amounts, or only kinds of funders
  transparent – donors named with amounts or in funding brackets
  unassessed – no profile yet."""
import csv
import datetime as dt
import io
import json
import logging
import re
import urllib.request
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from . import ratings, topics
from .config import DATA, ROOT

log = logging.getLogger("rozvedka.publishers")

PROFILES = ROOT / "sources" / "publishers.yaml"
STORE = DATA / "gazetteer" / "publishers.json"
UA = "Rozvedka/0.x (personal research library; https://github.com/iiogurt/Rozvedka)"
EU_REGISTER = "https://transparency-register.europa.eu/odplastorganisationxml_en"
EU_ENTRY = "https://transparency-register.europa.eu/searchregister-or-update/organisation-detail_en?id={id}"
FARA = "https://efile.fara.gov/api/v1/Registrants/json/{status}"
SANCTIONS = {
    "US OFAC SDN": "https://www.treasury.gov/ofac/downloads/sdn.csv",
    "UK sanctions list": "https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.csv",
    "EU financial sanctions": "https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw",
    "UN Security Council": "https://scsanctions.un.org/resources/xml/en/consolidated.xml",
}
DISCLOSURE = {   # key → (label, Transparify-like stars, status of the check)
    "amounts": ("donors named with amounts", 5, "ok"),
    "brackets": ("donors named in funding brackets", 4, "ok"),
    "names": ("donors named, no amounts", 3, "partial"),
    "categories": ("only kinds of funders or shares", 2, "partial"),
    "none": ("donors not disclosed", 1, "concern"),
}
LEVELS = {   # key → (label, description) – colours in style.css (.pub-lv-…), in this order of severity
    "redflag": ("red flag", "on a sanctions list or registered as agent of a foreign principal"),
    "concerns": ("concerns", "donors not disclosed, or funded by an autocratic government"),
    "partial": ("partly transparent", "donors named without amounts, or only kinds of funders"),
    "transparent": ("transparent funding", "donors named with amounts or in funding brackets"),
    "unassessed": ("not assessed", "no profile yet"),
}
_BAD_XML = re.compile(rb"&#(x0*[0-8bBcCeEfF]|x0*1[0-9a-fA-F]|0*[0-8]|0*1[1-2]|0*1[4-9]|0*2[0-9]|0*3[01]);")
WIKIDATA_PROPS = {"P571": "founded", "P159": "headquarters", "P112": "founded by", "P488": "chairperson",
                  "P1037": "director", "P1454": "legal form", "P1128": "employees", "P856": "website"}


def _get(url: str, timeout: int = 300) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
        return r.read()


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w ]", " ", topics.normalize(str(name or "")))).strip()


def _domain(url: str) -> str:
    host = urlsplit(url if "//" in (url or "") else "//" + (url or "")).hostname or ""
    return host.lower().removeprefix("www.")


def load_profiles(path: Path | None = None) -> dict:
    return yaml.safe_load((path or PROFILES).read_text(encoding="utf-8")) or {}


# ── fetched checks ──
def eu_register(domains: dict[str, str]) -> dict[str, dict]:
    """{source key: register entry} for publishers whose website domain is registered (streamed: 100+ MB XML)."""
    out: dict[str, dict] = {}
    parser = ET.XMLPullParser(events=("end",))
    req = urllib.request.Request(EU_REGISTER, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=600) as f:
        first = True
        for line in f:
            if first:
                line, first = line.replace(b"version='1.1'", b"version='1.0'"), False
            parser.feed(_BAD_XML.sub(b"", line))
            for _, el in parser.read_events():
                if el.tag != "interestRepresentative":
                    continue
                d = _domain(el.findtext("webSiteURL") or "")
                key = domains.get(d)
                if key:
                    closed = el.find("financialData/closedYear")
                    grants = [{"source": (g.findtext("source") or "").strip(), "amount": float(g.findtext("amount/absoluteCost") or 0)}
                              for g in (closed.findall("grants/grant") if closed is not None else [])]
                    cost = closed.find("costs/range") if closed is not None else None
                    out[key] = {"id": el.findtext("identificationCode"), "name": el.findtext("name/originalName"),
                                "category": el.findtext("registrationCategory"),
                                "registered": (el.findtext("registrationDate") or "")[:10],
                                "updated": (el.findtext("lastUpdateDate") or "")[:10],
                                "year": [(closed.findtext("startDate") or "")[:10], (closed.findtext("endDate") or "")[:10]] if closed is not None else None,
                                "eu_grants": grants, "eu_grants_total": sum(g["amount"] for g in grants),
                                "lobbying_cost": [cost.findtext("min"), cost.findtext("max")] if cost is not None else None,
                                "url": EU_ENTRY.format(id=el.findtext("identificationCode"))}
                el.clear()
    return out


def fara(names: dict[str, list[str]]) -> dict[str, list[dict]]:
    """{source key: [FARA registrations]} matched by exact (normalised) organisation name."""
    wanted = {_norm(n): key for key, ns in names.items() for n in ns if len(_norm(n)) > 4}
    out: dict[str, list[dict]] = {}
    for status in ("Active", "Terminated"):
        data = json.loads(_get(FARA.format(status=status)))
        rows = next(iter(data.values()))["ROW"]
        for r in rows if isinstance(rows, list) else [rows]:
            for field in ("Name", "Business_Name"):
                key = wanted.get(_norm(r.get(field) or ""))
                if key:
                    out.setdefault(key, []).append({"number": r.get("Registration_Number"), "name": r.get("Name"),
                                                    "status": status, "registered": r.get("Registration_Date"),
                                                    "terminated": r.get("Termination_Date"),
                                                    "url": f"https://efile.fara.gov/ords/fara/f?p=1235:10:::NO::P10_REG_NUMBER:{r.get('Registration_Number')}"})
    return out


def _sanction_names(label: str, raw: bytes) -> set[str]:
    """Every listed name (entities, aliases) of one sanctions list, normalised."""
    names: set[str] = set()
    if label == "UN Security Council":
        root = ET.fromstring(raw)
        for tag in ("FIRST_NAME", "ALIAS_NAME"):
            names |= {_norm(e.text) for e in root.iter(tag) if e.text}
        return names
    text = raw.decode("utf-8-sig", "replace")
    if label == "US OFAC SDN":
        names |= {_norm(r[1]) for r in csv.reader(io.StringIO(text)) if len(r) > 1}
    elif label == "UK sanctions list":
        lines = text.splitlines()
        rows = csv.DictReader(io.StringIO("\n".join(lines[1:])))       # first line: "Last Updated, …"
        names |= {_norm(r.get("Name 6") or "") for r in rows}
    else:                                                             # EU: semicolon-separated
        rows = csv.DictReader(io.StringIO(text), delimiter=";")
        names |= {_norm(r.get("NameAlias_WholeName") or "") for r in rows}
    return names - {""}


def sanctions(names: dict[str, list[str]]) -> dict:
    """{"lists": {label: {url, entries}}, "hits": {source key: [label, …]}} – exact matches of normalised names."""
    out = {"lists": {}, "hits": {}}
    for label, url in SANCTIONS.items():
        listed = _sanction_names(label, _get(url))
        out["lists"][label] = {"url": url, "names": len(listed)}
        for key, ns in names.items():
            if any(len(_norm(n)) > 4 and _norm(n) in listed for n in ns):
                out["hits"].setdefault(key, []).append(label)
    return out


def identity(titles: dict[str, str]) -> dict[str, dict]:
    """Wikidata facts and the Wikipedia lead of each publisher, with revision and links."""
    from . import actor_sources as src
    qids = src.resolve_titles(list(titles.values()), what="publisher")
    ents = src.entities(list(set(qids.values())), "labels|claims|info", ["en"])
    leads = src.wikipedia_leads(list(titles.values()))
    # labels of the items the claims point to (headquarters, founders, leaders)
    refs = {c["mainsnak"]["datavalue"]["value"]["id"] for e in ents.values() for p in WIKIDATA_PROPS
            for c in src._claims(e, p) if c["mainsnak"]["datavalue"]["type"] == "wikibase-entityid"}
    labels = {k: v.get("labels", {}).get("en", {}).get("value", k) for k, v in src.entities(list(refs), "labels", ["en"]).items()} if refs else {}
    out = {}
    for key, title in titles.items():
        qid = qids.get(title)
        e = ents.get(qid) if qid else None
        facts: dict[str, list[str]] = {}
        for prop, label in WIKIDATA_PROPS.items():
            for c in src._claims(e, prop) if e else []:
                v = c["mainsnak"]["datavalue"]
                if v["type"] == "wikibase-entityid":
                    facts.setdefault(label, []).append(labels.get(v["value"]["id"], v["value"]["id"]))
                elif v["type"] == "time":
                    facts.setdefault(label, []).append(src._time(v["value"]))
                elif v["type"] == "quantity":
                    facts.setdefault(label, []).append(v["value"]["amount"].lstrip("+"))
                elif v["type"] == "string":
                    facts.setdefault(label, []).append(v["value"])
        out[key] = {"qid": qid, "wikidata": f"https://www.wikidata.org/wiki/{qid}" if qid else None,
                    "revision": e.get("lastrevid") if e else None, "facts": facts, "wikipedia": leads.get(title)}
    return out


def fetch(out: Path | None = None) -> dict:
    """Run every fetched check for the independent publishers of the registry."""
    from . import registry
    profiles = load_profiles()
    srcs = {registry.source_key(s): s for s in registry.load() if s.get("publisher") == "independent"}
    domains = {_domain(s["homepage"]): k for k, s in srcs.items() if s.get("homepage")}
    names = {k: [n for n in (s["agency"], s.get("name_en"), s.get("name_local")) if n] for k, s in srcs.items()}
    titles = {k: profiles.get(k, {}).get("wikipedia") for k in srcs if profiles.get(k, {}).get("wikipedia")}
    today = dt.date.today().isoformat()
    store = {"retrieved": today, "eu_register": eu_register(domains), "fara": fara(names),
             "sanctions": sanctions(names), "identity": identity(titles)}
    out = out or STORE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    load.cache_clear()
    summary = {"publishers": len(srcs), "in_eu_register": len(store["eu_register"]), "fara": len(store["fara"]),
               "sanctions_hits": store["sanctions"]["hits"], "identity": sum(1 for v in store["identity"].values() if v["qid"])}
    log.info("publishers %s", summary)
    return summary


@lru_cache(maxsize=1)
def load(path: Path | None = None) -> dict:
    p = path or STORE
    if not p.exists():
        return {"retrieved": None, "eu_register": {}, "fara": {}, "sanctions": {"lists": {}, "hits": {}}, "identity": {}}
    return json.loads(p.read_text(encoding="utf-8"))


# ── the profile and its rating ──
def _country(a3: str) -> str:
    return ratings.load().get("names", {}).get(a3, a3)


def _autocracies(govs: list[str]) -> list[dict]:
    """Donor governments that V-Dem rates a closed or electoral autocracy in its latest year."""
    out = []
    values = ratings.load().get("values", {})
    for a3 in govs:
        reg = values.get(a3, {}).get("vdem_regime", {})
        if reg:
            year = max(reg, key=int)
            if int(reg[year]) <= 1:
                out.append({"country": a3, "name": _country(a3), "year": int(year), "regime": ratings.REGIMES[int(reg[year])]})
    return out


def profile(source_key: str) -> dict:
    """Checks (each with status ok / partial / concern / redflag / unknown, text and evidence) and the rating."""
    p = load_profiles().get(source_key) or {}
    f = load()
    checks = []
    hits = f["sanctions"]["hits"].get(source_key, [])
    if f["sanctions"]["lists"]:
        checks.append({"key": "sanctions", "name": "Sanctions lists", "status": "redflag" if hits else "ok",
                       "text": ("listed by " + ", ".join(hits)) if hits else "on none of the lists of the US (OFAC), UK, EU and UN",
                       "evidence": [{"label": k, "url": v["url"]} for k, v in f["sanctions"]["lists"].items()],
                       "checked": f["retrieved"]})
    fara_rows = f["fara"].get(source_key, [])
    if f["retrieved"]:
        checks.append({"key": "fara", "name": "US foreign-agent registration (FARA)",
                       "status": "redflag" if any(r["status"] == "Active" for r in fara_rows) else ("partial" if fara_rows else "ok"),
                       "text": ("registered: " + ", ".join(f"no. {r['number']} ({r['status'].lower()})" for r in fara_rows))
                               if fara_rows else "no registration as agent of a foreign principal",
                       "evidence": [{"label": f"FARA no. {r['number']}", "url": r["url"]} for r in fara_rows]
                                   or [{"label": "FARA registrant lists", "url": "https://efile.fara.gov/api"}],
                       "checked": f["retrieved"]})
    funding = p.get("funding")
    if funding:
        label, stars, status = DISCLOSURE[funding["disclosure"]]
        checks.append({"key": "funding", "name": "Funding transparency", "status": status, "stars": stars,
                       "text": label, "note": funding.get("note"),
                       "evidence": [{"label": "publisher's disclosure", "url": funding["evidence"]}],
                       "checked": str(funding.get("checked"))})
        govs = funding.get("governments") or []
        autoc = _autocracies(govs)
        checks.append({"key": "governments", "name": "Government donors", "status": "concern" if autoc else "ok",
                       "text": (("from autocracies: " + ", ".join(f"{a['name']} ({a['regime']}, V-Dem {a['year']})" for a in autoc) + "; ")
                                if autoc else "") + (("named: " + ", ".join(_country(g) for g in govs)) if govs else "none named"),
                       "evidence": [{"label": "democracy ratings", "url": "/ratings"}], "checked": str(funding.get("checked"))})
    reg = f["eu_register"].get(source_key)
    if f["retrieved"]:
        checks.append({"key": "eu_register", "name": "EU Transparency Register", "status": "ok" if reg else "unknown",
                       "text": (f"registered {reg['registered']} as “{reg['category']}”; EU grants in the last closed year: "
                                f"€{reg['eu_grants_total']:,.0f}") if reg else "not registered (required only for those lobbying EU institutions)",
                       "evidence": [{"label": f"entry {reg['id']}", "url": reg["url"]}] if reg else [{"label": "register", "url": "https://transparency-register.europa.eu/"}],
                       "checked": f["retrieved"], "entry": reg})
    statuses = {c["status"] for c in checks}
    if not funding:
        level = "redflag" if "redflag" in statuses else "unassessed"
    elif "redflag" in statuses:
        level = "redflag"
    elif "concern" in statuses:
        level = "concerns"
    elif "partial" in statuses:
        level = "partial"
    else:
        level = "transparent"
    worst = {"redflag": ("redflag",), "concerns": ("concern",), "partial": ("partial",)}.get(level, ())
    reasons = [f"{c['name']}: {c['text']}" for c in checks if c["status"] in worst]
    return {"key": source_key, "level": level, "label": LEVELS[level][0], "about": LEVELS[level][1], "reasons": reasons,
            "checks": checks, "former": p.get("former_ratings") or [], "identity": f["identity"].get(source_key),
            "retrieved": f["retrieved"]}
