"""The same person, company or vessel on several sanctions lists, and the details list entries share.

The four lists (rozvedka/sanctions.py) describe many of the same targets separately. Entries are recognised as one when
  - a list says so: a UK or EU entry gives the UN reference number of a UN listing;
  - they give the same vessel IMO number, or the same passport, national ID, company registration or tax number and share
    a word of their names (a number alone could be a typing error on one list);
  - they have the same name, word for word in any order (an alias counts), and – for people – the same date of birth (only
    the year where a list gives no more: then the name needs three words); for
    companies and groups the name must have at least two words, not only generic ones, and belong to one entry per list.
Every merge keeps its reason, shown on the entity's page. Entries tied to two different actors are never merged, and a
target holds at most one entry of each list – so entries that only share an alias (front companies all listed with the alias
"Yasa Part") are not chained into one; the strongest reasons are applied first.

Details that two different targets share – a street address, an e-mail address, a website, a telephone number, a crypto
wallet – become entities of their own in the network, linked to each entry that gives them (layer "ids"), so a shared
address is a path between two companies. The UK list also names parent companies, subsidiaries and ships' owners and
operators; those are linked by name.
"""
import hashlib
import re
from urllib.parse import urlparse

from . import actors, sanctions

MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
STRONG = {"passport", "national-id", "registration", "tax", "imo"}
MIN_NUMBER = 6
MIN_STREET = 10
LIST_ORDER = ("UN", "EU", "UK", "US", "FBI", "EUMW")   # whose entry names a merged entity when no actor does (wanted notices last)

US_IDS = {"Passport": "passport", "National ID No.": "national-id", "Cedula No.": "national-id", "C.U.R.P.": "national-id",
          "Identification Number": "national-id", "Registration Number": "registration", "Business Registration Number": "registration",
          "Company Number": "registration", "Tax ID No.": "tax", "R.F.C.": "tax", "Folio Mercantil No.": "registration",
          "Vessel Registration Identification": "imo", "MMSI": "mmsi", "Legal Entity Number": "lei"}
EU_IDS = {"passport": "passport", "id": "national-id", "regnumber": "registration", "fiscalcode": "tax", "taxid": "tax", "imo": "imo"}
UN_IDS = {"Passport": "passport", "National Identification Number": "national-id"}


def _tag(e) -> str:
    return e.tag.rsplit("}", 1)[-1]


def _all(e, tag: str) -> list:
    return [x for x in e.iter() if _tag(x) == tag]


def _texts(e, tag: str) -> list[str]:
    return [(x.text or "").strip() for x in _all(e, tag) if (x.text or "").strip()]


def number(s: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", (s or "").upper())


def imo(s: str) -> str:
    m = re.search(r"(?<!\d)(\d{7})(?!\d)", s or "")          # "IMO 9187629", "IMO9610808"
    return m.group(1) if m else ""


def dob(s: str) -> str:
    """'10 Dec 1948', '12/03/1960', 'dd/mm/1945', '1948-12-10', 'circa 1970' → '1948-12-10' or '1945' ('' if none)."""
    s = (s or "").strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    m = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{4})\b", s)
    if m and m.group(2).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b", s)        # 'December 28, 1951' (wanted notices)
    if m and m.group(1).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    m = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\b", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.search(r"\b(1[89]\d{2}|20\d{2})\b", s)
    return m.group(1) if m else ""


def _phones(s: str) -> list[str]:
    """One field can hold several numbers ("+41 22 320 88 36; +41 22 320 74 00"): 8–15 digits each."""
    out = []
    for part in re.split(r"[,;/]|\bor\b|\band\b", s or ""):
        d = re.sub(r"\D", "", part)
        if 8 <= len(d) <= 15:
            out.append(d)
    return out


PLATFORMS = {"vk.com", "t.me", "telegram.me", "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com", "ok.ru",
             "linkedin.com", "tiktok.com", "rutube.ru", "dzen.ru", "github.com", "telegram.org"}


