"""Ratings of states over time – democracy, security and governance: the context in which a state's reports were written.

A report from 2015 reads differently if its state was a liberal democracy then and an electoral autocracy now. Three
independent measurements, each with its own method, are kept per country and year:
  - V-Dem Liberal Democracy Index (0–1) and Regimes of the World category – V-Dem Institute (CC BY-SA 4.0), as
    republished by Our World in Data (the V-Dem download itself requires a registration form);
  - Freedom House, Freedom in the World total score (0–100) – Freedom House (non-commercial use with attribution),
    as republished by Our World in Data;
  - World Bank Worldwide Governance Indicators, Voice and Accountability (about −2.5 to +2.5) – World Bank (CC BY 4.0),
    from the World Bank API.
V-Dem and Freedom House also publish reports in this library (think tanks); the World Bank measure is the official,
intergovernmental third view. The EIU Democracy Index is a commercial product and is not used.

Security and governance (since 0.70.0, roadmap H3a): the other five World Bank governance indicators (political
stability and absence of violence/terrorism, rule of law, control of corruption, government effectiveness, regulatory
quality), intentional homicides (UNODC), military expenditure (SIPRI) and the Corruption Perceptions Index
(Transparency International, CC BY-ND – shown unaltered), the last three as republished by Our World in Data. Each
measure keeps its own scale, source and direction (`better`: which end is the safer or better one; none for military
spending, which is context, not a grade) – there is no composite score.

Disaster risk (0.80.0): INFORM Risk Index and WorldRiskIndex. Media and cyber (0.81.0, roadmap H3d): RSF's World
Press Freedom Index since its 2022 method (kept in this library only – RSF's terms ask for permission to reproduce) and
the ITU Global Cybersecurity Index 2024 tiers, read from the annex of the report's PDF. The National Cyber Security
Index is not used: its terms prohibit reproduction.

`fetch-ratings` stores everything in data/ratings/ratings.json with the retrieval date and each source's citation."""
import csv
import datetime as dt
import io
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

from . import countries, db
from .config import DATA

log = logging.getLogger("rozvedka.ratings")

STORE = DATA / "ratings" / "ratings.json"
UA = "Rozvedka/0.x (personal research library; https://github.com/iiogurt/Rozvedka)"
OWID = "https://ourworldindata.org/grapher/{slug}"
WB_API = "https://api.worldbank.org/v2"
REGIMES = {0: "closed autocracy", 1: "electoral autocracy", 2: "electoral democracy", 3: "liberal democracy"}

