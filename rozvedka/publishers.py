"""Credibility profiles of the publishers that are not states: think tanks (registry `publisher: independent`) and
commercial analysts (`publisher: commercial` – companies selling political-risk or threat analysis to clients). Evidence,
not a score (docs/PUBLISHER_PROFILES.md).

Hand-researched (sources/publishers.yaml): how openly a think tank discloses its funding and which governments fund it;
who owns a company and whether it names its clients; named authors and a published method; former transparency ratings;
owners, sponsors, founders and partners, each with its evidence. Fetched (`fetch-publishers`, stored in
data/gazetteer/publishers.json):
  - EU Transparency Register entry, matched by website domain (official; declared EU grants and lobbying costs);
  - US FARA registrations as agent of a foreign principal, matched by name (official, efile.fara.gov API);
  - sanctions lists of the US (OFAC SDN), UK, EU and UN, matched by name (official);
  - US federal contracts and grants to the recipients the profile names exactly (official, USAspending.gov);
  - identity from Wikidata and Wikipedia (founded, headquarters, founders, owners, parent, leaders; revision and date).
The rating is a rule over those checks – shown with every reason, never as a number:
  red flag   – on a sanctions list, or registered in the US as agent of a foreign principal
  concerns   – think tank: donors not disclosed, or a donor government that V-Dem rates an autocracy;
               company: owners not disclosed, or owned by the state of an autocracy
  partial    – think tank: donors named without amounts, or only kinds of funders; company: owners named without stakes;
               either: authors not named or no method published (when checked)
  transparent – think tank: donors named with amounts or in brackets; company: listed, or owners named with stakes
  unassessed – no profile yet.
The owners, sponsors and other ties of every profile also become links of the network (layer "publishers", ties.py)."""
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
# a company sells analysis to clients: what can be checked is who owns it (and so who it answers to), not donors
COMMERCIAL_LEVELS = {
    "redflag": LEVELS["redflag"],
    "concerns": ("concerns", "owners not disclosed, or owned by the state of an autocracy"),
    "partial": ("partly transparent", "owners named without their stakes, or authors / method not published"),
    "transparent": ("transparent ownership", "listed company, or owners named with their stakes"),
    "unassessed": LEVELS["unassessed"],
}
KINDS = {   # registry `publisher` → how the kind is named and marked wherever a source, report, count or map point is shown
    "independent": {"name": "think tank", "plural": "think tanks", "mark": "◆", "type": "think-tank", "levels": LEVELS,
                    "about": "an independent publisher – a think tank, not run by a state"},
    "commercial": {"name": "commercial analyst", "plural": "commercial analysts", "mark": "■", "type": "commercial",
                   "levels": COMMERCIAL_LEVELS,
                   "about": "a company selling political-risk or threat analysis to clients – neither a state agency nor a think tank"},
}
OWNERSHIP = {   # key → (label, status)
    "listed": ("listed company – its shareholders are in public filings", "ok"),
    "stakes": ("owners named with their stakes", "ok"),
    "named": ("owners named, their stakes not published", "partial"),
    "none": ("owners not disclosed", "concern"),
}
CLIENTS = {
    "named": ("clients named", "ok"),
    "some": ("some clients or partners named", "partial"),
    "none": ("clients not disclosed – usual for consultancies, so it does not change the rating", "unknown"),
}
USASPENDING = "https://api.usaspending.gov/api/v2/search/spending_by_category/{category}/"
USASPENDING_RECIPIENT = "https://www.usaspending.gov/recipient/{id}/latest"
USASPENDING_PERIOD = ("2007-10-01", None)     # the first fiscal year the API searches (FY2008) to today
AWARD_TYPES = ["A", "B", "C", "D", "02", "03", "04", "05"]    # contracts and grants (no loans, no direct payments)
_BAD_XML = re.compile(rb"&#(x0*[0-8bBcCeEfF]|x0*1[0-9a-fA-F]|0*[0-8]|0*1[1-2]|0*1[4-9]|0*2[0-9]|0*3[01]);")
WIKIDATA_PROPS = {"P571": "founded", "P159": "headquarters", "P112": "founded by", "P488": "chairperson",
                  "P1037": "director", "P169": "chief executive", "P127": "owned by", "P749": "parent organisation",
                  "P8324": "funder", "P414": "stock exchange", "P1454": "legal form", "P1128": "employees", "P856": "website"}
