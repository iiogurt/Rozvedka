"""Wanted notices of the FBI and of Europe's Most Wanted (ENFAST, supported by Europol) – official sources on people.

The sanctions lists name the people a government has designated; wanted notices name the people it has charged: GRU and FSB
officers, ransomware developers, Iranian and Chinese state hackers, terrorists, members of criminal organisations – with
their aliases and handles, dates of birth, the charges, and a text that names the unit they serve in, the group they belong
to and the people charged with them. Only notices about security are kept: the FBI's cyber, counter-intelligence, China,
Iran, terrorism, transnational repression and criminal-enterprise notices, and the European notices for terrorism, criminal
organisations, computer crime, trafficking in drugs, weapons or people and money laundering. Never victims, missing persons
or notices about other crimes, and no photographs or physical descriptions.

A notice is an entry like a list entry (rozvedka/identity.py): it is merged with the same person's sanctions entry when the
name and the full date of birth agree. Its text is read for the actors, list entries and other wanted people it names
(layer "wanted", rozvedka/ties.py). A notice about several people at once ("APT 41 GROUP", "GRU 29155 CYBER ACTORS") is a
case of its own that links them.

    python -m rozvedka fetch-wanted       # network: the FBI's notices (API) and Europe's Most Wanted (a few minutes)

Rewards for Justice is not read: its robots.txt allows only search engines.
"""
import datetime as dt
import html
import json
import logging
import re
from html.parser import HTMLParser

from . import actors, fetch, identity, sanctions
from .config import DATA

log = logging.getLogger("rozvedka.wanted")
FILE = DATA / "gazetteer" / "wanted.json"
SOURCES = {
    "FBI": {"name": "FBI Wanted", "issuer": "Federal Bureau of Investigation (US)", "page": "https://www.fbi.gov/wanted",
            "api": "https://api.fbi.gov/wanted/v1/list"},
    "EUMW": {"name": "Europe's Most Wanted", "issuer": "ENFAST teams of the EU member states, supported by Europol",
             "page": "https://eumostwanted.eu/"},
}
FBI_SUBJECTS = {"Cyber's Most Wanted", "Counterintelligence", "China Threat", "Iran", "Most Wanted Terrorists",
                "Seeking Information - Terrorism", "Domestic Terrorism", "Transnational Repression",
                "Criminal Enterprise Investigations"}
EU_CRIMES = re.compile(r"terroris|criminal organisation|computer|narcotic|weapons|trafficking in human|smuggling of migrants"
                       r"|laundering|racketeering|sabotage|espionage", re.I)
# a notice about several people or an operation, not about one person
CASE_WORDS = {"group", "actors", "members", "hackers", "hacking", "interference", "conspiracy", "activities", "attacks",
              "workers", "elections", "election", "institute", "operation", "subjects", "suspects", "kidnappers", "fraud"}
PAGE = 50
# the agencies that investigate: "investigated by the FBI and the DEA" is no link between a fugitive and them (Wikidata ids)
INVESTIGATORS = {"Q8333", "Q622899"}