MEASURES = {
    "vdem_libdem": {"name": "Liberal Democracy Index", "group": "democracy", "better": "high", "by": "V-Dem", "short": "V-Dem LDI", "scale": (0, 1), "fmt": "{:.2f}",
                    "slug": "liberal-democracy-index", "column": "libdem_vdem__estimate_best",
                    "license": "CC BY-SA 4.0", "home": "https://www.v-dem.net/",
                    "about": "Expert-coded extent of liberal democracy: free and fair elections, freedoms of association "
                             "and expression, civil liberties, rule of law, constraints on the executive (0 = none, 1 = full)."},
    "vdem_regime": {"name": "Regimes of the World", "group": "democracy", "better": "high", "by": "V-Dem", "short": "V-Dem RoW", "scale": (0, 3), "fmt": "{}",
                    "slug": "political-regime", "column": "regime_row_owid", "license": "CC BY-SA 4.0",
                    "home": "https://www.v-dem.net/",
                    "about": "Classification from V-Dem data: closed autocracy, electoral autocracy, electoral democracy, "
                             "liberal democracy (Lührmann, Tannenberg & Lindberg 2018)."},
    "fh_score": {"name": "Freedom in the World score", "group": "democracy", "better": "high", "by": "Freedom House", "short": "FH", "scale": (0, 100), "fmt": "{:.0f}",
                 "slug": "freedom-score-fh", "column": "total_score",
                 "license": "Freedom House content: non-commercial use with attribution",
                 "home": "https://freedomhouse.org/report/freedom-world",
                 "about": "Political rights (0–40) and civil liberties (0–60) assessed by analysts; 100 = most free."},
    "wgi_va": {"name": "Voice and Accountability", "group": "democracy", "better": "high", "by": "World Bank (WGI)", "short": "WGI VA", "scale": (-2.5, 2.5), "fmt": "{:+.2f}",
               "indicator": "GOV_WGI_VA.EST", "license": "CC BY 4.0", "home": "https://www.worldbank.org/en/publication/worldwide-governance-indicators",
               "about": "Perceptions of citizens' ability to choose their government, freedom of expression and "
                        "association, and a free media; standard units, about −2.5 to +2.5."},
    # ── security ──
    "wgi_pv": {"group": "security", "better": "high", "name": "Political Stability and Absence of Violence/Terrorism",
               "by": "World Bank (WGI)", "short": "WGI PV", "scale": (-2.5, 2.5), "fmt": "{:+.2f}", "topic": "terrorism",
               "indicator": "GOV_WGI_PV.EST", "license": "CC BY 4.0", "home": "https://www.worldbank.org/en/publication/worldwide-governance-indicators",
               "about": "Perceptions of the likelihood of political instability and politically motivated violence, "
                        "including terrorism; standard units, about −2.5 to +2.5."},
    "homicide": {"group": "security", "better": "low", "name": "Intentional homicides per 100,000", "by": "UNODC",
                 "short": "Homicides", "scale": (0, 10), "fmt": "{:.1f}", "topic": "organised-crime",
                 "slug": "homicide-rate-unodc",
                 "column": "value__category_total__sex_total__age_total__unit_of_measurement_rate_per_100_000_population",
                 "license": "UNODC data as republished by Our World in Data", "home": "https://dataunodc.un.org/",
                 "about": "Unlawful deaths intentionally inflicted on a person, per 100,000 inhabitants, from police and "
                          "public-health records; the colour scale saturates at 10."},
    "milex": {"group": "security", "better": None, "name": "Military expenditure, % of GDP", "by": "SIPRI",
              "short": "Military %GDP", "scale": (0, 5), "fmt": "{:.1f} %", "topic": "military-threat",
              "slug": "military-spending-as-a-share-of-gdp-sipri", "column": "share_gdp",
              "license": "SIPRI data as republished by Our World in Data", "home": "https://www.sipri.org/databases/milex",
              "about": "Military spending as a share of gross domestic product (SIPRI definition, which can differ from "
                       "NATO's and national budgets). Context, not a grade: neither end is better; the colour scale "
                       "saturates at 5 %."},
    "ucdp_deaths": {"group": "security", "better": "low", "name": "Deaths in organised violence per 100,000", "by": "UCDP",
                    "short": "Conflict deaths", "scale": (0, 10), "fmt": "{:.2f}", "topic": "military-threat", "derived": "ucdp",
                    "license": "CC BY 4.0", "home": "https://ucdp.uu.se/",
                    "about": "Deaths in state-based and non-state conflict and one-sided violence in the state, per year and "
                             "100,000 inhabitants (UCDP Georeferenced Event Dataset, best estimates; population: World Bank). "
                             "No recorded death counts as 0. The colour scale saturates at 10."},
    # ── governance ──
    "wgi_rl": {"group": "governance", "better": "high", "name": "Rule of Law", "by": "World Bank (WGI)", "short": "WGI RL",
               "scale": (-2.5, 2.5), "fmt": "{:+.2f}", "indicator": "GOV_WGI_RL.EST", "license": "CC BY 4.0",
               "home": "https://www.worldbank.org/en/publication/worldwide-governance-indicators",
               "about": "Perceptions of confidence in and abiding by the rules of society: contract enforcement, "
                        "property rights, the police and the courts, and the likelihood of crime and violence."},
    "wgi_cc": {"group": "governance", "better": "high", "name": "Control of Corruption", "by": "World Bank (WGI)",
               "short": "WGI CC", "scale": (-2.5, 2.5), "fmt": "{:+.2f}", "topic": "money-laundering-corruption",
               "indicator": "GOV_WGI_CC.EST", "license": "CC BY 4.0",
               "home": "https://www.worldbank.org/en/publication/worldwide-governance-indicators",
               "about": "Perceptions of the extent to which public power is exercised for private gain, including "
                        "petty and grand corruption and the capture of the state by elites."},
    "wgi_ge": {"group": "governance", "better": "high", "name": "Government Effectiveness", "by": "World Bank (WGI)",
               "short": "WGI GE", "scale": (-2.5, 2.5), "fmt": "{:+.2f}", "indicator": "GOV_WGI_GE.EST", "license": "CC BY 4.0",
               "home": "https://www.worldbank.org/en/publication/worldwide-governance-indicators",
               "about": "Perceptions of the quality of public services and the civil service, its independence from "
                        "political pressure, and the credibility of the government's policies."},
    "wgi_rq": {"group": "governance", "better": "high", "name": "Regulatory Quality", "by": "World Bank (WGI)",
               "short": "WGI RQ", "scale": (-2.5, 2.5), "fmt": "{:+.2f}", "indicator": "GOV_WGI_RQ.EST", "license": "CC BY 4.0",
               "home": "https://www.worldbank.org/en/publication/worldwide-governance-indicators",
               "about": "Perceptions of the government's ability to formulate and implement sound policies and "
                        "regulations that permit and promote private-sector development."},
    "cpi": {"group": "governance", "better": "high", "name": "Corruption Perceptions Index", "by": "Transparency International",
            "short": "CPI", "scale": (0, 100), "fmt": "{:.0f}", "topic": "money-laundering-corruption",
            "slug": "ti-corruption-perception-index", "column": "cpi_score",
            "license": "CC BY-ND 4.0 (shown unaltered)", "home": "https://www.transparency.org/en/cpi",
            "about": "Perceived corruption in the public sector, from 13 expert and business surveys; "
                     "0 = highly corrupt, 100 = very clean."},
    # ── disaster risk ──
    "inform_risk": {"group": "disaster", "better": "low", "name": "INFORM Risk Index", "by": "EU JRC (INFORM)", "short": "INFORM",
                    "scale": (0, 10), "fmt": "{:.1f}", "topic": "crisis-management", "inform": "INFORM2026",
                    "license": "European Commission data – reuse with acknowledgement (Commission Decision 2011/833/EU)",
                    "home": "https://drmkc.jrc.ec.europa.eu/inform-index",
                    "about": "Risk of humanitarian crises and disasters that would overwhelm national capacity: hazard and "
                             "exposure, vulnerability, lack of coping capacity; 0–10, higher = more risk. One release "
                             "(INFORM Risk 2026) with every year recomputed by the same method, from the INFORM API; "
                             "the year shown is the year of the data (INFORM Risk 2026 = data of 2025)."},
    "world_risk": {"group": "disaster", "better": "low", "name": "WorldRiskIndex", "by": "Bündnis Entwicklung Hilft / IFHV",
                   "short": "WorldRiskIndex", "scale": (0, 40), "fmt": "{:.1f}", "topic": "floods-storms",
                   "csv": "https://data.humdata.org/dataset/1efb6ee7-051a-440f-a2cf-e652fecccf73/resource/3a2320fa-41b4-4dda-a847-3f397d865378/download/worldriskindex-trend.csv",
                   "csv_cols": ("ISO3.Code", "Year", "W"), "license": "CC BY (Humanitarian Data Exchange)",
                   "home": "https://weltrisikobericht.de/en/",
                   "about": "Disaster risk from extreme natural events: exposure combined with vulnerability (susceptibility, "
                            "lack of coping and of adaptive capacity); higher = more risk. The colour scale saturates at 40."},
    # ── media ──
    "rsf": {"group": "media", "better": "high", "name": "World Press Freedom Index", "by": "Reporters Without Borders (RSF)",
            "short": "RSF", "scale": (0, 100), "fmt": "{:.1f}", "topic": "disinformation", "rsf": True,
            "license": "© RSF – kept in this library only, not redistributed (RSF's terms ask for permission to reproduce)",
            "home": "https://rsf.org/en/index",
            "about": "Press freedom from political, economic, legal, social and safety indicators; 0–100, higher = freer. "
                     "Only the editions since 2022: RSF changed its method then and earlier scores are not comparable. "
                     "The year is the edition's (the 2026 index describes 2025)."},
    # ── cyber ──
    "gci_tier": {"group": "cyber", "better": "low", "name": "Global Cybersecurity Index tier", "by": "ITU",
                 "short": "GCI tier", "scale": (1, 5), "fmt": "T{:.0f}", "topic": "state-cyber",
                 "gci": "https://www.itu.int/dms_pub/itu-d/opb/hdb/D-HDB-GCI.01-2024-PDF-E.pdf",
                 "license": "CC BY-NC-SA 3.0 IGO", "home": "https://www.itu.int/en/ITU-D/Cybersecurity/Pages/global-cybersecurity-index.aspx",
                 "about": "The state's legal, technical, organisational, capacity-building and cooperation measures for "
                          "cybersecurity, as the state reported and ITU checked them; five tiers – T1 role-modelling "
                          "(score 95–100), T2 advancing (85–95), T3 establishing (55–85), T4 evolving (20–55), "
                          "T5 building (0–20). One edition (GCI 2024, 5th) – earlier editions ranked by another method. "
                          "Read from the report's annex (pp. 24–25); Taiwan is not covered (ITU covers UN members)."},
    "cyber_incidents": {"group": "cyber", "better": None, "name": "Cyber incidents reported against the state", "by": "EuRepoC",
                        "short": "Cyber incidents", "scale": (0, 60), "fmt": "{:.0f}", "topic": "state-cyber", "derived": "eurepoc",
                        "license": "CC BY-NC 4.0", "home": "https://eurepoc.eu/",
                        "about": "Incidents that EuRepoC's Global Dataset of Cyber Incidents records with the state among their "
                                 "receivers, by the year they began. Context, not a grade: it counts what was reported and "
                                 "attributed, which depends on openness as much as on attacks. Each year opens its incidents."},
}
# the groups of /ratings, in order: (name, what it covers)
GROUPS = {"democracy": ("Democracy", "how free and democratic the state is"),
          "security": ("Security", "political violence and terrorism, homicides, military spending"),
          "governance": ("Governance", "rule of law, corruption, effectiveness and regulation"),
          "media": ("Media", "press freedom"),
          "cyber": ("Cyber", "cybersecurity commitment and cyber incidents reported against the state"),
          "disaster": ("Disaster risk", "risk of disasters and humanitarian crises")}


