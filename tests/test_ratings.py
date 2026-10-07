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
                            "wgi_va": {"2010": 0.89, "2025": -0.04}},
                    "CZE": {"vdem_libdem": {"2010": 0.80, "2025": 0.78}, "vdem_regime": {"2010": 3, "2025": 3}}}}


@pytest.fixture
def store(tmp_path, monkeypatch):
    p = tmp_path / "ratings.json"
    p.write_text(json.dumps(STORE))
    monkeypatch.setattr(ratings, "STORE", p)
    ratings.load.cache_clear()
    yield p
    ratings.load.cache_clear()


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