def _plain(h: str | None) -> str:
    """HTML of a notice → text, paragraphs on their own lines."""
    s = re.sub(r"</p>|<br\s*/?>", "\n", h or "", flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    return "\n".join(" ".join(line.split()) for line in s.splitlines() if line.strip())


def _name(title: str) -> str:
    """'MARY CAROLE MCDONNELL' → 'Mary Carole Mcdonnell'; 'Wang, Hongwei' → 'Wang Hongwei'; mixed case is kept."""
    t = " ".join(title.replace(",", " ").split())
    return t.title() if t.isupper() else t


def is_case(title: str, dob: list) -> bool:
    words = {w.casefold() for w in re.findall(r"\w+", title)}
    return not dob and bool(words & CASE_WORDS or any(w.isdigit() for w in words))


# ── FBI ──
def _fbi() -> list[dict]:
    out, page, total = [], 1, None
    while total is None or (page - 1) * PAGE < total:
        r = fetch.get(f"{SOURCES['FBI']['api']}?pageSize={PAGE}&page={page}")
        d = json.loads(r.text)
        total = d.get("total", 0)
        if not d.get("items"):
            break
        for i in d["items"]:
            subjects = [s for s in (i.get("subjects") or []) if s]
            if not set(subjects) & FBI_SUBJECTS or i.get("person_classification") == "Victim" \
                    or i.get("poster_classification") == "missing":
                continue
            dob = [identity.dob(x) for x in (i.get("dates_of_birth_used") or [])]
            text = "\n".join(_plain(i.get(k)) for k in ("caution", "details", "remarks", "additional_information") if i.get(k))
            out.append({"source": "FBI", "ref": i["uid"], "title": i["title"], "name": _name(i["title"]),
                        "aliases": [a.strip().strip('"“”') for a in (i.get("aliases") or []) if a and a.strip()],
                        "dob": sorted({x for x in dob if x}), "nationality": i.get("nationality") or "",
                        "subjects": subjects, "charges": i.get("description") or "", "text": text, "url": i["url"],
                        "published": (i.get("publication") or "")[:10], "modified": (i.get("modified") or "")[:10],
                        "case": is_case(i["title"], dob)})
        log.info("FBI wanted: page %d, %d of %d notices kept", page, len(out), total)
        page += 1
    return out


# ── Europe's Most Wanted ──
class _Fields(HTMLParser):
    """Text of each `field--name-…` block of a Drupal page, and the rows of its list view."""

    def __init__(self):
        super().__init__()
        self.fields: dict[str, list[str]] = {}
        self.stack: list[str | None] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("br", "img", "input", "meta", "link", "hr", "source"):
            return
        cls = dict(attrs).get("class") or ""
        m = re.search(r"\b(?:field--name|views-field)-([\w-]+)", cls)
        self.stack.append(m.group(1) if m else None)
        if tag == "p":
            self._add("\n")

    def handle_endtag(self, tag):
        if tag in ("br", "img", "input", "meta", "link", "hr", "source"):
            return
        if self.stack:
            self.stack.pop()

    def _add(self, text):
        name = next((s for s in reversed(self.stack) if s), None)
        if name:
            self.fields.setdefault(name, []).append(text)

    def handle_data(self, data):
        self._add(data)

    def get(self, name: str) -> str:
        return "".join(self.fields.get(name, [])).strip()


def _field_values(p: _Fields, name: str, label: str) -> list[str]:
    """'Crime Illicit trafficking … Laundering …' → the values without the label (the page puts each in its own div)."""
    raw = p.get(name)
    raw = raw[len(label):] if raw.startswith(label) else raw
    return [" ".join(v.split()) for v in raw.split("\n") if v.strip()]


def _eumw() -> list[dict]:
    home = fetch.get(SOURCES["EUMW"]["page"])
    rows = []
    for chunk in home.text.split('<div class="views-row">')[1:]:
        p = _Fields()
        p.feed(chunk)
        rows.append({"path": p.get("view-node"), "nid": p.get("nid"), "crime": p.get("field-crime"),
                     "status": p.get("field-status")})
    out = []
    for r in rows:
        if not r["path"].startswith("/") or r["status"] != "Wanted" or not EU_CRIMES.search(r["crime"]):
            continue
        url = SOURCES["EUMW"]["page"].rstrip("/") + r["path"]
        p = _Fields()
        p.feed(fetch.get(url).text)
        title = " ".join(p.get("field-w-first-name").split())         # "MOINI, Armin"
        last, _, first = title.partition(",")
        dates = [identity.dob(x) for x in re.findall(r"(?:published|modified)\s+on\s+([A-Za-z]+ \d+,\s+\d{4})", p.get("field-w-last-name"))]
        born = _field_values(p, "field-date-of-birth", "Date of birth")
        aliases = [re.sub(r"\s+geb\..*", "", a).strip() for v in _field_values(p, "field-alias", "Alias")
                   for a in re.split(r"[;,]", v)]          # "BABIC Josip geb. 06.02.1979 in Deutschland; GOJKOVIC …"
        aliases = [a for a in aliases if a and a.casefold() not in ("alias", "und weitere", "and others")]
        out.append({"source": "EUMW", "ref": r["nid"], "title": title,
                    "name": " ".join(x for x in (_name(first.strip()), _name(last.strip())) if x),
                    "aliases": aliases,
                    "dob": sorted({identity.dob(x) for x in born if identity.dob(x)}),
                    "nationality": ", ".join(_field_values(p, "field-nationality", "Nationality")),
                    "subjects": ["Wanted " + " ".join(p.get("field-enfast-country").split())] if p.get("field-enfast-country") else [],
                    "charges": "; ".join(_field_values(p, "field-crime", "Crime")),
                    "text": "\n".join(" ".join(x.split()) for x in p.get("body").split("\n") if x.strip()), "url": url,
                    "published": dates[0] if dates else "", "modified": dates[-1] if dates else "", "case": False})
        log.info("Europe's Most Wanted: %d notices kept", len(out))
    return out


def fetch_all() -> dict:
    notices, errors = [], {}
    for src, fn in (("FBI", _fbi), ("EUMW", _eumw)):
        try:
            notices += fn()
        except Exception as e:  # noqa: BLE001 - one source down must not lose the other
            log.warning("%s: %s", src, e)
            errors[src] = str(e)[:300]
    if errors and FILE.exists():           # keep what the failed source gave last time
        old = stored()
        notices += [n for n in old["notices"] if n["source"] in errors]
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps({"meta": {"retrieved": dt.date.today().isoformat(), "errors": errors,
                                         "sources": SOURCES},
                                "notices": notices}, ensure_ascii=False), encoding="utf-8")
    by = {}
    for n in notices:
        by[n["source"]] = by.get(n["source"], 0) + 1
    return {"notices": len(notices), "by_source": by, "cases": sum(n["case"] for n in notices), "errors": errors}