def of_group(group: str) -> dict[str, dict]:
    return {k: m for k, m in MEASURES.items() if m["group"] == group}


def _get(url: str, attempts: int = 3) -> bytes:
    """A download, tried again after a dropped connection or a timeout (10 s, then 20 s)."""
    import time
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except (OSError, urllib.error.URLError) as e:
            if attempt + 1 == attempts or (isinstance(e, urllib.error.HTTPError) and e.code < 500):   # an answer, not a dropped line
                raise
            log.warning("retry %s: %s", url[:90], e)
            time.sleep(10 * (attempt + 1))


@lru_cache(maxsize=1)
def _wb_countries() -> tuple:
    return tuple(json.loads(_get(f"{WB_API}/country?format=json&per_page=400"))[1])


def _iso3_map() -> dict[str, str]:
    """ISO 3166 alpha-2 → alpha-3 from the World Bank's official country list (Taiwan, absent there, by name)."""
    return {c["iso2Code"]: c["id"] for c in _wb_countries() if c.get("iso2Code")}


def _norm(name: str) -> str:
    import unicodedata
    name = unicodedata.normalize("NFKD", name.replace("’", "'")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]+", " ", name).strip()


# the ITU's spellings that neither the World Bank nor Our World in Data use
ITU_NAMES = {"Korea (Republic of)": "KOR", "Dem. People's Rep. of Korea": "PRK", "Congo (Rep. of the)": "COG",
             "Dem. Rep. of the Congo": "COD", "Lao P.D.R.": "LAO", "State of Palestine": "PSE", "Dominican Rep.": "DOM",
             "Central African Rep.": "CAF", "Micronesia": "FSM", "Vatican": "VAT", "Iran (Islamic Republic of)": "IRN",
             "Bolivia (Plurinational State of)": "BOL", "Russian Federation": "RUS", "Viet Nam": "VNM",
             "Türkiye": "TUR", "Czech Republic": "CZE", "Netherlands (Kingdom of the)": "NLD", "Nepal (Republic of)": "NPL"}
