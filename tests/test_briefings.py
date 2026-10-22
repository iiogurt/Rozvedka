"""Briefing pages: one topic and one country, and that every number opens exactly the reports it counts."""
from fastapi.testclient import TestClient

from rozvedka import actors, briefings, db, topics
from test_trends import library  # noqa: F401  – the tiny library


def _actors(monkeypatch):
    from rozvedka import collect
    monkeypatch.setattr(collect, "INBOX", db.DB_PATH.parent / "inbox")
    collect.init()
    monkeypatch.setattr(briefings, "MIN_DOCS", 1)
    actors.init()
    with db.session() as con:
        con.execute("INSERT INTO actors(key,kind,label,data,iso) VALUES('Q159','country','Russia','{}','RU')")
        con.execute("INSERT INTO actors(key,kind,label,data) VALUES('Q1','cyber','Lockbit','{}')")
        con.execute("""INSERT INTO actors(key,kind,label,data) VALUES('Q2','state','BIS','{"countries": [{"iso": "CZ"}]}')""")
        for doc, key in ((1, "Q159"), (2, "Q159"), (3, "Q1"), (4, "Q1"), (1, "Q2"), (2, "Q2"), (3, "Q159")):
            con.execute("INSERT INTO doc_actors(doc_id,actor_key,hits) VALUES(?,?,1)", (doc, key))


def test_topic_briefing(library, monkeypatch):
    _actors(monkeypatch)
    d = briefings.topic("ransomware")
    assert d["n"] == 2 and [k["n"] for k in d["kinds"]] == [2, 0, 0]
    assert [(y["year"], y["official"]) for y in d["years"]] == [(2024, 2)] and d["years"][0]["of"] == 3
    assert [(r["country"], r["n"], r["of"]) for r in d["countries"]] == [("DE", 2, 3)]      # of 3: one is undated
    assert [r["key"] for r in d["actors"]] == ["Q1"]                     # Lockbit: in both ransomware reports, 2 of 5 overall
    assert d["actors"][0]["lift"] == 2.5 and "actor=Q1" in d["actors"][0]["link"]
    assert briefings.topic("nope") is None


def test_country_briefing_leaves_out_its_own_agencies(library, monkeypatch):
    _actors(monkeypatch)
    d = briefings.country("CZ")
    assert d["n"] == 2 and [s["n"] for s in d["sources"]] == [2]
    assert [r["key"] for r in d["topics"]] == ["russia", "sabotage"] and d["actors"] == []    # BIS names itself: left out
    de = briefings.country("DE")
    assert [r["key"] for r in de["actors"]] == ["Q1"]
    assert de["about"] == [] and de["me"] is None               # Germany is no actor in this library
    with db.session() as con:
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(3,'RU/X','RU','X','other')")
    ru = briefings.country("RU")
    assert [(r["country"], r["n"]) for r in ru["about"]] == [("CZ", 2), ("DE", 1)]
    assert briefings.country("XX") is None


def test_numbers_open_their_lists(library, monkeypatch):
    _actors(monkeypatch)
    from rozvedka.app import app
    c = TestClient(app)
    for label, n, url in briefings.figures("ransomware", "CZ"):
        t = c.get(url).text
        assert f"<b>{n}</b> documents match" in t, (label, n, url)
    assert c.get("/topics/ransomware").status_code == 200 and c.get("/countries/CZ").status_code == 200
    assert "Czech" in c.get("/countries").text or "CZ" in c.get("/countries").text
    assert c.get("/topics/map").status_code == 200            # the mind map keeps its address
    with db.session() as con:                                 # a state whose agencies have no reports yet
        con.execute("INSERT INTO sources(id,key,country,agency,type) VALUES(9,'MT/X','MT','X','other')")
    assert c.get("/countries/MT").status_code == 200