def _web(s: str) -> str:
    """A website by its host ('https://www.ghu.by/x' → 'ghu.by'); on a platform the account counts ('vk.com/name')."""
    s = (s or "").strip().lower()
    if not s:
        return ""
    u = urlparse(s if "://" in s else "http://" + s)
    host = u.hostname or ""
    host = host[4:] if host.startswith("www.") else host
    if host in PLATFORMS:
        account = next((x for x in u.path.split("/") if x), "")
        return f"{host}/{account}" if account else ""
    return host if "." in host else ""


def _email(s: str) -> str:
    s = (s or "").strip().lower()
    return s if re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", s) else ""


def _address(street: str, city: str, country: str) -> dict | None:
    street = " ".join((street or "").split())
    if len(sanctions.normalise(street)) < MIN_STREET or not re.search(r"\d", street):
        return None                       # "Moscow" or "Tehran, Iran" is a city, not an address two companies share
    return {"street": street, "city": " ".join((city or "").split()), "country": " ".join((country or "").split())}


def details(e, kind: str) -> dict:
    """What identifies one list entry beyond its names (the XML element of the entry)."""
    d = {"dob": [], "ids": [], "addresses": [], "emails": [], "webs": [], "phones": [], "wallets": [], "un": "",
         "parents": [], "subsidiaries": [], "owners": []}

    def add_id(k, raw, country=""):
        n = imo(raw) if k == "imo" else number(raw)
        if n and (k == "imo" or len(n) >= MIN_NUMBER) and [k, n, country] not in d["ids"]:
            d["ids"].append([k, n, country])

    if kind == "US":
        d["dob"] = [dob(x) for x in _texts(e, "dateOfBirth")]
        for i in _all(e, "id"):
            t = sanctions._text(i, "idType")
            v = sanctions._text(i, "idNumber")
            if t in US_IDS:
                add_id(US_IDS[t], v, sanctions._text(i, "idCountry"))
            elif t == "Email Address":
                d["emails"].append(_email(v))
            elif t == "Website":
                d["webs"].append(_web(v))
            elif t == "Phone Number":
                d["phones"] += _phones(v)
            elif t.startswith("Digital Currency Address - "):
                d["wallets"].append(v.strip())
        for a in _all(e, "address"):
            d["addresses"].append(_address(" ".join(x for x in (sanctions._text(a, "address1"), sanctions._text(a, "address2"),
                                                                  sanctions._text(a, "address3")) if x),
                                           sanctions._text(a, "city"), sanctions._text(a, "country")))
    elif kind == "UK":
        d["dob"] = [dob(x) for x in _texts(e, "DOB")]
        for x in _texts(e, "PassportNumber"):
            add_id("passport", x)
        for x in _texts(e, "NationalIdentifierNumber"):
            add_id("national-id", x)
        for x in _texts(e, "IMONumber"):
            add_id("imo", x)
        for x in _texts(e, "BusinessRegistrationNumber"):
            for n in re.findall(r"\d[\d\-/ ]{4,}\d", x):     # often several numbers in one field, with their names
                add_id("registration", n.split("/")[0])
        d["emails"] = [_email(x) for x in _texts(e, "EmailAddress")]
        d["webs"] = [_web(x) for x in _texts(e, "Website")]
        d["phones"] = [p for x in _texts(e, "PhoneNumber") for p in _phones(x)]
        for a in _all(e, "Address"):
            lines = [sanctions._text(a, f"AddressLine{i}") for i in range(1, 7)]
            lines = [x for x in lines if x]
            d["addresses"].append(_address(", ".join(lines[:-1]) if len(lines) > 1 else "".join(lines),
                                           lines[-1] if len(lines) > 1 else "", sanctions._text(a, "AddressCountry")))
        d["un"] = sanctions._text(e, "UNReferenceNumber")
        d["parents"] = _texts(e, "ParentCompany")
        d["subsidiaries"] = _texts(e, "Subsidiary")
        d["owners"] = _texts(e, "CurrentOwnerOperator")
    elif kind == "EU":
        d["dob"] = [b.get("birthdate") or b.get("year") or "" for b in _all(e, "birthdate")]
        for i in _all(e, "identification"):
            if i.get("identificationTypeCode") in EU_IDS:
                add_id(EU_IDS[i.get("identificationTypeCode")], i.get("number") or i.get("latinNumber") or "", i.get("countryIso2Code") or "")
        for a in _all(e, "address"):
            d["addresses"].append(_address(a.get("street"), a.get("city"), a.get("countryDescription")))
        for c in _all(e, "contactInfo"):
            k, v = c.get("key"), c.get("value") or ""
            if k == "EMAIL":
                d["emails"].append(_email(v))
            elif k == "WEB":
                d["webs"].append(_web(v))
            elif k == "PHONE":
                d["phones"] += _phones(v)
        d["un"] = e.get("unitedNationId") or ""
    elif kind == "UN":
        for b in _all(e, "INDIVIDUAL_DATE_OF_BIRTH"):
            d["dob"].append(dob(sanctions._text(b, "DATE") or sanctions._text(b, "YEAR")))
        for doc in _all(e, "INDIVIDUAL_DOCUMENT"):
            t = sanctions._text(doc, "TYPE_OF_DOCUMENT")
            if t in UN_IDS:
                add_id(UN_IDS[t], sanctions._text(doc, "NUMBER"), sanctions._text(doc, "ISSUING_COUNTRY"))
        for a in _all(e, "INDIVIDUAL_ADDRESS") + _all(e, "ENTITY_ADDRESS"):
            d["addresses"].append(_address(sanctions._text(a, "STREET"), sanctions._text(a, "CITY"), sanctions._text(a, "COUNTRY")))
    for k in ("dob", "emails", "webs", "phones", "wallets"):
        d[k] = sorted({x for x in d[k] if x})
    d["addresses"] = [a for i, a in enumerate(d["addresses"]) if a and a not in d["addresses"][:i]]
    return d