GCI_TIERS = {"Role-modelling": 1, "Advancing": 2, "Establishing": 3, "Evolving": 4, "Building": 5}


def parse_gci_tiers(text: str) -> dict[str, int]:
    """{country name: tier} from the GCI 2024 annex "Tier performance: Global" (pdftotext -layout): four columns of
    names under each tier's heading, a name that does not fit continued on the next line of its column ("Netherlands
    (Kingdom" / "of the)", "Saint Vincent and" / "the Grenadines")."""
    head = re.search(r"^Tier performance: Global\s*$", text, re.M)      # the heading, not its line in the contents
    if not head:
        raise ValueError("GCI annex not found")
    start = head.start()
    end = text.find("Tier Performance:", start + 10)
    tier, out = None, {}
    cols: dict[int, list[str]] = {}                   # column start → names in reading order, per tier and page

    def flush():
        for names in cols.values():
            for n in names:
                out[n] = tier
        cols.clear()

    for line in text[start:end if end > 0 else None].replace("\f", "\n<page>\n").split("\n"):
        head = re.match(r"\s*Tier (\d) – (\S+)", line)
        if head:
            flush()
            tier = int(head.group(1))
            if GCI_TIERS.get(head.group(2)) != tier:
                raise ValueError(f"unexpected tier heading: {line.strip()}")
            continue
        if line == "<page>":
            flush()                                    # a new page lays its columns out anew
            continue
        if tier is None or not line.strip() or re.fullmatch(r"\s*(\d+|\(continued\)|Global Cybersecurity Index 2024)\s*", line):
            continue
        for m in re.finditer(r"\S+(?: \S+)*", line):
            col = next((c for c in cols if abs(c - m.start()) <= 3), m.start())
            names = cols.setdefault(col, [])
            cell = m.group()
            prev = names[-1] if names else ""
            if prev and (prev.count("(") > prev.count(")") or re.search(r" (of|and)$", prev) or cell[0].islower()):
                names[-1] = f"{prev} {cell}"
            else:
                names.append(cell)
    flush()
    return out


