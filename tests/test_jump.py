"""Jump to anything: names of pages, countries, agencies, actors, topics, reports and network entities → their pages."""
import pytest
from fastapi.testclient import TestClient

from rozvedka import actors, collect, db, jump, ties, topics


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    db.init()
    collect.init()
    actors.init()
    topics.init()
    with db.session() as con:
        con.executescript(ties.SCHEMA)
        con.execute("""INSERT INTO sources(id,key,country,agency,type,name_en,active)
                       VALUES(1,'EE/KAPO','EE','KAPO','intelligence-civil','Estonian Internal Security Service',1)""")
        con.execute("""INSERT INTO documents(id,source_id,url,title,lang,year,status)
                       VALUES(1,1,'https://kapo.ee/a.pdf','Annual Review 2024','en',2024,'downloaded')""")
        con.execute("INSERT INTO documents(id,source_id,url,title,lang,year,status,hidden) VALUES(2,1,'https://kapo.ee/b.pdf','Annual Review 2023','en',2023,'downloaded',1)")
        con.execute("INSERT INTO actors(key,kind,label) VALUES('Q1','cyber','Sandworm')")
        con.execute("INSERT INTO actors(key,kind,label) VALUES('Q2','cyber','Fancy Bear')")
        con.execute("INSERT INTO actors(key,kind,label,iso) VALUES('Q3','country','Sandland','SL')")
        con.execute("INSERT INTO actor_names(actor_key,name,status) VALUES('Q2','APT28','used')")
        con.execute("INSERT INTO actor_names(actor_key,name,status) VALUES('Q2','Sandy Bear','unused')")
        con.execute("INSERT INTO doc_actors(doc_id,actor_key,hits) VALUES(1,'Q1',3)")
        con.execute("INSERT INTO entities(id,kind,label,origin,actor) VALUES('Q1','cyber','Sandworm','wikidata','Q1')")
        con.execute("INSERT INTO entities(id,kind,label,origin) VALUES('S1','malware','Sandworm Toolkit','attack')")
    return tmp_path


def _of(r, kind):
    return next((g["items"] for g in r["groups"] if g["kind"] == kind), [])


def test_find(library):
    r = jump.find("sandw")
    assert [i["url"] for i in _of(r, "actor")] == ["/actors/Q1"] and "in 1 reports" in _of(r, "actor")[0]["sub"]
    assert [i["url"] for i in _of(r, "entity")] == ["/entity/S1"]             # the actor's own entity is not listed twice
    assert not _of(r, "country")                                             # a country is a country page, not an actor
    a = _of(jump.find("apt28"), "actor")
    assert a[0]["url"] == "/actors/Q2" and "also “APT28”" in a[0]["sub"]      # found by a name in use, and says so
    assert not _of(jump.find("sandy"), "actor")                              # a name not in use finds nothing
    assert _of(jump.find("eston"), "country")[0]["url"] == "/countries/EE"
    assert _of(jump.find("ee"), "country")[0]["label"] == "Estonia"           # by its code
    assert _of(jump.find("internal security"), "agency")[0]["url"] == "/agency/1"
    assert [i["url"] for i in _of(jump.find("annual review"), "report")] == ["/report/1"]    # hidden reports stay out
    assert _of(jump.find("ransom"), "topic")[0]["url"] == "/topics/ransomware"
    assert _of(jump.find("rings"), "page")[0]["url"] == "/graph/rings"
    assert jump.find("s")["groups"] == [] and jump.find("")["groups"] == [] and jump.find("zzzzqq")["groups"] == []
    assert not _of(jump.find("a_nual"), "report") and not _of(jump.find("ann%view"), "report")     # typed signs are no wildcards


def test_ranking():
    rows = [{"label": "Islamic State", "match": "Estado Islámico", "weight": 900}, {"label": "Estonia First", "weight": 1},
            {"label": "West Bank", "weight": 50}]
    assert [r["label"] for r in jump._best("est", rows, 5)] == ["Estonia First", "Islamic State", "West Bank"]


def test_endpoint_and_page(library):
    from rozvedka.app import app
    client = TestClient(app)
    d = client.get("/api/jump?q=eston").json()
    assert d["groups"][0]["kind"] == "country" and d["groups"][0]["items"][0]["flag"].endswith("ee.svg")
    assert client.get("/api/jump").json() == {"q": "", "groups": []}
    t = client.get("/documents").text
    assert 'id="jump"' in t and 'class="jump-open"' in t and 'id="trail"' in t and "jump.js" in t