LEGAL_FORMS = set("""pao pjsc jsc oao ojsc zao cjsc ooo llc ltd limited co company inc corp corporation plc gmbh ag sa srl bv fze fzco
dmcc llp lp public joint stock closed open limited liability aktsionernoe obshchestvo tov the""".split())


def bare(name: str) -> str:
    """'PUBLIC JOINT STOCK COMPANY SOVCOMFLOT', 'PAO Sovcomflot' → 'sovcomflot': the name without its legal form."""
    words = [w for w in sanctions.normalise(name).split() if w not in LEGAL_FORMS]
    return " ".join(words)


# ── one target, several entries ──
class _Union:
    def __init__(self, keys, actor_of: dict):
        self.up = {k: k for k in keys}
        self.actor = {k: actor_of.get(k) for k in keys}
        self.lists = {k: {k.split(":")[0]} for k in keys}

    def find(self, k):
        while self.up[k] != k:
            self.up[k] = self.up[self.up[k]]
            k = self.up[k]
        return k

    def join(self, a, b) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.actor[ra] and self.actor[rb] and self.actor[ra] != self.actor[rb]:
            return False                  # two different actors: not one target
        if self.lists[ra] & self.lists[rb]:
            return False                  # one entry per list: two entries sharing an alias ("Yasa Part") stay two targets
        self.up[rb] = ra
        self.actor[ra] = self.actor[ra] or self.actor[rb]
        self.lists[ra] |= self.lists[rb]
        return True


def _words(names: list[str]) -> set[str]:
    return {w for n in names for w in sanctions.normalise(n).split() if len(w) >= 3}


def _key(name: str) -> str:
    return " ".join(sorted(sanctions.normalise(name).split()))


