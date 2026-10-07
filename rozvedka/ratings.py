"""Democracy ratings of states over time – the context in which a state's reports were written.

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

`fetch-ratings` stores everything in data/ratings/ratings.json with the retrieval date and each source's citation."""
import csv
import datetime as dt
import io
import json
import logging
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

from . import countries
from .config import DATA

log = logging.getLogger("rozvedka.ratings")

STORE = DATA / "ratings" / "ratings.json"
UA = "Rozvedka/0.x (personal research library; https://github.com/iiogurt/Rozvedka)"
OWID = "https://ourworldindata.org/grapher/{slug}"
WB_API = "https://api.worldbank.org/v2"
REGIMES = {0: "closed autocracy", 1: "electoral autocracy", 2: "electoral democracy", 3: "liberal democracy"}

MEASURES = {
    "vdem_libdem": {"name": "Liberal Democracy Index", "by": "V-Dem", "short": "V-Dem LDI", "scale": (0, 1), "fmt": "{:.2f}",
                    "slug": "liberal-democracy-index", "column": "libdem_vdem__estimate_best",
                    "license": "CC BY-SA 4.0", "home": "https://www.v-dem.net/",
                    "about": "Expert-coded extent of liberal democracy: free and fair elections, freedoms of association "
                             "and expression, civil liberties, rule of law, constraints on the executive (0 = none, 1 = full)."},
    "vdem_regime": {"name": "Regimes of the World", "by": "V-Dem", "short": "V-Dem RoW", "scale": (0, 3), "fmt": "{}",
                    "slug": "political-regime", "column": "regime_row_owid", "license": "CC BY-SA 4.0",
                    "home": "https://www.v-dem.net/",
                    "about": "Classification from V-Dem data: closed autocracy, electoral autocracy, electoral democracy, "
                             "liberal democracy (Lührmann, Tannenberg & Lindberg 2018)."},
    "fh_score": {"name": "Freedom in the World score", "by": "Freedom House", "short": "FH", "scale": (0, 100), "fmt": "{:.0f}",
                 "slug": "freedom-score-fh", "column": "total_score",
                 "license": "Freedom House content: non-commercial use with attribution",
                 "home": "https://freedomhouse.org/report/freedom-world",
                 "about": "Political rights (0–40) and civil liberties (0–60) assessed by analysts; 100 = most free."},
    "wgi_va": {"name": "Voice and Accountability", "by": "World Bank (WGI)", "short": "WGI VA", "scale": (-2.5, 2.5), "fmt": "{:+.2f}",
               "indicator": "GOV_WGI_VA.EST", "license": "CC BY 4.0", "home": "https://www.worldbank.org/en/publication/worldwide-governance-indicators",
               "about": "Perceptions of citizens' ability to choose their government, freedom of expression and "
                        "association, and a free media; standard units, about −2.5 to +2.5."},
}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def _iso3_map() -> dict[str, str]:
    """ISO 3166 alpha-2 → alpha-3 from the World Bank's official country list (Taiwan, absent there, by name)."""
    data = json.loads(_get(f"{WB_API}/country?format=json&per_page=400"))
    return {c["iso2Code"]: c["id"] for c in data[1] if c.get("iso2Code")}


def fetch(out: Path | None = None) -> dict:
    """Download every measure for every country and year; returns counts."""
    today = dt.date.today().isoformat()
    names = countries.names()
    iso3 = _iso3_map()
    store = {"retrieved": today, "measures": {}, "iso3": {}, "values": {}}
    owid_names: dict[str, str] = {}
    for key, m in MEASURES.items():
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
    # library countries → alpha-3 (World Bank list; else the country's name as Our World in Data spells it)
    for code, name in names.items():
        a3 = iso3.get(code) or owid_names.get(name)
        if a3 and a3 in store["values"]:
            store["iso3"][code] = a3
    out = out or STORE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(store), encoding="utf-8")
    load.cache_clear()
    missing = sorted(c for c in names if c not in store["iso3"] and c not in ("EU", "NATO", "OTHER"))
    log.info("ratings: %s; library countries without ratings: %s", {k: v["rows"] for k, v in store["measures"].items()}, missing)
    return {"measures": {k: v["rows"] for k, v in store["measures"].items()}, "countries": len(store["iso3"]),
            "without_ratings": missing}


@lru_cache(maxsize=1)
def load(path: Path | None = None) -> dict:
    p = path or STORE
    if not p.exists():
        return {"retrieved": None, "measures": {}, "iso3": {}, "values": {}}
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


def source_url(country: str, key: str) -> str:
    """Where a reader checks the value: the chart for that country, or the World Bank indicator page."""
    m = MEASURES[key]
    a3 = load()["iso3"].get(country, "")
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
                                "url": source_url(country, key), "citation": load()["measures"].get(key, {}).get("citation")}
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
