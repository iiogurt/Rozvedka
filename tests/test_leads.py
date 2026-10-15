"""Leads (hypotheses from shared neighbours) and brokers (entities reaching several kinds of actor)."""
import json

import pytest
from fastapi.testclient import TestClient

from rozvedka import actors, collect, db, leads, series, ties


@pytest.fixture
def network(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(series, "SERIES_FILE", tmp_path / "series.yaml")
    monkeypatch.setattr(collect, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(leads, "REVIEWS", tmp_path / "lead_reviews.yaml")
    db.init()
    collect.init()
    actors.init()
    ties.init()
    acts = [("Q1", "terror", "Group One"), ("Q2", "crime", "Cartel Two"), ("Q3", "state", "Service Three"),
            ("Q4", "terror", "Group Four"), ("Q5", "country", "Somewhere")]
    others = [("US:F", "org", "Front Company"), ("US:P", "person", "Financier"), ("S1", "tool", "Mimikatz"),
              ("US:R", "org", "Rival Gang"), ("US:H", "org", "Hub")]
    ev = json.dumps({"list": "US", "ref": "1", "url": "u", "quote": "Linked To: X"})
    links = [("US:F", "Q1", "linked to"), ("US:F", "Q2", "linked to"), ("US:P", "Q1", "linked to"), ("US:P", "Q2", "linked to"),
             ("US:F", "Q3", "linked to"),                                   # the front company also reaches a state service
             ("Q1", "S1", "uses"), ("Q4", "S1", "uses"),                    # shared tool: not a lead
             ("Q1", "US:R", "opposed to"), ("Q4", "US:R", "opposed to"),    # shared rival: not a lead
             ("Q5", "US:F", "linked to"), ("Q5", "US:P", "linked to")]      # a country is never a lead
    links += [(f"US:L{i}", "US:H", "linked to") for i in range(leads.HUB)] + [("Q3", "US:H", "linked to"), ("Q4", "US:H", "linked to"),
                                                                              ("Q3", "US:P", "linked to")]
    with db.session() as con:
        for k, kind, label in acts:
            con.execute("INSERT INTO actors(key,kind,label,data) VALUES(?,?,?,'{}')", (k, kind, label))
        con.executemany("INSERT INTO entities VALUES (?,?,?,?,'us','{}')",
                        [(k, kind, label, k) for k, kind, label in acts] + [(k, kind, label, None) for k, kind, label in others]
                        + [(f"US:L{i}", "org", f"Leaf {i}", None) for i in range(leads.HUB)])
        con.executemany("INSERT INTO ties(a,b,rel,back,layer,weight,evidence) VALUES (?,?,?,?,?,1,?)",
                        [(a, b, rel, rel, "attack" if rel == "uses" else "us", ev) for a, b, rel in links])
        con.execute("INSERT INTO actor_pairs VALUES (1,'Q1','Q3',1)")             # named together once: not a lead
    return tmp_path


def test_leads(network):
    rows = leads.ranking()
    assert {(r["a"], r["b"]) for r in rows} == {("Q1", "Q2"), ("Q2", "Q3")}   # not Q1–Q4 (tool, rival, hub), Q1–Q3 (named together)
    assert all(r["shared"] == 2 for r in rows) and rows[0]["score"] == rows[1]["score"]
    d = leads.detail("Q2", "Q1")
    assert d["counted"] == 2 and {w["id"] for w in d["common"]} == {"US:F", "US:P"} and not d["direct"]
    assert d["common"][0]["a"][0]["evidence"]["quote"] == "Linked To: X"
    assert leads.detail("Q1", "Q5") is None                               # a country


def test_review_kept(network):
    assert leads.record("Q2", "Q1", "confirmed", "  both funded by the same front  ") == {"ok": True}
    assert leads.reviews()[("Q1", "Q2")]["note"] == "both funded by the same front"
    assert leads.record("Q1", "Q2", "maybe") == {"error": "unknown verdict"}
    assert "Linked To" not in (network / "lead_reviews.yaml").read_text() and "confirmed" in (network / "lead_reviews.yaml").read_text()


def test_brokers(network):
    rows = {r["id"]: r for r in leads.brokers()}
    assert set(rows) == {"US:F", "US:P", "US:H"}
    f = rows["US:F"]
    assert {(d["kind"], d["n"]) for d in f["domains"]} == {("terror", 1), ("crime", 1), ("state", 1)}
    assert ties.others(entity="US:F", other_kind="terror", group="connecting") == 1
    for label, n, url in leads.figures():
        if n < 0:
            q = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
            assert ties.others(**q) == -n, label


def test_pages(network):
    from rozvedka.app import app
    with TestClient(app) as client:
        assert "Cartel Two" in client.get("/graph/leads").text
        page = client.get("/graph/leads/Q1/Q2").text
        assert "share <b>2</b> counted neighbours" in page and "Front Company" in page
        r = client.post("/graph/leads/review", data={"a": "Q1", "b": "Q2", "verdict": "rejected", "note": "x"}, follow_redirects=False)
        assert r.status_code == 303 and leads.reviews()[("Q1", "Q2")]["verdict"] == "rejected"
        assert "rejected" in client.get("/graph/leads?status=rejected").text
        assert client.get("/graph/leads/Q1/NOPE").status_code == 404
        b = client.get("/graph/brokers").text
        assert "Front Company" in b
        assert "with <b>1</b> others" in client.get("/graph/ties?entity=US:F&other_kind=terror&group=connecting").text
        assert 'id="leads"' in client.get("/actors/Q1").text