def parse_rsf(raw: bytes) -> tuple[int | None, dict[str, float]]:
    """(edition year, {ISO3: score}) from one of RSF's yearly index files (semicolons, decimal commas; UTF-8 or
    Windows-1252, depending on the year)."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", "replace")
    rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))
    if not rows:
        return None, {}
    score_col = next(c for c in rows[0] if re.fullmatch(r"Score( \d{4})?", c.strip()))
    out, year = {}, None
    for r in rows:
        if r.get("ISO") and (r.get(score_col) or "").strip():
            out[r["ISO"].strip()] = float(r[score_col].replace(",", "."))
            year = year or int(r["Year (N)"])
    return year, out


def fetch(out: Path | None = None) -> dict:
    """Download every measure for every country and year; returns counts."""
    today = dt.date.today().isoformat()
    names = countries.names()
    iso3 = _iso3_map()
    store = {"retrieved": today, "measures": {}, "iso3": {}, "values": {}, "names": {}}
    owid_names: dict[str, str] = {}
    for key, m in MEASURES.items():
        if m.get("derived"):        # from the library's own event data (events.py), after the downloads
            continue
        if m.get("gci"):             # tiers read from the report's annex: names → alpha-3 by the official country lists
            import subprocess
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
                f.write(_get(m["gci"]))
                f.flush()
                text = subprocess.run(["pdftotext", "-q", "-layout", "-enc", "UTF-8", f.name, "-"],
                                      capture_output=True, timeout=300).stdout.decode("utf-8", "replace")
            lookup = {_norm(c["name"]): c["id"] for c in _wb_countries()}
            lookup.update({_norm(k): v for k, v in owid_names.items()})
            lookup.update({_norm(k): v for k, v in ITU_NAMES.items()})
            tiers, unmatched = parse_gci_tiers(text), []
            for name, t in tiers.items():
                a3 = lookup.get(_norm(name)) or lookup.get(_norm(re.sub(r"\(.*?\)", "", name)))
                if a3:
                    store["values"].setdefault(a3, {}).setdefault(key, {})["2024"] = float(t)
                else:
                    unmatched.append(name)
            if unmatched:
                log.warning("GCI names without a country code: %s", unmatched)
            store["measures"][key] = {"source": m["gci"], "unmatched": unmatched,
                                      "citation": "ITU, Global Cybersecurity Index 2024, 5th edition – annex "
                                                  "'Tier performance: Global', pp. 24–25",
                                      "retrieved": today, "rows": len(tiers) - len(unmatched)}
            continue
        if m.get("rsf"):             # one file per edition, since the 2022 method
            import time
            n, editions = 0, []
            for y in range(2022, dt.date.today().year + 1):
                time.sleep(2)
                try:
                    year, scores = parse_rsf(_get(f"https://rsf.org/sites/default/files/import_classement/{y}.csv"))
                except urllib.error.HTTPError as e:
                    if e.code == 404:        # this year's edition not out yet
                        continue
                    raise
                for a3, v in scores.items():
                    store["values"].setdefault(a3, {}).setdefault(key, {})[str(year or y)] = v
                    n += 1
                editions.append(year or y)
            store["measures"][key] = {"source": "https://rsf.org/en/index",
                                      "citation": f"Reporters Without Borders, World Press Freedom Index {min(editions)}–{max(editions)} (RSF's yearly data files)",
                                      "retrieved": today, "rows": n}
            continue
        if m.get("inform"):          # the INFORM API: the release's countries, then each country's trend (every year alike)
            import time
            api = "https://drmkc.jrc.ec.europa.eu/inform-index/API/InformAPI"
            flows = json.loads(_get(f"{api}/workflows/GetByWorkflowGroup/{m['inform']}"))
            latest = max((w for w in flows if " - " not in (w.get("Name") or "")), key=lambda w: w["WorkflowId"])
            n = 0
            for c in json.loads(_get(f"{api}/Countries/Scores/?WorkflowId={latest['WorkflowId']}&IndicatorId=INFORM")):
                if not c.get("Iso3"):
                    continue
                time.sleep(1)                # politely: one request per country
                for r in json.loads(_get(f"{api}/Countries/Trends/?workflowid={latest['WorkflowId']}&iso3={c['Iso3']}&indicatorid=INFORM")):
                    # (the answer also holds the sub-indices – hazard, vulnerability, coping capacity – of each year)
                    if r.get("IndicatorId") == "INFORM" and r.get("IndicatorScore") is not None and r.get("GNAYear"):
                        # the year of the data: INFORM Risk 2026 holds the data of 2025
                        store["values"].setdefault(c["Iso3"], {}).setdefault(key, {})[str(r["GNAYear"])] = float(r["IndicatorScore"])
                        n += 1
            store["measures"][key] = {"source": "https://drmkc.jrc.ec.europa.eu/inform-index/INFORM-Risk/Results-and-data",
                                      "citation": f"{latest['Name']} (INFORM API, every year recomputed alike), European Commission Joint Research Centre",
                                      "retrieved": today, "rows": n}
            continue
        if m.get("csv"):             # a CSV file: ISO3 code, year, value
            iso_c, year_c, val_c = m["csv_cols"]
            n = 0
            for r in csv.DictReader(io.StringIO(_get(m["csv"]).decode("utf-8-sig"))):
                if r.get(iso_c) and r.get(year_c) and r.get(val_c) not in (None, "", "NA"):
                    store["values"].setdefault(r[iso_c], {}).setdefault(key, {})[str(int(float(r[year_c])))] = float(r[val_c])
                    n += 1
            store["measures"][key] = {"source": "https://data.humdata.org/dataset/worldriskindex",
                                      "citation": "WorldRiskReport / WorldRiskIndex trend data, Bündnis Entwicklung Hilft and IFHV",
                                      "retrieved": today, "rows": n}
            continue
        if "slug" in m:
            url = OWID.format(slug=m["slug"]) + ".csv?v=1&csvType=full&useColumnShortNames=true"
            meta = json.loads(_get(OWID.format(slug=m["slug"]) + ".metadata.json"))
            rows = csv.DictReader(io.StringIO(_get(url).decode("utf-8")))
            n = 0
            for r in rows:
                code, value = r.get("code") or "", r.get(m["column"]) or ""
                if not code or code.startswith("OWID_") or value == "":
                    continue
                owid_names[r["entity"]] = code
                store["values"].setdefault(code, {}).setdefault(key, {})[r["year"]] = float(value)
                n += 1
            store["measures"][key] = {"source": OWID.format(slug=m["slug"]), "citation": meta["chart"].get("citation"),
                                      "retrieved": today, "rows": n}
        else:
            url = f"{WB_API}/country/all/indicator/{m['indicator']}?format=json&per_page=20000"
            data = json.loads(_get(url))
            n = 0
            for r in data[1] or []:
                if r["value"] is None or not r.get("countryiso3code"):
                    continue
                store["values"].setdefault(r["countryiso3code"], {}).setdefault(key, {})[r["date"]] = float(r["value"])
                n += 1
            store["measures"][key] = {"source": f"https://data.worldbank.org/indicator/{m['indicator']}",
                                      "citation": f"World Bank, Worldwide Governance Indicators ({data[0].get('lastupdated', '')})",
                                      "retrieved": today, "rows": n}
    pop = json.loads(_get(f"{WB_API}/country/all/indicator/SP.POP.TOTL?format=json&per_page=20000"))
    store["population"] = {}
    for r in pop[1] or []:
        if r["value"] and r.get("countryiso3code"):
            store["population"].setdefault(r["countryiso3code"], {})[r["date"]] = r["value"]
    store["iso2to3_all"] = {a2: a3 for a2, a3 in iso3.items()}
    event_measures(store, today)
    store["names"] = {code: name for name, code in owid_names.items()}      # alpha-3 → country name (any country)
    store["iso2to3"] = {a2: a3 for a2, a3 in iso3.items() if a3 in store["values"]}   # every country, for the map
    # library countries → alpha-3 (World Bank list; else the country's name as Our World in Data spells it)
    for code, name in names.items():
        a3 = iso3.get(code) or owid_names.get(name)
        if a3 and a3 in store["values"]:
            store["iso3"][code] = a3
    out = out or STORE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(store), encoding="utf-8")
    load.cache_clear()
    ranks.cache_clear()
    missing = sorted(c for c in names if c not in store["iso3"] and c not in ("EU", "NATO", "OTHER"))
    log.info("ratings: %s; library countries without ratings: %s", {k: v["rows"] for k, v in store["measures"].items()}, missing)
    return {"measures": {k: v["rows"] for k, v in store["measures"].items()}, "countries": len(store["iso3"]),
            "without_ratings": missing}


def event_measures(store: dict, today: str) -> dict:
    """The measures computed from the library's event data (events.py): UCDP deaths per year and 100,000 inhabitants
    (preliminary candidate months left out; a state with no recorded death has 0) and EuRepoC incidents per year with
    the state among their receivers. Written into `store`; returns the rows per measure."""
    from . import events
    rows = {"ucdp_deaths": 0, "cyber_incidents": 0}
    try:
        events.init()
        with db.session() as con:
            deaths, last = {}, 0
            for iso, month, n in con.execute("SELECT iso, month, deaths FROM event_months WHERE preliminary=0"):
                y = int(month[:4])
                deaths.setdefault(iso, {}).setdefault(y, 0)
                deaths[iso][y] += n
                last = max(last, y)
            incidents = {}
            for iso, y, n in con.execute("""SELECT c.iso, e.year, COUNT(*) FROM events e JOIN event_countries c ON c.event_key=e.key
                                            WHERE e.source='eurepoc' GROUP BY c.iso, e.year"""):
                incidents.setdefault(iso, {})[y] = n
            first_i = min((y for v in incidents.values() for y in v), default=None)
            last_i = max((y for v in incidents.values() for y in v), default=None)
    except Exception as e:  # noqa: BLE001 - no events fetched yet
        log.info("no event data for the ratings (%s) – run fetch-events", e)
        return rows
    for a2, a3 in (store.get("iso2to3_all") or {}).items():
        pop = store.get("population", {}).get(a3) or {}
        if pop and last:
            years = sorted(int(y) for y in pop)
            for y in range(2000, last + 1):
                p = pop.get(str(y)) or pop.get(str(max(yy for yy in years if yy <= y) if any(yy <= y for yy in years) else years[0]))
                if p:
                    store["values"].setdefault(a3, {}).setdefault("ucdp_deaths", {})[str(y)] = deaths.get(a2, {}).get(y, 0) / p * 1e5
                    rows["ucdp_deaths"] += 1
        if first_i:
            for y in range(first_i, last_i + 1):
                store["values"].setdefault(a3, {}).setdefault("cyber_incidents", {})[str(y)] = float(incidents.get(a2, {}).get(y, 0))
                rows["cyber_incidents"] += 1
    store["measures"]["ucdp_deaths"] = {"source": "https://ucdp.uu.se/downloads/", "retrieved": today, "rows": rows["ucdp_deaths"],
                                        "citation": "UCDP Georeferenced Event Dataset (via fetch-events); population: World Bank SP.POP.TOTL"}
    store["measures"]["cyber_incidents"] = {"source": "https://zenodo.org/records/14965395", "retrieved": today,
                                            "rows": rows["cyber_incidents"],
                                            "citation": "EuRepoC Global Dataset of Cyber Incidents 1.3 (via fetch-events)"}
    return rows


def refresh_event_measures() -> dict:
    """Recompute the event measures in the stored ratings (after fetch-events) without downloading the ratings again."""
    if not STORE.exists():
        return {}
    store = json.loads(STORE.read_text(encoding="utf-8"))
    if "iso2to3_all" not in store:
        return {}
    rows = event_measures(store, dt.date.today().isoformat())
    STORE.write_text(json.dumps(store), encoding="utf-8")
    load.cache_clear()
    ranks.cache_clear()
    return rows


@lru_cache(maxsize=1)
def load(path: Path | None = None) -> dict:
    p = path or STORE
    if not p.exists():
        return {"retrieved": None, "measures": {}, "iso3": {}, "values": {}, "names": {}, "iso2to3": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def series(country: str, key: str) -> dict[int, float]:
    """{year: value} of one measure for a library country (two-letter code); empty when not rated."""
    d = load()
    a3 = d["iso3"].get(country)
    return {int(y): v for y, v in sorted(d["values"].get(a3, {}).get(key, {}).items(), key=lambda kv: int(kv[0]))} if a3 else {}


def at(country: str, key: str, year: int | None) -> tuple[int, float] | None:
    """The value for a year, or the closest earlier year (ratings are published a year late); None if unrated."""
    s = series(country, key)
    if not s:
        return None
    if year is None:
        y = max(s)
        return y, s[y]
    earlier = [y for y in s if y <= year]
    if not earlier:
        return None
    y = max(earlier)
    return y, s[y]


@lru_cache(maxsize=64)
def ranks(key: str) -> dict[str, tuple[int, int]]:
    """{library country: (place, of how many)} by the latest value of a measure, the better end first (higher first
    for a measure without a better end, such as military spending – a position, not a grade). Ties share a place."""
    better = MEASURES[key]["better"]
    latest = {c: v[1] for c in load()["iso3"] if (v := at(c, key, None))}
    order = sorted(latest.values(), reverse=better != "low")
    return {c: (order.index(v) + 1, len(order)) for c, v in latest.items()}


def source_url(country: str, key: str) -> str:
    """Where a reader checks the value: the chart for that country, or the World Bank indicator page."""
    m = MEASURES[key]
    a3 = load()["iso3"].get(country, "")
    if m.get("inform"):
        return "https://drmkc.jrc.ec.europa.eu/inform-index/INFORM-Risk/Results-and-data"
    if m.get("csv"):
        return "https://data.humdata.org/dataset/worldriskindex"
    if m.get("gci"):
        return m["gci"] + "#page=34"
    if m.get("rsf"):
        return "https://rsf.org/en/index"
    if m.get("derived") == "eurepoc":
        return f"/events?source=eurepoc&country={country}"
    if m.get("derived") == "ucdp":
        return "https://ucdp.uu.se/downloads/"
    if "slug" in m:
        return OWID.format(slug=m["slug"]) + "?" + urllib.parse.urlencode({"tab": "chart", "country": a3})
    return f"https://data.worldbank.org/indicator/{m['indicator']}?locations={country}"


def profile(country: str, year: int | None = None) -> dict | None:
    """Every measure for a country: latest value, value in `year` (if given), the series since 1990, sources."""
    if not load()["iso3"].get(country):
        return None
    out = {"country": country, "retrieved": load()["retrieved"], "measures": {}}
    for key, m in MEASURES.items():
        s = series(country, key)
        if not s:
            continue
        latest, then = at(country, key, None), at(country, key, year) if year else None
        out["measures"][key] = {**m, "key": key, "latest": latest, "then": then,
                                "spark": [(y, v) for y, v in s.items() if y >= 1990],
                                "url": source_url(country, key), "citation": load()["measures"].get(key, {}).get("citation"),
                                "rank": ranks(key).get(country)}
    reg = out["measures"].get("vdem_regime")
    if reg:
        reg["latest_label"] = REGIMES.get(int(reg["latest"][1]))
        reg["then_label"] = REGIMES.get(int(reg["then"][1])) if reg.get("then") else None
        # the years in which the category changed – what to keep in mind reading older reports
        changes, prev = [], None
        for y, v in reg["spark"]:
            if prev is not None and int(v) != int(prev):
                changes.append({"year": y, "from": REGIMES[int(prev)], "to": REGIMES[int(v)]})
            prev = v
        reg["changes"] = changes
    return out


MAP_FROM = 1990


def map_data() -> dict:
    """Every country's measures per year since 1990, keyed by its two-letter code (as the map's country shapes are),
    with the sources – for the Democracy map, which changes years in the browser without asking again."""
    d = load()
    if not d.get("values"):
        return {"years": [], "countries": {}, "measures": {}, "regimes": REGIMES, "retrieved": None}
    last = max(int(y) for v in d["values"].values() for m in v.values() for y in m)
    years = list(range(MAP_FROM, last + 1))
    iso2to3 = {**d.get("iso2to3", {}), **d.get("iso3", {})}       # library countries win (e.g. Taiwan, by name)
    countries = {}
    for a2, a3 in iso2to3.items():
        vals = d["values"].get(a3, {})
        countries[a2] = {"iso3": a3, "name": d.get("names", {}).get(a3, a2), "library": a2 in d.get("iso3", {}),
                         "values": {k: [vals.get(k, {}).get(str(y)) for y in years] for k in MEASURES}}
    measures = {k: {**{f: m[f] for f in ("name", "by", "short", "scale", "license", "about", "home", "group", "better", "fmt")},
                    "citation": d["measures"].get(k, {}).get("citation"), "source": d["measures"].get(k, {}).get("source")}
                for k, m in MEASURES.items()}
    return {"years": years, "countries": countries, "measures": measures, "regimes": REGIMES, "retrieved": d["retrieved"],
            "groups": {g: name for g, (name, _) in GROUPS.items()}}
