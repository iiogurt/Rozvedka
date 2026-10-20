"""Democracy ratings of states over time – the context of a state's reports."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from rozvedka import app as app_module
from rozvedka import collect, db, ratings, series, topics

STORE = {"retrieved": "2026-10-07", "iso3": {"HU": "HUN", "CZ": "CZE"},
         "measures": {"vdem_libdem": {"source": "https://ourworldindata.org/grapher/liberal-democracy-index",
                                      "citation": "V-Dem (2026)", "retrieved": "2026-10-07", "rows": 4}},
         "values": {"HUN": {"vdem_libdem": {"2008": 0.70, "2010": 0.68, "2018": 0.40, "2025": 0.32},
                            "vdem_regime": {"2008": 3, "2010": 2, "2018": 1, "2025": 1},
                            "wgi_va": {"2010": 0.89, "2025": -0.04},
                            "homicide": {"2015": 2.1, "2023": 0.8}, "wgi_pv": {"2025": 0.8}, "milex": {"2025": 2.1}},
                    "CZE": {"vdem_libdem": {"2010": 0.80, "2025": 0.78}, "vdem_regime": {"2010": 3, "2025": 3},
                            "homicide": {"2023": 0.6}, "wgi_pv": {"2025": 0.9}, "milex": {"2025": 1.3}}}}


@pytest.fixture
def store(tmp_path, monkeypatch):
    p = tmp_path / "ratings.json"
    p.write_text(json.dumps(STORE))
    monkeypatch.setattr(ratings, "STORE", p)
    ratings.load.cache_clear()
    ratings.ranks.cache_clear()
    yield p
    ratings.load.cache_clear()
    ratings.ranks.cache_clear()


def test_values_by_year(store):
    assert ratings.at("HU", "vdem_libdem", 2012) == (2010, 0.68)        # the latest value before the report's year
    assert ratings.at("HU", "vdem_libdem", None) == (2025, 0.32)
    assert ratings.at("HU", "vdem_libdem", 2000) is None
    assert ratings.at("EU", "vdem_libdem", 2010) is None                 # international bodies are not rated
    p = ratings.profile("HU", 2009)
    reg = p["measures"]["vdem_regime"]
    assert reg["then_label"] == "liberal democracy" and reg["latest_label"] == "electoral autocracy"
    assert [(c["year"], c["to"]) for c in reg["changes"]] == [(2010, "electoral democracy"), (2018, "electoral autocracy")]
    assert "country=HUN" in p["measures"]["vdem_libdem"]["url"]
    assert p["measures"]["wgi_va"]["url"].endswith("GOV_WGI_VA.EST?locations=HU")


@pytest.fixture
def library(tmp_path, monkeypatch, store):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    app_module._independent["at"] = None
    db.init()
    collect.init()
    topics.init()
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type,active) VALUES(1,'HU/AH','HU','AH','intelligence-civil',1)")
        con.execute("INSERT INTO sources(id,key,country,agency,type,active) VALUES(2,'CZ/BIS','CZ','BIS','intelligence-civil',1)")
        for i, src, year in ((1, 1, 2009), (2, 1, 2020), (3, 2, 2015)):
            con.execute("""INSERT INTO documents(id,source_id,url,title,lang,year,status,local_path)
                           VALUES(?,?,?,?,'en',?,'downloaded',?)""", (i, src, f"https://x/{i}.pdf", f"Report {i}", year, f"f{i}.pdf"))
    yield tmp_path
    app_module._independent["at"] = None


def test_pages(library):
    client = TestClient(app_module.app)
    t = client.get("/ratings").text
    assert t.index("Czechia") < t.index("Hungary")                        # most democratic first
    assert re.search(r'href="/documents\?country=HU&amp;type=official">2</a>', t)   # each count opens its list
    t = client.get("/ratings?sort=change").text
    assert t.index("Hungary") < t.index("Czechia")                        # largest decline first
    assert "When this report was written the state\n        was a liberal democracy" in client.get("/report/1").text
    assert "rt-warn" not in client.get("/report/2").text                  # same type since 2018: no warning
    assert "V-Dem LDI 0.32" in client.get("/sources").text


def test_democracy_map(library):
    d = ratings.map_data()
    assert d["years"][0] == 1990 and d["years"][-1] == 2025
    hu = d["countries"]["HU"]
    assert hu["library"] and hu["iso3"] == "HUN"
    assert hu["values"]["vdem_regime"][d["years"].index(2018)] == 1
    assert hu["values"]["vdem_libdem"][d["years"].index(2017)] is None    # no value that year: no colour, no guess
    client = TestClient(app_module.app)
    api = client.get("/api/ratings/map").json()
    assert api["reports"]["HU"] == {"2009": 1, "2020": 1}                 # official reports per publication year
    t = client.get("/map/democracy").text
    assert 'value="change"' in t and "map_democracy.js" in t
    assert 'href="/map/democracy"' in client.get("/map").text             # reachable from the other map views


def test_security_and_governance_measures(store):
    # every measure belongs to a group and says which end is better (none for military spending: context, not a grade)
    assert set(ratings.GROUPS) == {m["group"] for m in ratings.MEASURES.values()}
    assert ratings.MEASURES["homicide"]["better"] == "low" and ratings.MEASURES["milex"]["better"] is None
    assert {"wgi_pv", "wgi_rl", "wgi_cc", "wgi_ge", "wgi_rq"} <= set(ratings.MEASURES)
    # places among the library's states: fewer homicides first, more stability first, more spending first (a position)
    assert ratings.ranks("homicide") == {"CZ": (1, 2), "HU": (2, 2)}
    assert ratings.ranks("wgi_pv") == {"CZ": (1, 2), "HU": (2, 2)}
    assert ratings.ranks("milex") == {"HU": (1, 2), "CZ": (2, 2)}
    assert ratings.profile("HU")["measures"]["homicide"]["rank"] == (2, 2)
    assert ratings.at("HU", "homicide", None) == (2023, 0.8)


def test_group_pages_and_country_card(library):
    client = TestClient(app_module.app)
    t = client.get("/ratings?group=security").text
    assert "Intentional homicides per 100,000" in t and "↓ lower is better" in t and "neither end is better" in t
    assert t.index("Czechia") < t.index("Hungary")                         # sorted by the first measure's place
    t = client.get("/ratings?group=security&sort=milex").text
    assert t.index("Hungary") < t.index("Czechia")
    assert "Liberal Democracy Index" not in client.get("/ratings?group=governance").text.split("Where the ratings")[1]
    card = client.get("/ratings/hu")
    assert card.status_code == 200
    t = card.text
    assert "2. of 2" in t and 'href="/documents?country=HU&amp;topic=organised-crime&amp;type=official"' in t
    assert client.get("/ratings/EU").status_code == 404                     # international bodies are not rated
    assert 'href="/ratings/HU"' in client.get("/ratings").text              # every state opens its card
    d = ratings.map_data()
    assert d["measures"]["homicide"]["better"] == "low" and d["groups"]["security"] == "Security"
    assert '<optgroup label="Security">' in client.get("/map/democracy").text


def test_conflict_deaths_and_cyber_incidents_from_the_event_data(library):
    from rozvedka import events
    events.init()
    with db.session() as con:
        con.execute("INSERT INTO event_months VALUES('UA','2023-05',1000,3,1000,0,0,0)")
        con.execute("INSERT INTO event_months VALUES('UA','2023-06',500,2,500,0,0,0)")
        con.execute("INSERT INTO event_months VALUES('UA','2024-01',900,2,900,0,0,1)")     # preliminary: left out
        for k, y in (("eurepoc:1", 2022), ("eurepoc:2", 2023), ("eurepoc:3", 2023)):
            con.execute("INSERT INTO events(key,source,kind,label,start,year,url) VALUES(?,'eurepoc','cyber incident','x',?,?,'u')",
                        (k, f"{y}-01-01", y))
            con.execute("INSERT INTO event_countries VALUES(?, 'HU')", (k,))
    store = {"values": {}, "measures": {}, "iso2to3_all": {"UA": "UKR", "HU": "HUN"},
             "population": {"UKR": {"2023": 40_000_000}, "HUN": {"2023": 9_600_000}}}
    rows = ratings.event_measures(store, "2026-10-20")
    assert store["values"]["UKR"]["ucdp_deaths"]["2023"] == 1500 / 40_000_000 * 1e5         # per 100,000
    assert store["values"]["HUN"]["ucdp_deaths"]["2023"] == 0                                # no recorded death: 0
    assert "2024" not in store["values"]["UKR"]["ucdp_deaths"]                               # only preliminary months
    assert store["values"]["HUN"]["cyber_incidents"] == {"2022": 1.0, "2023": 2.0}
    assert store["values"]["UKR"]["cyber_incidents"] == {"2022": 0.0, "2023": 0.0}
    assert rows["cyber_incidents"] == 4 and ratings.MEASURES["cyber_incidents"]["better"] is None
    assert ratings.source_url("HU", "cyber_incidents") == "/events?source=eurepoc&country=HU"   # each count opens its incidents


def test_disaster_risk_measures_are_read(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, attempts=3):
        calls.append(url)
        if "GetByWorkflowGroup" in url:
            return json.dumps([{"WorkflowId": 505, "Name": "INFORM Risk 2026"}, {"WorkflowId": 506, "Name": "INFORM Risk 2026 - 2025"}]).encode()
        if "Countries/Scores" in url:
            return json.dumps([{"Iso3": "DEU", "IndicatorScore": 2.4}]).encode()
        if "Countries/Trends" in url:
            return json.dumps([{"IndicatorId": "INFORM", "GNAYear": 2025, "IndicatorScore": 2.4},
                               {"IndicatorId": "CC", "GNAYear": 2025, "IndicatorScore": 1.5},            # a sub-index: not the risk
                               {"IndicatorId": "INFORM", "GNAYear": 2024, "IndicatorScore": 2.5}]).encode()
        if url.endswith("worldriskindex-trend.csv"):
            return '"WRI.Country","ISO3.Code","Year","W"\n"Japan","JPN",2023,9.5\n"Japan","JPN",2024,NA\n'.encode()
        raise OSError("not used in this test")
    monkeypatch.setattr(ratings, "_get", fake_get)
    monkeypatch.setattr(ratings, "MEASURES", {k: ratings.MEASURES[k] for k in ("inform_risk", "world_risk")})
    monkeypatch.setattr(ratings, "_iso3_map", lambda: {"DE": "DEU", "JP": "JPN"})
    monkeypatch.setattr(ratings, "event_measures", lambda store, today: {})
    monkeypatch.setattr(ratings.countries, "names", lambda: {"DE": "Germany", "JP": "Japan"})
    real_get = fake_get
    monkeypatch.setattr(ratings, "_get", lambda url, attempts=3: real_get(url) if "SP.POP" not in url else json.dumps([{}, []]).encode())
    out = tmp_path / "r.json"
    ratings.fetch(out)
    store = json.loads(out.read_text())
    assert store["values"]["DEU"]["inform_risk"] == {"2025": 2.4, "2024": 2.5}     # the data year of each recomputed year
    assert store["values"]["JPN"]["world_risk"] == {"2023": 9.5}                     # NA left out
    assert any("Trends" in c and "iso3=DEU" in c for c in calls) and ratings.MEASURES["inform_risk"]["better"] == "low"
    ratings.load.cache_clear()