# the Wikidata facts that are ties to another subject (network layer "publishers"): fact → (it …, … of it)
WIKIDATA_TIES = {"founded by": ("founded by", "founder of"), "chairperson": ("chaired by", "chair of"),
                 "director": ("directed by", "director of"), "chief executive": ("led by", "chief executive of"),
                 "owned by": ("owned by", "owner of"), "parent organisation": ("part of", "parent organisation of"),
                 "funder": ("funded by", "funder of")}


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


def _post(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"User-Agent": UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def us_awards(names: dict[str, list[str]], today: str | None = None) -> dict[str, dict]:
    """{source key: US federal contracts and grants} to the recipients a profile names exactly (`us_awards`), by awarding
    agency, since FY2008 (USAspending.gov). The API searches names loosely ("GRAPHIKA" also finds other companies), so
    only recipients whose registered name is exactly one of the names count."""
    import time
    period = [{"start_date": USASPENDING_PERIOD[0], "end_date": today or dt.date.today().isoformat()}]
    out: dict[str, dict] = {}
    for key, wanted in names.items():
        recipients, agencies = [], {}
        for name in wanted:
            found = _post(USASPENDING.format(category="recipient"), {"filters": {
                "recipient_search_text": [name], "time_period": period, "award_type_codes": AWARD_TYPES}, "limit": 100})
            time.sleep(1)
            for r in found.get("results", []):
                if _norm(r["name"]) != _norm(name) or any(x["id"] == r["recipient_id"] for x in recipients):
                    continue
                recipients.append({"name": r["name"], "id": r["recipient_id"], "uei": r.get("uei"), "amount": r["amount"],
                                   "url": USASPENDING_RECIPIENT.format(id=r["recipient_id"])})
                by = _post(USASPENDING.format(category="awarding_agency"), {"filters": {
                    "recipient_id": r["recipient_id"], "time_period": period, "award_type_codes": AWARD_TYPES}, "limit": 50})
                time.sleep(1)
                for a in by.get("results", []):
                    agencies[a["name"]] = agencies.get(a["name"], 0) + (a["amount"] or 0)
        out[key] = {"recipients": recipients, "period": [period[0]["start_date"], period[0]["end_date"]],
                    "agencies": [{"name": k, "amount": v} for k, v in sorted(agencies.items(), key=lambda x: -x[1]) if v > 0],
                    "total": sum(v for v in agencies.values() if v > 0)}
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
    ref_ents = src.entities(list(refs), "labels|claims", ["en"]) if refs else {}
    labels = {k: v.get("labels", {}).get("en", {}).get("value", k) for k, v in ref_ents.items()}
    humans = {k for k, v in ref_ents.items() if any(c["mainsnak"].get("datavalue", {}).get("value", {}).get("id") == "Q5"
                                                    for c in src._claims(v, "P31"))}
    out = {}
    for key, title in titles.items():
        qid = qids.get(title)
        e = ents.get(qid) if qid else None
        facts: dict[str, list[str]] = {}
        subjects: dict[str, list[dict]] = {}      # facts that name another subject, with its Wikidata item
        for prop, label in WIKIDATA_PROPS.items():
            for c in src._claims(e, prop) if e else []:
                v = c["mainsnak"]["datavalue"]
                if v["type"] == "wikibase-entityid":
                    ref = v["value"]["id"]
                    facts.setdefault(label, []).append(labels.get(ref, ref))
                    subjects.setdefault(label, []).append({"qid": ref, "label": labels.get(ref, ref), "property": prop,
                                                           "person": ref in humans})
                elif v["type"] == "time":
                    facts.setdefault(label, []).append(src._time(v["value"]))
                elif v["type"] == "quantity":
                    facts.setdefault(label, []).append(v["value"]["amount"].lstrip("+"))
                elif v["type"] == "string":
                    facts.setdefault(label, []).append(v["value"])
        out[key] = {"qid": qid, "wikidata": f"https://www.wikidata.org/wiki/{qid}" if qid else None,
                    "revision": e.get("lastrevid") if e else None, "facts": facts, "subjects": subjects,
                    "wikipedia": leads.get(title)}
    return out


def fetch(out: Path | None = None) -> dict:
    """Run every fetched check for the publishers of the registry that are not states (think tanks, companies)."""
    from . import registry
    profiles = load_profiles()
    srcs = {registry.source_key(s): s for s in registry.load() if s.get("publisher") in KINDS}
    domains = {_domain(s["homepage"]): k for k, s in srcs.items() if s.get("homepage")}
    names = {k: [n for n in (s["agency"], s.get("name_en"), s.get("name_local")) if n] for k, s in srcs.items()}
    titles = {k: profiles.get(k, {}).get("wikipedia") for k in srcs if profiles.get(k, {}).get("wikipedia")}
    today = dt.date.today().isoformat()
    store = {"retrieved": today, "eu_register": eu_register(domains), "fara": fara(names),
             "sanctions": sanctions(names), "identity": identity(titles),
             "us_awards": us_awards({k: p["us_awards"] for k, p in profiles.items() if k in srcs and p.get("us_awards")}, today)}
    out = out or STORE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    load.cache_clear()
    summary = {"publishers": len(srcs), "in_eu_register": len(store["eu_register"]), "fara": len(store["fara"]),
               "sanctions_hits": store["sanctions"]["hits"], "identity": sum(1 for v in store["identity"].values() if v["qid"]),
               "us_awards": {k: round(v["total"]) for k, v in store["us_awards"].items()}}
    log.info("publishers %s", summary)
    return summary


@lru_cache(maxsize=1)
def load(path: Path | None = None) -> dict:
    p = path or STORE
    if not p.exists():
        return {"retrieved": None, "eu_register": {}, "fara": {}, "sanctions": {"lists": {}, "hits": {}}, "identity": {},
                "us_awards": {}}
    return {"us_awards": {}, **json.loads(p.read_text(encoding="utf-8"))}


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


def _methods_check(m: dict) -> dict:
    authors, method = m.get("authors") == "named", m.get("methodology")
    return {"key": "methods", "name": "People and methods", "status": "ok" if authors and method else "partial",
            "text": "; ".join([("authors named" if authors else "authors not named"),
                               ("method published" if method else "no published method")]),
            "note": m.get("note"),
            "evidence": [{"label": "method", "url": method}] if method else
                        [{"label": "publisher's site", "url": m["evidence"]}] if m.get("evidence") else [],
            "checked": str(m.get("checked"))}


def _awards_check(a: dict, checked) -> dict:
    agencies = a["agencies"]
    top = ", ".join(f"{x['name']} ${x['amount']:,.0f}" for x in agencies[:4]) + (f" and {len(agencies) - 4} more" if len(agencies) > 4 else "")
    return {"key": "us_awards", "name": "US federal contracts and grants", "status": "info",
            "text": (f"${a['total']:,.0f} since FY2008 – {top}" if a["total"] else "none found since FY2008")
                    + " (recipients: " + (", ".join(r["name"] for r in a["recipients"]) or "none of the names") + ")",
            "evidence": [{"label": f"USAspending: {r['name']}", "url": r["url"]} for r in a["recipients"]]
                        or [{"label": "USAspending.gov", "url": "https://www.usaspending.gov/search"}],
            "checked": checked, "agencies": agencies}


def profile(source_key: str, kind: str = "independent") -> dict:
    """Checks (each with status ok / partial / concern / redflag / unknown / info, text and evidence) and the rating.
    kind: the registry's `publisher` – "independent" (think tank) or "commercial" (company)."""
    p = load_profiles().get(source_key) or {}
    f = load()
    commercial = kind == "commercial"
    levels = KINDS.get(kind, KINDS["independent"])["levels"]
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
    funding, owners = p.get("funding"), p.get("ownership")
    assessed = owners if commercial else funding
    if funding and not commercial:
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
    if owners and commercial:
        label, status = OWNERSHIP[owners["disclosure"]]
        states = owners.get("states") or []          # states that own a stake (ISO alpha-3)
        autoc = _autocracies(states)
        checks.append({"key": "ownership", "name": "Ownership", "status": "concern" if autoc else status,
                       "text": label + ((" – owned in part by the state of " + ", ".join(f"{a['name']} ({a['regime']}, V-Dem {a['year']})" for a in autoc)) if autoc else ""),
                       "note": owners.get("note"), "evidence": [{"label": "ownership", "url": owners["evidence"]}],
                       "checked": str(owners.get("checked"))})
        cl = p.get("clients")
        if cl:
            label, status = CLIENTS[cl["disclosure"]]
            checks.append({"key": "clients", "name": "Clients", "status": status, "text": label, "note": cl.get("note"),
                           "evidence": [{"label": "clients", "url": cl["evidence"]}] if cl.get("evidence") else [],
                           "checked": str(cl.get("checked"))})
    if p.get("methods"):
        checks.append(_methods_check(p["methods"]))
    awards = f["us_awards"].get(source_key)
    if awards is not None:
        checks.append(_awards_check(awards, f["retrieved"]))
    reg = f["eu_register"].get(source_key)
    if f["retrieved"]:
        checks.append({"key": "eu_register", "name": "EU Transparency Register", "status": "ok" if reg else "unknown",
                       "text": (f"registered {reg['registered']} as “{reg['category']}”; EU grants in the last closed year: "
                                f"€{reg['eu_grants_total']:,.0f}") if reg else "not registered (required only for those lobbying EU institutions)",
                       "evidence": [{"label": f"entry {reg['id']}", "url": reg["url"]}] if reg else [{"label": "register", "url": "https://transparency-register.europa.eu/"}],
                       "checked": f["retrieved"], "entry": reg})
    statuses = {c["status"] for c in checks}
    if "redflag" in statuses:
        level = "redflag"
    elif not assessed:
        level = "unassessed"
    elif "concern" in statuses:
        level = "concerns"
    elif "partial" in statuses:
        level = "partial"
    else:
        level = "transparent"
    worst = {"redflag": ("redflag",), "concerns": ("concern",), "partial": ("partial",)}.get(level, ())
    reasons = [f"{c['name']}: {c['text']}" for c in checks if c["status"] in worst]
    return {"key": source_key, "kind": kind, "level": level, "label": levels[level][0], "about": levels[level][1],
            "levels": levels, "reasons": reasons, "checks": checks, "former": p.get("former_ratings") or [],
            "identity": f["identity"].get(source_key), "retrieved": f["retrieved"], "ties": influence(source_key)}


TIE_KINDS = {"person": "person", "org": "org", "company": "org", "foundation": "org", "government": "country", "country": "country"}
BACK = {"owned by": "owner of", "founded by": "founder of", "led by": "leads", "chaired by": "chairs", "funded by": "funds",
        "invested in by": "investor in", "part of": "has as part", "owner of": "owned by", "partner of": "partner of",
        "client of": "has as client", "works for": "has as client", "advised by": "adviser of"}


def influence(source_key: str) -> list[dict]:
    """Every owner, sponsor, founder, leader, parent and partner of a publisher that a source states, as ties
    {rel, back, name, kind, qid?, iso3?, amount?, evidence: [{label, url}], checked, origin}:
      - "profile": hand-researched in sources/publishers.yaml (`ties`), each with its evidence;
      - "funding": the donor governments of a think tank's funding disclosure;
      - "usaspending": the US federal agencies that gave contracts or grants (USAspending.gov);
      - "wikidata": owner, parent, founder, funder and leaders on its Wikidata item (with the revision)."""
    p = load_profiles().get(source_key) or {}
    f = load()
    out = []
    for t in p.get("ties") or []:
        out.append({"rel": t["rel"], "back": t.get("back") or BACK.get(t["rel"], "linked with"), "name": t["name"],
                    "kind": TIE_KINDS.get(t.get("kind", "org"), "org"), "qid": t.get("qid"), "iso3": t.get("country") if t.get("kind") == "government" else None,
                    "amount": t.get("amount"), "note": t.get("note"),
                    "evidence": [{"label": t.get("evidence_label") or "evidence", "url": t["evidence"]}],
                    "checked": str(t.get("checked") or ""), "origin": "profile"})
    funding = p.get("funding") or {}
    for g in funding.get("governments") or []:
        out.append({"rel": "funded by the government of", "back": "funds", "name": _country(g), "kind": "country", "iso3": g,
                    "evidence": [{"label": "publisher's funding disclosure", "url": funding["evidence"]}],
                    "checked": str(funding.get("checked") or ""), "origin": "funding"})
    awards = f["us_awards"].get(source_key) or {}
    for a in awards.get("agencies", []):
        out.append({"rel": "received US federal contracts or grants from", "back": "gave US federal contracts or grants to",
                    "name": f"US {a['name']}", "kind": "org", "amount": a["amount"],
                    "evidence": [{"label": f"USAspending: {r['name']}", "url": r["url"]} for r in awards["recipients"]],
                    "checked": f["retrieved"] or "", "origin": "usaspending", "period": awards.get("period")})
    idn = f["identity"].get(source_key) or {}
    for fact, subjects in (idn.get("subjects") or {}).items():
        if fact not in WIKIDATA_TIES:
            continue
        rel, back = WIKIDATA_TIES[fact]
        for x in subjects:
            out.append({"rel": rel, "back": back, "name": x["label"], "kind": "person" if x.get("person") else "org",
                        "qid": x["qid"],
                        "evidence": [{"label": f"Wikidata {x['property']} (revision {idn.get('revision')})", "url": idn.get("wikidata")}],
                        "checked": f["retrieved"] or "", "origin": "wikidata"})
    return out