def stored() -> dict:
    return json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {"meta": None, "notices": []}


# ── as list entries (rozvedka/identity.py, rozvedka/ties.py) ──
def entries() -> dict[str, dict]:
    """"FBI:<uid>" → an entry shaped like a sanctions-list entry; notices about several people are left out (cases)."""
    out = {}
    for n in stored()["notices"]:
        if n["case"]:
            continue
        names = [n["name"]] + [a for a in n["aliases"] if a and sanctions.normalise(a) != sanctions.normalise(n["name"])]
        d = {"dob": n["dob"], "ids": [], "addresses": [], "emails": [], "webs": [], "phones": [], "wallets": [], "un": "",
             "parents": [], "subsidiaries": [], "owners": []}
        out[f"{n['source']}:{n['ref']}"] = {"ref": n["ref"], "type": "person", "shape": "Individual", "name": n["name"],
                                            "names": names, "primary": 1, "date": n["published"],
                                            "programme": "; ".join(n["subjects"]), "legal": "", "url": n["url"],
                                            "text": n["text"], "linked": [], "details": d, "notice": n}
    return out


def cases() -> list[dict]:
    return [n for n in stored()["notices"] if n["case"]]


# ── what a notice's sentence says about what it names ──
RELATIONS = {   # relation → words; which are checked, and in which order, depends on what is named (relation() below)
    "family": r"\b(?:uncle|aunt|nephew|niece|brother|sister|son|daughter|father|mother|wife|husband|cousin|relatives?|"
              r"(?:brother|son|father|daughter|sister)-in-law)\b",
    "associate": r"\bassociates?\b|\baides?\b|\bdeputy\b|\bbodyguards?\b|\bsecurity detail\b|\blieutenants?\b|\bright-hand\b"
                 r"|\bcouriers?\b|\bfinancier",
    "victim": r"\babduct|\bkidnap|\bmurder|\bkilling of\b|\bdeath of\b|\bvictims?\b|\bassassinat",
    "charged together": r"\bco-?conspirators?\b|\bco-?defendants?\b|\bconspir|\bcharged\b|\bindict|\btogether with\b"
                        r"|\balong with\b|\bare wanted\b|\bwere wanted\b|\binvolvement\b",
    "member or officer": r"\bofficers?\b|\bassigned\b|\bmembers?\b|\bemploy(?:ed|ee|ees)\b|\bwork(?:ed|s|ing)? (?:for|at)\b"
                         r"|\bon behalf of\b|\bat the behest of\b|\bagents? of\b|\bpart of\b|\bleaders?\b|\bhead of\b"
                         r"|\bcommanders?\b|\bcontractors?\b|\baffiliat|\boperatives?\b|\bfounder\b|\bco-?founded\b|\bsenior\b"
                         r"|\bassociates?\b|\bbanner\b|\boversaw\b|\bsupervis|\bconduct the affairs of\b",
    "support or funding": r"\bfund(?:er|ers|ed|ing)\b|\bfinanc|\bmaterial support\b|\bprovid(?:ed|ing) support\b|\bto benefit\b"
                          r"|\bfor the benefit of\b",
    "target": r"\btarget|\battack(?:s|ed|ing)? (?:on|against)\b|\bvictims?\b|\bcompromis|\bhack(?:ed|ing) into\b"
              r"|\bintrusions? into\b|\bkill|\bmurder|\bkidnap|\bstole\b|\bsteal|\bextort",
}
# words, not names: "son" and "Son Un Chol" (a Korean surname) – family words count only in lowercase
_REL = {name: re.compile(rx) if name == "family" else re.compile(rx, re.I) for name, rx in RELATIONS.items()}
# another person named with the wanted one is family, an associate, a victim or charged with them – not a fellow "member";
# a unit, group or company first of all employs them, funds or is funded, or is their target
ORDER = {True: ("family", "associate", "victim", "charged together"),
         False: ("member or officer", "support or funding", "target")}