def clusters(entries: dict[str, dict], actor_of: dict[str, str]) -> tuple[dict[str, str], dict[str, list]]:
    """entries {"US:36": entry with details} → ({entry: its cluster's first entry}, {cluster: [reasons]})."""
    u = _Union(entries, actor_of)
    why: dict[str, list] = {}

    def join(a, b, reason):
        if u.join(a, b):
            why.setdefault(a, []).append([b, reason])

    un = {k.split(":", 1)[1]: k for k in entries if k.startswith("UN:")}
    for k, e in entries.items():          # 1. the list itself says so
        ref = e["details"]["un"]
        if ref and ref in un and not k.startswith("UN:"):
            join(un[ref], k, f"the {k.split(':')[0]} entry gives the UN reference {ref}")
    seen: dict[tuple, str] = {}           # 2. the same number
    for k, e in entries.items():
        for kind, n, _ in e["details"]["ids"]:
            if kind not in STRONG:
                continue
            other = seen.setdefault((kind, n), k)
            if other != k and (kind == "imo" or _words(e["names"]) & _words(entries[other]["names"])):
                join(other, k, f"same IMO number {n}" if kind == "imo" else f"same {kind.replace('-', ' ')} number {n}")
    by_name: dict[tuple, list] = {}       # 3. the same name (and, for people, date of birth)
    for k, e in entries.items():
        lst = k.split(":")[0]
        for nm in e["names"]:
            key = _key(nm)
            words = key.split()
            if len(words) < 2 or len(key) < 8 or actors.is_generic(tuple(words)):
                continue
            by_name.setdefault((e["type"], key), [])
            if (lst, k) not in by_name[(e["type"], key)]:
                by_name[(e["type"], key)].append((lst, k))
    for (typ, key), found in by_name.items():
        per_list: dict[str, list] = {}
        for lst, k in found:
            per_list.setdefault(lst, []).append(k)
        if len(per_list) < 2:
            continue
        if typ == "person":
            for i, (l1, a) in enumerate(found):
                for l2, b in found[i + 1:]:
                    if l1 == l2:
                        continue
                    da, db = entries[a]["details"]["dob"], entries[b]["details"]["dob"]
                    full_a, full_b = {x for x in da if len(x) == 10}, {x for x in db if len(x) == 10}
                    same = sorted(full_a & full_b) if full_a and full_b else \
                        sorted({x[:4] for x in da} & {x[:4] for x in db}) if len(key.split()) >= 3 else []   # a year: three-word names only
                    if same:
                        join(a, b, f"same name and date of birth {same[0]}")
        elif all(len(v) == 1 for v in per_list.values()):
            first = next(iter(per_list.values()))[0]
            for v in list(per_list.values())[1:]:
                join(first, v[0], "same name on both lists")
    root = {k: u.find(k) for k in entries}
    reasons: dict[str, list] = {}
    for a, items in why.items():
        for b, reason in items:
            reasons.setdefault(root[a], []).append([a, b, reason])
    return root, reasons


def detail_nodes(entries: dict[str, dict], node_of: dict[str, str]) -> list[tuple]:
    """Details two different targets share → (node id, kind, label, [(entry, relation)])."""
    found: dict[tuple, dict] = {}
    for k, e in entries.items():
        d = e["details"]
        items = [("address", f"{a['street']}, {a['city']}".strip(", "), "registered at", _key(a["street"] + " " + a["city"]))
                 for a in d["addresses"]]
        items += [("email", x, "uses the e-mail address", x) for x in d["emails"]]
        items += [("website", x, "uses the website", x) for x in d["webs"]]
        items += [("phone", "+" + x, "uses the telephone number", x) for x in d["phones"]]
        items += [("wallet", x, "uses the crypto wallet", x) for x in d["wallets"]]
        for kind, label, rel, key in items:
            f = found.setdefault((kind, key), {"label": label, "entries": {}})
            f["entries"].setdefault(k, rel)
    out = []
    for (kind, key), f in found.items():
        if len({node_of[k] for k in f["entries"]}) < 2:
            continue                      # given by one target only: a detail, not a connection
        nid = f"{kind}:{hashlib.sha1(key.encode()).hexdigest()[:12]}"
        out.append((nid, kind, f["label"], sorted(f["entries"].items())))
    return out
