"""Find a connection: the most specific chains between two entities of the network, the costs that decide it, and the page."""
import json

import pytest
from fastapi.testclient import TestClient

from rozvedka import actors, collect, db, paths, series, ties


@pytest.fixture
def network(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    db.init()
    collect.init()
    actors.init()
    ties.init()
    ents = [("Q1", "cyber", "Evil Corp", "Q1"), ("Q2", "state", "Federal Security Service", "Q2"),
            ("US:1", "person", "Maksim YAKUBETS", None), ("US:H", "org", "Big Holding", None), ("C1", "country", "Russia", "C1"),
            ("S1", "tool", "Mimikatz", None), ("US:X", "org", "Rostec", None), ("UK:Y", "org", "Rostec", None)]
    ev = json.dumps({"list": "US", "ref": "1", "url": "https://x", "quote": "Linked To: EVIL CORP"})
    links = [("US:1", "Q1", "us"), ("US:1", "Q2", "us"),                          # the specific chain, through a person
             ("Q1", "Q2", "reports"),                                             # a co-mention
             ("Q1", "US:H", "us"), ("US:H", "Q2", "us"),                          # through a hub …
             *[(f"US:L{i}", "US:H", "us") for i in range(60)],                    # … with 62 links
             ("Q1", "C1", "wikidata"), ("C1", "Q2", "wikidata"),                  # through a country
             ("Q1", "S1", "attack"), ("Q2", "S1", "attack"),                      # through a common tool
             ("US:X", "UK:Y", "uk")]                                              # an island
    with db.session() as con:
        for i in range(60):
            ents.append((f"US:L{i}", "org", f"Leaf {i}", None))
        con.executemany("INSERT INTO entities VALUES (?,?,?,?,'us','{}')", ents)
        con.executemany("INSERT INTO ties(a,b,rel,back,layer,weight,evidence) VALUES (?,?,'linked to','linked to it',?,1,?)",
                        [(a, b, layer, ev) for a, b, layer in links])
        for key, kind, label, _ in [e for e in ents if e[3]]:
            con.execute("INSERT INTO actors(key,kind,label,data) VALUES(?,?,?,'{}')", (key, kind, label))
            con.execute("INSERT INTO actor_names(actor_key,name,status,weak,langs,origins) VALUES(?,?,'used',0,'[]','[]')", (key, label))
    return tmp_path


def _route(c):
    return [n["id"] for n in c["nodes"]]


def test_most_specific_first_and_alternatives_avoid_its_entities(network):
    cs = paths.chains("Q1", "Q2")
    assert [_route(c) for c in cs] == [["Q1", "Q2"], ["Q1", "US:1", "Q2"], ["Q1", "S1", "Q2"], ["Q1", "US:H", "Q2"]]
    assert cs[0]["co_mention_only"] == [0] and cs[1]["co_mention_only"] == []
    assert cs[1]["cost"] == round(1 + 1 + paths.penalty(2), 2)
    assert cs[2]["cost"] == round(1.25 + 1.25 + paths.penalty(2) + paths.KIND_COST["tool"], 2)   # a common tool costs more
    assert cs[3]["hubs"][0]["id"] == "US:H"                       # 62 links: a hub, shown as such
    step = cs[1]["steps"][0]["links"][0]
    assert step["a"] == "US:1" and not step["forward"] and step["evidence"]["quote"] == "Linked To: EVIL CORP"


def test_layers_and_countries(network):
    assert [_route(c) for c in paths.chains("Q1", "Q2", layers=["us"])] == [["Q1", "US:1", "Q2"], ["Q1", "US:H", "Q2"]]
    with_countries = [_route(c) for c in paths.chains("Q1", "Q2", countries=True)]
    assert ["Q1", "C1", "Q2"] in with_countries
    assert paths.chains("Q1", "Q1") == [] and paths.chains("Q1", "NOPE") == []


def test_separate_parts(network):
    assert paths.chains("Q1", "US:X") == []
    a, b = paths.part("Q1"), paths.part("US:X")
    assert a["id"] != b["id"] and b["size"] == 2 and a["largest"]


def test_resolve_what_was_typed(network):
    assert paths.resolve("Evil Corp [Q1]")[0]["id"] == "Q1"
    assert paths.resolve("US:1")[0]["id"] == "US:1"
    assert paths.resolve("Evil Corp")[0]["id"] == "Q1"
    e, cands = paths.resolve("Rostec")                 # two list entries with the name: the user chooses
    assert e is None and {c["id"] for c in cands} == {"US:X", "UK:Y"}
    assert paths.resolve("nothing like it") == (None, [])


def test_pages(network):
    from rozvedka.app import app
    with TestClient(app) as client:
        page = client.get("/graph/path?a=Evil+Corp&b=Federal+Security+Service").text
        assert "Chain 1" in page and "Maksim YAKUBETS" in page and "Linked To: EVIL CORP" in page
        assert "Which “Rostec”?" in client.get("/graph/path?a=Rostec&b=Evil+Corp").text
        assert "separate parts of the network" in client.get("/graph/path?a=Evil+Corp&b=US:X").text
        assert "nothing in the network is called" in client.get("/graph/path?a=zzz&b=Evil+Corp").text
        assert client.get("/graph/path").status_code == 200
        s = client.get("/api/entities/suggest?q=Rost").json()["entities"]
        assert {e["id"] for e in s} == {"US:X", "UK:Y"} and s[0]["value"].endswith("]")