NEAR = 100        # characters around the name in which the word must stand; a victim's word before the name


def _position(sentence: str, name: str) -> tuple[int, int] | None:
    """Where the sentence writes a name found in its normalised form ("alexey valerevich minin" → "Alexey Valerevich Minin")."""
    words = [re.escape(w) for w in name.split()]
    m = re.search(r"\W+".join(words), sentence, re.I) if words else None
    return (m.start(), m.end()) if m else None


def relation(sentence: str, person: bool, name: str = "") -> tuple[str, str]:
    """(relation, the word that decided it) – or ('', '') where no word near the name says."""
    at = _position(sentence, name) if name else None
    for rel in ORDER[person]:
        if at:
            lo = max(0, at[0] - NEAR)
            window = sentence[lo:at[0]] if rel == "victim" else sentence[lo:at[1] + NEAR]
        else:
            window = sentence
        m = _REL[rel].search(window)
        if m:
            if rel == "member or officer" and _REL["target"].search(window[max(0, m.start() - 40):m.start()]):
                return "target", m.group(0).lower()        # "targeting current and former members of …"
            return rel, m.group(0).lower()
    return "", ""


def case_label(title: str) -> str:
    """'GRU 29155 CYBER ACTORS' → 'GRU 29155 Cyber Actors' (abbreviations kept)."""
    keep = {"GRU", "APT", "IRGC", "DPRK", "PLA", "DDOS", "IT", "U.S.", "US", "FSB", "SVR", "MSS"}
    return " ".join(w if w.upper() in keep or any(c.isdigit() for c in w) else w.capitalize() for w in title.split())


TRADE = re.compile(r"hack|intelligence|officer|terror|militant|cyber|spy|espionage|\bGRU\b|\bFSB\b|IRGC|cartel|drug|traffick"
                   r"|criminal|mafia|crime|programmer|military|jihad|fugitive|ransomware|malware|computer", re.I)


def actor_of(entries: dict[str, dict], actor_rows: dict[str, dict]) -> dict[str, str]:
    """Notice → the person actor of the gazetteer it is about: the same full name (an alias counts), on one actor only, and –
    for a two-word name, which many people share – a description of the actor that speaks of the notice's world (a hacker,
    an officer, a cartel)."""
    by: dict[str, set] = {}
    for key, a in actor_rows.items():
        if a["kind"] != "person":
            continue
        for n in json.loads(a.get("data") or "{}").get("names", []):
            nn = sanctions.normalise(n["name"])
            if len(nn.split()) >= 2:
                by.setdefault(nn, set()).add(key)
    out = {}
    for k, e in entries.items():
        found = {}                                   # actor → the longest name it was found by
        for nm in e["names"]:
            nn = sanctions.normalise(nm)
            if len(nn.split()) < 2 or nn.split()[0] in actors.ARTICLES:
                continue                             # "El Señor": a title many are given, not a name
            for key in by.get(nn, ()):
                if len(nn.split()) > len(found.get(key, "").split()):
                    found[key] = nn
        if len(found) != 1:
            continue
        key, nn = next(iter(found.items()))
        desc = json.loads(actor_rows[key].get("data") or "{}").get("description") or ""
        if len(nn.split()) >= 3 or TRADE.search(desc):
            out[k] = key
    return out
